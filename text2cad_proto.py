"""text2cad:图片 → Kimi 看图(带思考)→ DeepSeek 理解 → 追问澄清 → 写代码(自纠错)→ cadgen 出 STEP。

架构(五阶段):
  感知   Kimi(视觉推理)看图 → {描述, 思考}
  理解   DeepSeek 深度思考 → 理解卡(是什么/策略/不确定点)
  澄清   不确定点 → 弹窗问用户(选项+自定义)
  生成   DeepSeek 拿「理解卡+澄清结果」写 build123d
  纠错   报错→喂回→重试

CLI 用法: python text2cad_proto.py 图1 图2 图3 --note "..." --name xxx
Web 用法: 见 web_app.py(调用 run_pipeline 传入 clarify 回调)
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import requests
from PIL import Image

# 让 print 实时输出(Web 端日志不缓冲)
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

MOONSHOT_BASE = "https://api.moonshot.cn/v1"
DEEPSEEK_BASE = "https://api.deepseek.com/v1"
VISION_MODEL = "kimi-k3"
CODE_MODEL = "deepseek-v4-flash"        # 默认快速模型(前端「精细」可切 pro)
AUX_MODEL = "deepseek-v4-flash"         # 理解/加工/纠错等辅助步骤(快)
MAX_ATTEMPTS = 6
MAX_EDGE = 1280

import os

CODE_ROOT = Path(__file__).resolve().parent
# 数据目录(产物/账单等)可用 ZW_DATA_DIR 覆盖,便于容器部署时挂数据卷
WORKSPACE = Path(os.environ.get("ZW_DATA_DIR", str(CODE_ROOT)))
SKILLS = CODE_ROOT / "text-to-cad" / "skills" / "cad" / "scripts"
GEN = SKILLS / "gen"
INSPECT = SKILLS / "inspect"
SNAPSHOT = SKILLS / "snapshot"

# ---------------------------------------------------------------- 提示词

VISION_PROMPT = (
    "你是 CAD 逆向建模的『视觉观察员』。你会收到同一物体的 1~3 张照片(不同角度)。\n"
    "请先【思考】:这可能是什么物体、属于哪一类、对参数化建模最关键的结构是什么、哪里拿不准;\n"
    "然后再给出【描述】,分点:\n"
    "1) 这是什么物体,用途;\n"
    "2) 整体外形与朝向(哪个面是底面/放置面);\n"
    "3) 可见特征(孔/槽/圆角/凸台/文字等)及数量、位置(注明视角);\n"
    "4) 长宽高大致比例;\n"
    "5) 看不到的部分(背面/内部/厚度)。\n"
    "不要编造毫米尺寸;不确定就写不知道。"
)

UNDERSTAND_SYSTEM = (
    "你是 CAD 逆向建模的『理解器』。给你视觉观察员的描述(含其思考)与用户补充说明,"
    "你要输出一张『理解卡』JSON。只输出 JSON,不要任何其它文字。\n"
    "第一步【内置知识回忆】:先回忆这类物体在参数化建模中应有的构造,写进 shape_plan:"
    "外部构造(外形/轮廓/突起/曲面特征)、内部构造(空腔/加强筋/螺丝柱/壁厚)、组成方式(一体/分件/装配)。\n"
    "第二步【缺口盘点】:对比用户描述,把『会实质影响几何、但用户没说』的信息全部列成 uncertainties,"
    "至少 5 个、最多 12 个;每个 3~4 个选项,第一个必须是基于常识的推荐默认值,"
    "最后一个选项固定为「我来填」;问题要具体到数值或结构选择,按顺序:整体尺寸→主体结构→关键比例→细节特征→制造工艺→用途。\n"
    "思考务必从简:直接给出结论,不要长篇分析,不要复述输入。\n"
    "JSON 结构:\n"
    "{\n"
    '  "object": "这是什么物体(中文,简短)",\n'
    '  "category": "类别(如 household_appliance/tool/electronics/furniture/toy_figure)",\n'
    '  "confidence": "high|medium|low",\n'
    '  "is_assembly": true|false,\n'
    '  "shape_plan": "外部构造/内部构造/组成方式 + 建模思路",\n'
    '  "strategy": "box_block|revolved|extruded_profile|assembly|shell",\n'
    '  "uncertainties": [\n'
    '    {"field":"...","critical":true,"question":"用中文问用户","options":["推荐默认值","选项2","选项3","我来填"]}\n'
    '  ],\n'
    '  "assumptions": ["已默认掉的假设..."]\n'
    "}\n"
    "规则:\n"
    "1. uncertainties 至少 5 个、最多 12 个,全部 critical=true;每个 3~4 个选项,"
    "第一个选项是推荐默认值,最后一个固定为「我来填」;\n"
    "2. 尺寸、结构、比例、工艺、用途等影响建模的点都要问,不要硬猜;\n"
    "3. 颜色/材质/logo 等不影响几何的不放进 uncertainties,写进 assumptions;\n"
    "4. 信息越少的问题越多:只说『做个皮卡丘手办』这类模糊需求要问满 10~12 个;"
    "描述很详细时可少问,但不得少于 5 个。"
)

REFINE_SYSTEM = (
    "你是资深机械工程师。用户给你一段(可能很模糊的)需求描述,你要把它加工成一份『工程化建模需求』,"
    "让下游 CAD 建模能直接照做。\n"
    "从机械工程师视角补充(能推断的就给合理默认值,并在后面标注『(推断)』):\n"
    "1. 明确外形与结构(用工程语言);\n"
    "2. 关键尺寸(mm):能推断的给数值并标『(推断)』,缺的单独列出来;\n"
    "3. 制造工艺建议(3D打印/CNC/钣金/注塑)及它带来的默认壁厚、圆角;\n"
    "4. 关键特征清单(孔/槽/圆角/凸台/配合/装配关系);\n"
    "5. 需要向用户确认的关键问题:至少 5 个、最多 12 个,覆盖整体尺寸、主体结构、关键比例、"
    "细节特征、制造工艺、用途;每个给一个推荐默认值。\n"
    "输出纯文本(不要 JSON),要点式、条理清晰。思考从简:直接写正文,不要复述分析过程。"
)

# 一段「能跑通」的参考代码(few-shot,让模型照葫芦画瓢)
EXAMPLE = '''from build123d import *

length = 160.0
width = 50.0
thickness = 18.0
corner_r = 6.0
front_z = thickness / 2.0

def gen_step():
    with BuildPart() as p:
        Box(length, width, thickness)
        fillet(p.edges().filter_by(Axis.Z), corner_r)
        with BuildSketch(Plane.XY.offset(front_z)) as s:
            with Locations((42.0, 0.0)):
                RectangleRounded(52.0, 36.0, 6.0)
        extrude(amount=-0.8, mode=Mode.SUBTRACT)
        for by in (-15.0, 0.0, 15.0):
            with Locations((8.0, by, front_z + 1.0)):
                Cylinder(4.0, 2.0)
    return p.part
'''

CODE_SYSTEM = (
    "你是一名资深 CAD 参数化建模工程师,使用 Python 的 build123d 库。\n"
    "规则:\n"
    "1. 只输出一个 Python 代码块,内容是一个完整建模脚本,不要解释文字。\n"
    "2. 必须 `from build123d import *`,定义 `def gen_step():` 返回一个 STEP 就绪实体。\n"
    "3. 严格依据给出的「理解卡 + 澄清结果」建模:尺寸、结构、策略以它们为准,别自己另起炉灶。\n"
    "4. 单实体用 `with BuildPart() as p:` 上下文,`with Locations((x,y,z)):` 定位,最后 `return p.part`;"
    "不要用 `part += key` 手动布尔、不要丢弃 .moved() 返回值。\n"
    "5. 多零件(is_assembly)用 `from cadgen.assembly import AssemblyHelper` 的 asm.add()/asm.add_module()/asm.build()。\n"
    "6. 圆角 `fillet(p.edges().filter_by(Axis.Z), r)`,半径别超过相邻面尺寸(厚度18就别用R12,用R6左右)。\n"
    "7. 凹槽/孔用 `with BuildSketch(Plane.XY.offset(z)) as s: ...` + `extrude(amount=-d, mode=Mode.SUBTRACT)`。\n"
    "8. 细节要到位:按键/凸台边缘加小圆角,长条键用 RectangleRounded,别用光秃秃方块/圆柱。\n"
    "9. 旋转体(瓶身等)用 Cylinder(r, h)。\n"
    "10. 避坑:不要用 `with Rot(...)`(它不是上下文管理器);要旋转用 `with Locations(Location((0,0,z),(0,0,angle)))` 或 Cylinder(rotation=...)。\n"
    "11. 避坑:RectangleRounded(w,h,r) 的 r 必须严格 < min(w,h)/2,取 min(w,h)/4 更稳。\n"
    "12. 避坑:fillet 半径保守(0.3~1.0);报 'Failed creating fillet' 就减小半径或删掉该圆角。\n"
    "13. 避坑:只给确定安全的长直边加圆角(底板/外壳外棱);与孔、凸台、槽口相交的边一律不要圆角,"
    "chamfer 只在用户明确要求时使用;宁可不圆角,也要保证能生成。\n"
    "14. 关键尺寸必须定义为模块顶层的具名常量(如 `length = 160.0`、`width = 50.0`、`hole_d = 4.0`),"
    "代码里引用这些常量、不要重复写裸数字——用户生成后要用滑杆微调尺寸,全靠这些常量。"
    "变量名必须是有意义的英文语义名(length/width/thickness/hole_d/corner_r 这种),"
    "禁止用 a/b/c/x1 这类无意义名字。\n"
    "15. 若给了【外观造型说明书】,严格按其中的部件清单、几何基元、数字比例建模,"
    "不得自行更改造型或省略标志性特征。\n"
    "16. 标准件/成熟特征的可靠写法(需要这些特征时优先照抄):\n"
    "· 六角头/螺母体:with BuildSketch() as s: RegularPolygon(s/1.732, 6, major_radius=True) 然后 extrude(amount=h);"
    "内六角孔同理在 Plane.XY.offset(k*0.6) 上画六边形后 extrude(amount=-深, mode=Mode.SUBTRACT)。\n"
    "· 简化装饰螺纹:Torus(major_radius=d/2, minor_radius=pitch*0.28, mode=Mode.SUBTRACT),"
    "用 with Locations((0,0,z)): 沿轴向等距放置。\n"
    "· 渐开线齿轮:在 BuildSketch 里先 Circle(齿根半径),再对每个齿用 with BuildLine(): Polyline(*采样点, close=True) + make_face();"
    "齿形点由渐开线公式 x=rb*(cos t+t sin t), y=rb*(sin t - t cos t) 采样,镜像出另一侧齿面。\n"
    "· 装配体:每个零件一个独立 BuildPart,最后 AssemblyHelper 的 asm.add(part.part, '零件名', Location(...))、asm.build()。\n"
    "思考从简:先在脑内定方案,然后直接写代码,不要输出任何分析/注释性解释。\n"
    "代码块格式:```python\\n...\\n```\n\n【参考示例】\n" + EXAMPLE
)

FIX_SYSTEM = (
    "你是 build123d 调试专家。下面是用户的 build123d 脚本和运行报错。"
    "请修复错误,只输出修正后的完整代码块(```python ... ```),不要解释。"
    "保持命名参数和结构,只改导致报错的部分;若写法不可靠,换成参考示例里的等价安全写法。"
    "统一用 `with BuildPart() as p:` 上下文,不要手动布尔、不要丢弃 .moved() 的返回值。\n"
    "铁律:\n"
    "· 同一个几何特征(某条边的 fillet/chamfer)在【历史报错】里已经失败过,就【整行删除该操作】,"
    "绝对不要再用更小的半径继续尝试;宁可没有圆角,也要让模型能生成;\n"
    "· 布尔/挖孔失败 → 检查草图是否超出实体、深度是否穿透,改小尺寸或位置。\n"
    "常见报错→修法:\n"
    "· 'Rotation object does not support the context manager' → 去掉 with Rot(...),改用 Location 定位或省略旋转;\n"
    "· 'width and height must be > 2*radius' → RectangleRounded 的 radius 改小到 min(w,h)/4;\n"
    "· 'Failed creating a fillet with radius' → 第一次失败可把半径减到 0.5,再次失败直接删除该 fillet;\n"
    "· 'Failed creating a chamfer' → 直接删除该 chamfer。"
)

MODIFY_SYSTEM = (
    "你是 build123d 修改专家。给你一段当前能跑的 build123d 脚本,和用户的修改意见(标签)。\n"
    "请思考用户的意见,只修改相关的部分(改参数或局部几何),保持其它部分不变,"
    "输出完整修改后的代码块(```python ... ```),不要解释。\n"
    "如果用户给了 `#` 开头的引用(如 #o1.2 或 #o1.2.f1),表示要改的是这个零件/面,只改它,不要动其它部分。\n"
    "同样遵守:用 `with BuildPart() as p:` 上下文;不要 with Rot(...);RectangleRounded 半径 < min(w,h)/2;fillet 半径保守。\n"
    "如果意见里没给具体数值,基于常识给合理默认值。"
)


class PipelineError(Exception):
    """流水线错误(供 CLI 与 Web 统一捕获)。"""


def die(msg: str) -> "NoReturn":
    print(f"[FATAL] {msg}", file=sys.stderr)
    raise PipelineError(msg)


def _key(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        die(f"环境变量 {name} 未设置(先 setx {name} \"sk-...\" 并重启终端)")
    return v


def prepare_image(path: str) -> str:
    im = Image.open(path).convert("RGBA")
    bg = Image.new("RGB", im.size, (255, 255, 255))
    bg.paste(im, mask=im.split()[3])
    bg.thumbnail((MAX_EDGE, MAX_EDGE), Image.LANCZOS)
    buf = io.BytesIO()
    bg.save(buf, format="JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _extract_code(content: str) -> str:
    if not content:
        die("模型返回 content 为空")
    for block in re.findall(r"```[^\n]*\n(.*?)```", content, re.DOTALL):
        if "def gen_step" in block:
            return block.strip()
    if "def gen_step" in content:
        return content.strip()
    print("[DEBUG] 模型原始返回前 800 字符:\n" + content[:800], file=sys.stderr)
    die("模型返回的内容里没找到 gen_step()")


def _extract_json(content: str) -> dict:
    if not content:
        die("理解器返回为空")
    m = re.search(r"```(?:json)?\s*\n(.*?)```", content, re.DOTALL)
    if m:
        content = m.group(1)
    start = content.find("{")
    if start < 0:
        print("[DEBUG] 理解器原始返回:\n" + content[:800], file=sys.stderr)
        die("理解器没返回 JSON")
    for end in range(len(content), start, -1):
        try:
            return json.loads(content[start:end])
        except json.JSONDecodeError:
            continue
    print("[DEBUG] 理解器原始返回:\n" + content[:800], file=sys.stderr)
    die("理解器返回的 JSON 无法解析")


# 每线程上下文:token 计数与模型选择都放线程内,多用户并发时不串账、不串模型
import threading

_ctx = threading.local()


def reset_token_usage() -> None:
    _ctx.tokens = 0


def get_token_usage() -> int:
    return int(getattr(_ctx, "tokens", 0))


def _add_tokens(n) -> None:
    try:
        _ctx.tokens = get_token_usage() + int(n)
    except (TypeError, ValueError):
        pass


def set_model_overrides(code: str | None = None, vision: str | None = None, aux: str | None = None) -> None:
    """在本线程内覆盖本次任务的模型(默认取模块级常量,CLI 直跑不受影响)。

    精细模式:code 与 aux 都给 pro(整理规格/理解/写代码三步全精细);
    快速模式:aux 为 None 时回落 AUX_MODEL(flash)。
    """
    _ctx.code_model = code or CODE_MODEL
    _ctx.vision_model = vision or VISION_MODEL
    _ctx.aux_model = aux or AUX_MODEL


def _code_model() -> str:
    return str(getattr(_ctx, "code_model", CODE_MODEL))


def _aux_model() -> str:
    return str(getattr(_ctx, "aux_model", AUX_MODEL))


def _vision_model() -> str:
    return str(getattr(_ctx, "vision_model", VISION_MODEL))


def set_heartbeat(fn) -> None:
    """在本线程注册心跳回调:大模型调用期间每 30 秒触发一次(喂看门狗,证明任务活着)。"""
    _ctx.heartbeat = fn


def _post_with_heartbeat(url, headers, json=None, timeout=400, pulse_sec=30):
    """阻塞 POST,期间每 pulse_sec 秒打一次心跳(在调用线程捕获回调,再交给心跳线程)。"""
    hb = getattr(_ctx, "heartbeat", None)
    if hb is None:
        return requests.post(url, headers=headers, json=json, timeout=timeout)
    stop = threading.Event()

    def _pulse():
        while not stop.wait(pulse_sec):
            try:
                hb()
            except Exception:  # noqa: BLE001
                pass

    t = threading.Thread(target=_pulse, daemon=True)
    t.start()
    try:
        return requests.post(url, headers=headers, json=json, timeout=timeout)
    finally:
        stop.set()
        t.join(timeout=1)


def _ds_call(system: str, user: str, model: str | None = None) -> str:
    payload = {
        "model": model or _code_model(),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    for _attempt in range(3):
        r = _post_with_heartbeat(
            f"{DEEPSEEK_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {_key('DEEPSEEK_API_KEY')}", "Content-Type": "application/json"},
            json=payload, timeout=400,
        )
        if r.status_code != 200:
            die(f"DeepSeek HTTP {r.status_code}: {r.text[:400]}")
        d = r.json()
        _add_tokens((d.get("usage") or {}).get("total_tokens", 0))
        msg = d["choices"][0]["message"]
        content = msg.get("content") or ""
        if content:
            return content
        # 推理模型偶尔只输出思考、不输出正文,稍等重试
        time.sleep(2)
    die("模型连续多次都没输出结果,请稍后重试")


# ---------------------------------------------------------------- 阶段0:看图
def vision_describe(images: list[str]) -> dict:
    print(f"[1/5] Kimi 看图({len(images)} 张)...")
    parts = [{"type": "image_url", "image_url": {"url": prepare_image(p)}} for p in images]
    parts.append({"type": "text", "text": VISION_PROMPT})
    payload = {
        "model": _vision_model(),
        "messages": [{"role": "user", "content": parts}],
    }
    r = _post_with_heartbeat(
        f"{MOONSHOT_BASE}/chat/completions",
        headers={"Authorization": f"Bearer {_key('MOONSHOT_API_KEY')}", "Content-Type": "application/json"},
        json=payload, timeout=200,
    )
    if r.status_code != 200:
        die(f"Kimi HTTP {r.status_code}: {r.text[:400]}")
    d = r.json()
    _add_tokens((d.get("usage") or {}).get("total_tokens", 0))
    msg = d["choices"][0]["message"]
    return {
        "description": msg.get("content") or "",
        "reasoning": msg.get("reasoning_content") or "",
    }


# ---------------------------------------------------------------- 阶段0.5:提示词加工
def refine_prompt(raw_text: str) -> str:
    print("[1.5/5] 提示词加工(机械工程师视角)...")
    user = f"【用户原始需求】\n{raw_text}\n\n请加工成工程化建模需求。"
    refined = _ds_call(REFINE_SYSTEM, user, model=_aux_model())
    print("    工程化需求已生成,", len(refined), "字符")
    return refined


# ---------------------------------------------------------------- 阶段0.6:外观造型调研
APPEARANCE_SYSTEM = (
    "你是三维建模的『外观造型调研员』。用户要做一个东西,你要基于自己的知识,"
    "输出一份【极其详细的外观造型说明书】,让参数化建模程序照着建就能『像』。\n"
    "必须逐项给出具体数字比例,不要空话:\n"
    "1. 整体轮廓与姿态:侧影/正面轮廓是什么样的,总高、宽、厚之间的数字比例;\n"
    "2. 身体各部分清单:每个部件的形状(用哪种几何基元近似:球/椭球/圆锥/圆台/圆柱/旋转体/拉伸体/扫掠)、"
    "相对全身的比例尺寸、位置、朝向;\n"
    "3. 标志性特征:让人一眼认出的特征,给出精确数字比例"
    "(如耳长=0.8 头高、耳尖黑色占耳长 1/3、尾巴为 N 段折线的闪电形、脸颊圆斑直径=0.3 头宽…);\n"
    "4. 颜色/材质分界(影响分件、刻线与浮雕);\n"
    "5. 内部构造与制造考虑(壁厚/支撑/分件插接/底座配重)。\n"
    "输出纯文本,300~600 字,全部给具体数字。"
)


def research_appearance(raw_text: str) -> str:
    print("[1.6/5] 外观造型调研(DeepSeek 内置知识)…")
    content = _ds_call(
        APPEARANCE_SYSTEM,
        f"【用户需求与工程化描述】\n{raw_text}\n\n请输出外观造型说明书。",
        model=_aux_model(),
    )
    print("    外观造型说明书已生成,", len(content), "字符")
    return content


# ---------------------------------------------------------------- 阶段1:理解
def understand(refined: str, note: str, appearance: str = "") -> dict:
    print("[2/5] DeepSeek 深度理解(这是什么、怎么建、哪里拿不准)...")
    app = f"【外观造型说明书(极重要,以此为准)】\n{appearance}\n\n" if appearance else ""
    user = (
        f"{app}"
        f"【工程化需求】\n{refined}\n\n"
        f"【用户原始补充】\n{note or '(无)'}\n\n"
        "请输出理解卡 JSON。"
    )
    content = _ds_call(UNDERSTAND_SYSTEM, user, model=_aux_model())
    card = _extract_json(content)
    card.setdefault("uncertainties", [])
    card.setdefault("assumptions", [])
    print("    理解:", card.get("object"), "| 置信度", card.get("confidence"), "| 不确定点", len(card["uncertainties"]))
    return card


# ---------------------------------------------------------------- 阶段3:生成
def generate_code(card: dict, refined: str, answers: dict, appearance: str = "") -> str:
    print("[3/5] DeepSeek 写 build123d 代码 ...")
    clar = json.dumps(answers, ensure_ascii=False) if answers else "(无,按理解卡默认)"
    app = f"【外观造型说明书(造型的最终依据,严格按此建模)】\n{appearance}\n\n" if appearance else ""
    user = (
        f"请依据下面的外观造型说明书、理解卡和工程化需求,写一个 build123d 建模脚本。\n\n"
        f"{app}"
        f"【理解卡】\n{json.dumps(card, ensure_ascii=False, indent=2)}\n\n"
        f"【工程化需求】\n{refined}\n\n"
        f"【澄清结果(用户对不确定点的回答)】\n{clar}\n"
    )
    code = _extract_code(_ds_call(CODE_SYSTEM, user))
    print("    代码生成完成,", len(code), "字符")
    return code


# ---------------------------------------------------------------- 纠错
def fix_code(code: str, error: str, history: list[str] | None = None) -> str:
    hist = ""
    if history:
        hist = "【历史报错(同一任务的之前失败记录)】\n" + "\n".join(f"- {h[-300:]}" for h in history[-4:]) + "\n\n"
    content = _ds_call(FIX_SYSTEM, f"{hist}【最新报错】\n{error[-2000:]}\n\n【原代码】\n{code}", model=AUX_MODEL)
    return _extract_code(content)


def modify_code(code: str, tags: list[str], ref: str = "") -> str:
    print(f"    [修改] 意见: {'; '.join(tags)}" + (f" | 引用: {ref}" if ref else ""))
    ref_line = f"【目标引用(3D 里点选的零件/面)】\n{ref}\n\n" if ref else ""
    user = (
        f"【当前代码】\n{code}\n\n"
        f"{ref_line}"
        f"【用户修改意见】\n" + "\n".join(f"- {t}" for t in tags) + "\n\n"
        "请输出修改后的完整代码。若给了 #引用,只修改该零件/面,不要动其它部分。"
    )
    return _extract_code(_ds_call(MODIFY_SYSTEM, user))


def extract_labels(code: str) -> list[str]:
    """从代码里提取 asm.add()/asm.add_module() 的零件标签,供前端点击选择。"""
    labels = set()
    for m in re.findall(r'asm\.add\([^,]*,\s*"([^"]+)"', code):
        labels.add(m)
    for m in re.findall(r'asm\.add_module\(\s*"([^"]+)"', code):
        labels.add(m)
    return sorted(labels)


# 参数微调:顶层具名常量 → 中文标签
PARAM_LABELS = {
    "length": "长度", "width": "宽度", "height": "高度", "thickness": "厚度", "wall": "壁厚",
    "wall_thickness": "壁厚", "depth": "深度", "radius": "半径", "diameter": "直径",
    "dia": "直径", "corner_r": "圆角", "corner_radius": "圆角", "fillet_r": "圆角",
    "outer_corner_radius": "外圆角", "inner_corner_radius": "内圆角",
    "bottom_thickness": "底厚", "top_thickness": "顶厚", "bottom_h": "底高",
    "hole_d": "孔径", "hole_dia": "孔径", "hole_diameter": "孔径", "hole_radius": "孔半径",
    "hole_spacing": "孔间距", "hole_count": "孔数",
    "base_length": "底座长", "base_width": "底座宽", "base_h": "底座高", "base_height": "底座高",
    "spacing": "间距", "pitch": "间距", "margin": "边距", "offset": "偏移",
    "fin_h": "鳍片高", "fin_t": "鳍片厚", "fin_height": "鳍片高", "fin_count": "鳍片数",
    "rib_h": "筋高", "rib_t": "筋厚", "rib_width": "筋宽",
    "bore": "孔径", "count": "数量", "screw": "螺径", "slot_w": "槽宽", "slot_d": "槽深",
    "post_h": "柱高", "post_d": "柱径", "boss_h": "凸台高", "boss_d": "凸台径",
}


# 关键词兜底:任意命名都能翻译成中文(顺序即优先级,具体词在前)
PARAM_KEYWORDS = [
    ("length", "长度"), ("width", "宽度"), ("height", "高度"), ("thick", "厚度"),
    ("fillet", "圆角"), ("chamfer", "倒角"), ("radius", "半径"),
    ("diameter", "直径"), ("hole", "孔"), ("bore", "孔径"),
    ("depth", "深度"), ("space", "间距"), ("pitch", "间距"), ("count", "数量"),
    ("margin", "边距"), ("offset", "偏移"), ("slot", "槽"), ("fin", "鳍片"),
    ("rib", "筋"), ("boss", "凸台"), ("post", "柱"), ("flange", "法兰"),
    ("shaft", "轴"), ("screw", "螺钉"), ("nut", "螺母"), ("base", "底座"),
    ("plate", "板"), ("wall", "壁厚"), ("corner", "圆角"), ("size", "尺寸"),
]


def _param_label(key: str) -> str:
    k = key.lower()
    if key in PARAM_LABELS:
        return PARAM_LABELS[key]
    if k in PARAM_LABELS:
        return PARAM_LABELS[k]
    for kw, label in PARAM_KEYWORDS:
        if kw in k:
            return label
    return "尺寸"


def extract_params(code: str) -> list[dict]:
    """提取顶层具名数值常量(生成后可滑杆微调的参数)。

    过滤规则:引用次数>=2 才保留;无名常量(翻译不出含义)需引用>=3;
    有含义的优先,最多暴露 20 个,避免参数面板刷屏。
    """
    out: list[dict] = []
    seen: set[str] = set()
    for m in re.finditer(r"^([A-Za-z_]\w*)\s*=\s*(-?\d+(?:\.\d+)?)\s*$", code, re.M):
        key, val = m.group(1), float(m.group(2))
        if key.startswith("_") or key in seen:
            continue
        refs = len(re.findall(rf"\b{re.escape(key)}\b", code))
        if refs < 2:
            continue
        label = _param_label(key)
        if refs < 3 and label == "尺寸":  # 一次性/无意义常量不暴露
            continue
        seen.add(key)
        out.append({"key": key, "value": val, "label": label})
    out.sort(key=lambda p: (0 if p["label"] != "尺寸" else 1, -abs(p["value"])))
    return out[:20]


def substitute_params(code: str, params: dict) -> str:
    """把顶层具名常量替换成新值(仅允许 extract_params 认得出的键,数值型)。"""
    allowed = {p["key"] for p in extract_params(code)}
    lines = code.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^([A-Za-z_]\w*)\s*=\s*(-?\d+(?:\.\d+)?)\s*$", line)
        if m and m.group(1) in allowed and m.group(1) in params:
            val = params[m.group(1)]
            if isinstance(val, (int, float)) and val > 0:
                lines[i] = f"{m.group(1)} = {val}"
    return "\n".join(lines) + "\n"


def syntax_error(code: str) -> str | None:
    try:
        compile(code, "<gen>", "exec")
        return None
    except SyntaxError as e:
        return f"SyntaxError 第 {e.lineno} 行: {e.msg}\n  {e.text or ''}"


# ---------------------------------------------------------------- 落盘 + 生成
_cadgen_rt = None
_cadgen_lock = threading.Lock()


def _get_cadgen_runtime():
    """进程内加载 cadgen 运行时:OCP 内核只导入一次,后续 gen/snapshot 不再重复导入(提速关键)。"""
    global _cadgen_rt
    if _cadgen_rt is not None:
        return _cadgen_rt
    import importlib.util
    for p in (str(SKILLS), str(SKILLS / "packages"), str(SKILLS / "packages" / "cadgen" / "src")):
        if p not in sys.path:
            sys.path.insert(0, p)
    import cadgen  # 触发 OCP 导入(慢,仅此一次)
    gen_path = SKILLS / "gen" / "cli.py"
    spec = importlib.util.spec_from_file_location("_cadgen_gen_cli", gen_path)
    gen_cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen_cli)
    snap_path = SKILLS / "snapshot" / "__main__.py"
    spec2 = importlib.util.spec_from_file_location("_cadgen_snap_main", snap_path)
    snap_main = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(snap_main)
    exp_path = SKILLS / "export" / "cli.py"
    spec3 = importlib.util.spec_from_file_location("_cadgen_exp_cli", exp_path)
    exp_cli = importlib.util.module_from_spec(spec3)
    spec3.loader.exec_module(exp_cli)
    _cadgen_rt = (gen_cli.main, snap_main.main, exp_cli.main)
    return _cadgen_rt


def _run_inprocess(argv, func, cwd):
    import contextlib
    # os.chdir 与 redirect_stdout 是进程级状态,必须串行,否则并发任务会互相污染
    with _cadgen_lock:
        old_cwd = os.getcwd()
        os.chdir(cwd)
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = func(list(argv))
            code = code if isinstance(code, int) else 0
        finally:
            os.chdir(old_cwd)
        return code, out.getvalue(), err.getvalue()


def write_source(name: str, code: str) -> Path:
    outdir = WORKSPACE / "proto_out" / name
    outdir.mkdir(parents=True, exist_ok=True)
    src = outdir / f"{name}.step.py"
    src.write_text(code + "\n", encoding="utf-8")
    return src


def run_cadgen(name: str, src: Path) -> tuple[bool, str]:
    gen_main, _, _ = _get_cadgen_runtime()
    code, out, err = _run_inprocess([f"{name}.step.py", "--write"], gen_main, str(src.parent))
    if code != 0:
        return False, err + "\n" + out
    return True, ""


def run_export_stl(name: str, src: Path) -> tuple[bool, str]:
    """把 STEP 转成同名 .stl(3D 打印用)。失败不致命。"""
    _, _, exp_main = _get_cadgen_runtime()
    code, out, err = _run_inprocess([f"{name}.step.py", "--stl", "--json"], exp_main, str(src.parent))
    if code != 0:
        return False, (err + "\n" + out)[-400:]
    return True, ""


def build_and_snapshot(name: str, src: Path, heartbeat=None) -> dict:
    """生成(带自纠错)+ 校验 + 快照,返回产物字典。heartbeat 每轮回调一次(用于看门狗)。"""
    code = src.read_text(encoding="utf-8")
    errors = []
    ok = False
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if heartbeat:
            try:
                heartbeat()
            except Exception:  # noqa: BLE001
                pass
        syn = syntax_error(code)
        if syn:
            errors.append(f"第{attempt}轮 语法错误: {syn}")
            if attempt == MAX_ATTEMPTS:
                break
            code = fix_code(code, syn, history=errors[-4:])
            src.write_text(code + "\n", encoding="utf-8")
            continue

        print(f"[4/5] cadgen 生成 STEP(第 {attempt}/{MAX_ATTEMPTS} 轮)...")
        ok, err = run_cadgen(name, src)
        if ok:
            break
        errors.append(f"第{attempt}轮: {err.strip()[-300:]}")
        if attempt == MAX_ATTEMPTS:
            break
        code = fix_code(code, err, history=errors[-4:])
        src.write_text(code + "\n", encoding="utf-8")

    if not ok:
        detail = "\n".join(errors[-4:]) or "未知错误"
        die(f"重试 {MAX_ATTEMPTS} 轮后仍失败:\n{detail}")

    outdir = src.parent
    # 不再单独跑 inspect validate(gen 成功即几何有效),省一次 OCP 导入(~15s)
    validate_out = "生成成功"
    print("[5/5] 完成: STEP 已生成")
    _, snap_main, _ = _get_cadgen_runtime()
    _code, out, err = _run_inprocess(
        ["--input", f"{name}.step", "--output", f"{name}.png", "--json"],
        snap_main,
        str(outdir),
    )
    snapshot_out = (out or err).strip()
    print("     快照:", snapshot_out[:160])

    pngs = sorted(outdir.glob(f"{name}_*.png"))
    png = pngs[-1] if pngs else outdir / f"{name}.png"
    # STL 导出(3D 打印用户需要;失败不致命)
    stl = ""
    try:
        ok_stl, stl_err = run_export_stl(name, src)
        stl_path = outdir / f"{name}.stl"
        if ok_stl and stl_path.is_file():
            stl = str(stl_path)
        else:
            print("     STL 导出失败:", stl_err[:120])
    except Exception as e:  # noqa: BLE001
        print("     STL 导出异常:", str(e)[:120])
    code = src.read_text(encoding="utf-8")
    return {
        "name": name,
        "outdir": str(outdir),
        "step": str(outdir / f"{name}.step"),
        "stl": stl,
        "source": str(src),
        "png": str(png),
        "code": code,
        "labels": extract_labels(code),
        "validate": validate_out,
        "snapshot": snapshot_out,
    }


# ---------------------------------------------------------------- 编排
def run_pipeline(
    images: list[str],
    note: str = "",
    name: str = "",
    *,
    clarify=None,  # clarify(uncertainties: list[dict]) -> dict(field->answer)
    code_model: str | None = None,
    vision_model: str | None = None,
) -> dict:
    global CODE_MODEL, VISION_MODEL
    if code_model:
        CODE_MODEL = code_model
    if vision_model:
        VISION_MODEL = vision_model

    if not SKILLS.is_dir():
        die(f"找不到 skills 目录: {SKILLS}")
    for p in images:
        if not Path(p).is_file():
            die(f"图片不存在: {p}")
    if not images and not note.strip():
        die("既没有图片也没有文字描述,无法建模")

    name = name or "model_" + time.strftime("%Y%m%d_%H%M%S")
    name = re.sub(r"[^A-Za-z0-9_\-]", "_", name)

    # 阶段0: 感知(可选)
    desc = reasoning = ""
    if images:
        seen = vision_describe(images)
        desc = seen["description"]
        reasoning = seen["reasoning"]

    # 阶段0.5: 提示词加工(机械工程师视角)
    raw = f"【视觉描述】\n{desc or '(无图片,纯文字)'}\n\n【用户原始需求】\n{note or '(无)'}\n"
    if reasoning:
        raw += f"\n【视觉模型思考】\n{reasoning[:3000]}\n"
    refined = refine_prompt(raw)

    # 阶段1: 理解
    card = understand(refined, note)

    # 阶段2: 澄清
    answers: dict = {}
    critical = [u for u in card.get("uncertainties", []) if u.get("critical")]
    if critical and clarify:
        print(f"    [澄清] 有 {len(critical)} 个不确定点,询问用户 ...")
        answers = clarify(critical) or {}

    # 阶段3: 生成
    result = build_and_snapshot(name, write_source(name, generate_code(card, refined, answers)))
    result["card"] = card
    result["answers"] = answers
    result["refined"] = refined
    return result


# ---------------------------------------------------------------- CLI
def _cli_clarify(uncertainties: list[dict]) -> dict:
    answers = {}
    print("\n=== 有些细节需要确认(可直接回车跳过)===")
    for u in uncertainties:
        opts = u.get("options") or []
        print(f"\n· {u.get('question')}")
        for i, o in enumerate(opts, 1):
            print(f"  [{i}] {o}")
        ans = input("  选择(数字)或直接填/回车跳过: ").strip()
        if not ans:
            continue
        if ans.isdigit() and 1 <= int(ans) <= len(opts):
            answers[u["field"]] = opts[int(ans) - 1]
        else:
            answers[u["field"]] = ans
    return answers


def main() -> int:
    ap = argparse.ArgumentParser(description="图片 → Kimi 看图 → DeepSeek 理解 → 追问 → 写代码 → STEP")
    ap.add_argument("images", nargs="*", help="输入图片路径(1~3 张,可省略,纯文字用 --note)")
    ap.add_argument("--note", default="", help="补充说明(尺寸/要求)")
    ap.add_argument("--name", default="", help="模型名")
    ap.add_argument("--code-model", default=CODE_MODEL)
    ap.add_argument("--vision-model", default=VISION_MODEL)
    ap.add_argument("--no-clarify", action="store_true", help="跳过追问,直接按默认")
    args = ap.parse_args()

    clarify = None if args.no_clarify else _cli_clarify
    try:
        result = run_pipeline(
            args.images, args.note, args.name,
            clarify=clarify, code_model=args.code_model, vision_model=args.vision_model,
        )
    except PipelineError:
        return 1

    outdir = Path(result["outdir"])
    name = result["name"]
    print(f"\n完成! 产物目录: {outdir}")
    print(f"  STEP : {result['step']}")
    print(f"  源码 : {result['source']}")
    print(f"  快照 : {result['png']}")
    print(f"\n浏览器预览(先启动 cad-viewer):")
    print(f"  http://127.0.0.1:3245/{str(outdir).replace(chr(92), '/')}?file={name}.step.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
