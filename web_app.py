"""造物工坊 Web 后端(Flask):手机验证码登录 + 充值支付 + 文/图生三维模型。

启动:
  $env:MOONSHOT_API_KEY = [Environment]::GetEnvironmentVariable('MOONSHOT_API_KEY','User')
  $env:DEEPSEEK_API_KEY = [Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY','User')
  python web_app.py

浏览器打开 http://127.0.0.1:5000
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import uuid
import zipfile
import hashlib
from pathlib import Path

import requests
from flask import Flask, jsonify, request, send_file

import text2cad_proto as t2c
import billing
import users
import pay
import jobstore
import library
import library.parts  # noqa: F401 注册全部标准件
from build123d import exporters3d

BASE = Path(__file__).resolve().parent
WEB_DIR = BASE / "web"
UPLOAD_DIR = Path(os.environ.get("ZW_DATA_DIR", str(BASE))) / "web_uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 上传上限 25MB

JOBS: dict[str, dict] = {}
CARDS: dict[str, dict] = {}  # name -> 理解卡(供后续修改复用)
JOB_TTL = 2 * 3600           # 任务状态保留 2 小时
MAX_JOBS_PER_USER = 2        # 每人最多同时跑 2 个任务(保护 token 预算)


def _cleanup_jobs() -> None:
    now = time.time()
    for jid in [j for j, v in JOBS.items() if now - float(v.get("created_at") or v.get("_created") or 0) > JOB_TTL]:
        JOBS.pop(jid, None)
        jobstore.delete(jid)


def _running_jobs_of(user_id: str) -> int:
    return sum(1 for v in JOBS.values() if v.get("user_id") == user_id and v.get("status") in ("running", "awaiting_clarification"))


WATCHDOG_IDLE_SEC = 10 * 60  # 任务 10 分钟无进展视为超时(正常任务每步都喂狗,不受影响)
MAX_GLOBAL_JOBS = max(1, int(os.environ.get("MAX_GLOBAL_JOBS", "2")))  # 全站同时生成上限
_queue_pump_started = False


def _busy_jobs() -> int:
    return sum(1 for v in JOBS.values() if v.get("status") in ("running", "awaiting_clarification"))


def _queue_pump() -> None:
    """排队调度:有空位就把最早排队的任务拉起来跑。"""
    while True:
        time.sleep(5)
        try:
            queued = sorted(
                (j for j in JOBS.values() if j.get("status") == "queued"),
                key=lambda j: float(j.get("created_at") or 0),
            )
            for j in queued[: max(0, MAX_GLOBAL_JOBS - _busy_jobs())]:
                j["status"] = "running"
                j["stage"] = "排队结束,开始生成…"
                jobstore.save(j)
                threading.Thread(
                    target=_work,
                    args=(j["job_id"], j.get("image_paths") or [], j.get("note", ""), j.get("name", ""),
                          j.get("code_model"), j.get("vision_model"), j.get("user_id", "default"), j),
                    daemon=True,
                ).start()
        except Exception:  # noqa: BLE001
            pass


# ---------------- 每日备份 + 磁盘清理 ----------------
def _run_maintenance() -> None:
    data_dir = Path(os.environ.get("ZW_DATA_DIR", str(BASE)))
    now = time.time()
    # 1) 清理:30 天前的模型目录、7 天前的上传图片
    proto = data_dir / "proto_out"
    if proto.is_dir():
        for d in proto.iterdir():
            try:
                if d.is_dir() and now - d.stat().st_mtime > 30 * 86400:
                    shutil.rmtree(d, ignore_errors=True)
                    print(f"[维护] 清理旧模型 {d.name}")
            except OSError:
                pass
    uploads = data_dir / "web_uploads"
    if uploads.is_dir():
        for d in uploads.iterdir():
            try:
                if d.is_dir() and now - d.stat().st_mtime > 7 * 86400:
                    shutil.rmtree(d, ignore_errors=True)
            except OSError:
                pass
    # 2) 备份:每天一次,压缩账单/用户/邀请码/任务/反馈;保留最近 7 份
    backup_dir = data_dir / "backups"
    backup_dir.mkdir(exist_ok=True)
    marker = backup_dir / ".last_backup"
    today = time.strftime("%Y-%m-%d")
    try:
        if marker.is_file() and marker.read_text(encoding="utf-8").strip() == today:
            return
    except OSError:
        pass
    targets = ["billing_store.json", "users_store.json", "orders_store.json", "feedback_store.json"]
    jobs_dir = data_dir / "jobs"
    zpath = backup_dir / f"backup-{today}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for t in targets:
            p = data_dir / t
            if p.is_file():
                z.write(p, t)
        if jobs_dir.is_dir():
            for jf in jobs_dir.glob("*.json"):
                z.write(jf, "jobs/" + jf.name)
    backups = sorted(backup_dir.glob("backup-*.zip"), key=lambda p: p.name)
    for old in backups[:-7]:
        try:
            old.unlink()
        except OSError:
            pass
    marker.write_text(today, encoding="utf-8")
    print(f"[维护] 每日备份完成: {zpath.name}")


def _maintenance_loop() -> None:
    while True:
        time.sleep(3600)
        try:
            _run_maintenance()
        except Exception as e:  # noqa: BLE001
            print(f"[维护] 异常: {str(e)[:200]}")


def _watchdog() -> None:
    """后台守护:任务长时间无进展 -> 标记失败并结算已消耗 token,避免永远转圈。"""
    while True:
        time.sleep(60)
        try:
            now = time.time()
            for jid, job in list(JOBS.items()):
                if job.get("status") != "running":
                    continue
                if now - float(job.get("updated_at", job.get("created_at") or job.get("_created") or now)) < WATCHDOG_IDLE_SEC:
                    continue
                job["error"] = "任务超时中断(长时间无进展)。已结算已消耗的积分,请重新提交或联系客服。"
                job["status"] = "error"
                tokens = int(job.get("tokens") or 0)
                billed = int(job.get("billed_tokens") or 0)
                if tokens > billed:
                    points = billing.tokens_to_points(tokens - billed)
                    billing.consume(job.get("user_id", "default"), points, reason=f"超时中断已消耗 {tokens - billed} tokens")
                    billing.log_usage(job.get("user_id", "default"), tokens - billed, round(points, 2), "timeout")
                    job["billed_tokens"] = tokens
                # 记录看门狗已结算量,避免仍在运行的线程结束时重复扣费
                job["watchdog_billed_tokens"] = tokens
                jobstore.save(job)
        except Exception:  # noqa: BLE001
            pass


def _recover_jobs() -> None:
    """服务器重启后恢复未完成任务:先结算重启前已消耗的 token,再续跑。最多续跑 2 次,防止反复重启放大成本。"""
    for jid, j in jobstore.load_all().items():
        if j.get("status") not in ("running", "awaiting_clarification", "queued"):
            continue
        resumes = int(j.get("resumes") or 0) + 1
        j["resumes"] = resumes
        tokens = int(j.get("tokens") or 0)
        billed = int(j.get("billed_tokens") or 0)
        if tokens > billed:
            points = billing.tokens_to_points(tokens - billed)
            billing.consume(j.get("user_id", "default"), points, reason=f"重启恢复结算 {tokens - billed} tokens")
            billing.log_usage(j.get("user_id", "default"), tokens - billed, round(points, 2), "resume")
            j["billed_tokens"] = tokens
        if resumes > 2:
            j["status"] = "error"
            j["error"] = "任务多次因服务器中断未能完成,请重新提交。已结算已消耗的积分。"
            jobstore.save(j)
            continue
        if j.get("status") == "queued":
            # 排队任务保持排队,由 _queue_pump 调度
            JOBS[jid] = j
            jobstore.save(j)
            continue
        j["status"] = "running"
        j["questions"] = None
        j["_event"] = None
        JOBS[jid] = j
        jobstore.save(j)
        print(f"[恢复] 续跑任务 {jid} (用户 {j.get('user_id')}, 第 {resumes} 次)")
        threading.Thread(
            target=_work,
            args=(jid, j.get("image_paths") or [], j.get("note", ""), j.get("name", ""),
                  j.get("code_model"), j.get("vision_model"), j.get("user_id", "default"), j),
            daemon=True,
        ).start()

# 上线时设 REQUIRE_AUTH=1:生成/修改/充值都必须先登录
REQUIRE_AUTH = os.environ.get("REQUIRE_AUTH", "0") == "1"
# 充值开关:内测期间 PAY_ENABLED=0,充值接口全部关闭
PAY_ENABLED = os.environ.get("PAY_ENABLED", "0") == "1"
# 3D 预览器对外地址(本地默认 3245 端口;上线时改为 https://域名)
VIEWER_BASE = os.environ.get("VIEWER_BASE", "http://127.0.0.1:3245")


def current_user_id() -> str | None:
    """从 Authorization: Bearer <token> 取当前用户;未开启强制登录时回落 default。"""
    token = (request.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
    uid = users.token_to_user(token) if token else None
    if uid:
        return uid
    return None if REQUIRE_AUTH else "default"


def need_login():
    return jsonify({"error": "请先使用邀请码登录"}), 401


def viewer_url(outdir: str, name: str) -> str:
    p = str(outdir).replace(chr(92), "/")
    if p.startswith("/viewer/"):  # 容器内数据目录在预览器根里,URL 前缀由 nginx 的 /viewer 提供
        p = p[len("/viewer"):]
    return f"{VIEWER_BASE}{p}?file={name}.step.py"


def _make_name(name: str) -> str:
    name = name or ""
    cleaned = re.sub(r"[^A-Za-z0-9_\-]", "_", name).strip("_")
    if not cleaned:  # 纯中文等无法作为文件名时,自动命名
        cleaned = "model_" + time.strftime("%Y%m%d_%H%M%S")
    return cleaned


def _finalize_result(result: dict, card: dict | None, answers: dict | None) -> dict:
    outdir = result["outdir"]
    nm = result["name"]
    png_name = Path(result["png"]).name
    result["viewer_url"] = viewer_url(outdir, nm)
    result["step_url"] = f"/api/files/{nm}/{nm}.step"
    result["png_url"] = f"/api/files/{nm}/{png_name}"
    result["source_url"] = f"/api/files/{nm}/{nm}.step.py"
    if result.get("stl"):
        result["stl_url"] = f"/api/files/{nm}/{Path(result['stl']).name}"
    else:
        result["stl_url"] = ""
    result["card"] = card
    result["answers"] = answers or {}
    result["params"] = t2c.extract_params(result.get("code", ""))
    return result


def _error_kind(error: str) -> str:
    e = str(error or "")
    if "fillet" in e or "chamfer" in e:
        return "geometry"
    if "没输出结果" in e or "没有输出" in e:
        return "model"
    if "超时" in e:
        return "timeout"
    return "other"


def _checkpoint(job: dict) -> None:
    """阶段边界落盘 + 心跳(供看门狗与断点续跑)。"""
    job["tokens"] = t2c.get_token_usage()
    jobstore.save(job)


def _work(job_id: str, image_paths: list[str], note: str, name: str, code_model: str | None, vision_model: str | None, user_id: str, cp: dict | None = None):
    job = JOBS[job_id]
    cp = cp or {}
    t2c.reset_token_usage()
    # 精细模式:写代码 + 整理规格 + 理解三步都用所选模型(pro);纠错始终用 flash(快)
    t2c.set_model_overrides(code=code_model, vision=vision_model, aux=code_model)
    # 大模型调用期间每 30 秒喂一次看门狗(证明任务还活着,防止长思考被误判超时)
    t2c.set_heartbeat(lambda: _checkpoint(job))
    try:
        name = _make_name(name)
        job["name"] = name

        # 阶段0: 感知(可选;失败降级为纯文字,不中断任务)
        job["stage"] = "正在看图识别…"
        desc = reasoning = ""
        if image_paths:
            try:
                seen = t2c.vision_describe(image_paths)
                desc = seen["description"]
                reasoning = seen["reasoning"]
            except Exception as e:  # noqa: BLE001
                print(f"[降级] 视觉识别失败,改用纯文字描述: {str(e)[:120]}")
                desc = reasoning = ""
                cp["vision_failed"] = True
                _checkpoint(job)

        # 阶段0.5: 提示词加工(机械工程师视角)
        job["stage"] = "正在把需求整理成工程规格…"
        raw = f"【视觉描述】\n{desc or '(无图片,纯文字)'}\n\n【用户原始需求】\n{note or '(无)'}\n"
        if reasoning:
            raw += f"\n【视觉模型思考】\n{reasoning[:3000]}\n"
        if cp.get("refined"):
            refined = cp["refined"]
        else:
            refined = t2c.refine_prompt(raw)
            job["refined"] = refined
            cp["refined"] = refined
            _checkpoint(job)

        # 阶段0.6: 外观造型调研(DeepSeek 内置知识,极重要:决定"像不像")
        job["stage"] = "正在调研外观造型…"
        if cp.get("appearance"):
            appearance = cp["appearance"]
        else:
            appearance = t2c.research_appearance(f"【用户原始需求】\n{note or '(无)'}\n\n【工程化需求】\n{refined}")
            cp["appearance"] = appearance
            job["refined"] = refined
            _checkpoint(job)

        # 阶段1: 理解
        job["stage"] = "正在理解这是什么…"
        if cp.get("card"):
            card = cp["card"]
        else:
            card = t2c.understand(refined, note, appearance=appearance)
            job["card"] = card
            cp["card"] = card
            _checkpoint(job)

        # 阶段2:澄清(需要则暂停等用户回答;升级版:提问 5~12 个,全部带默认值)
        answers: dict = cp.get("answers") or {}
        questions = (card.get("uncertainties") or [])[:12]
        if questions and not cp.get("clarified"):
            job["status"] = "awaiting_clarification"
            job["questions"] = questions
            _checkpoint(job)
            event = threading.Event()
            job["_event"] = event
            event.wait(timeout=900)  # 最多等 15 分钟
            answers = job.get("answers") or {}
            job["status"] = "running"
            cp["clarified"] = True
            cp["answers"] = answers
            _checkpoint(job)

        # 阶段3~5:写代码(自纠错)+ 生成 + 校验 + 快照
        job["stage"] = "正在生成三维模型(可能自动修正几次)…"
        if cp.get("code_done") and (t2c.WORKSPACE / "proto_out" / name / f"{name}.step.py").is_file():
            src = t2c.WORKSPACE / "proto_out" / name / f"{name}.step.py"
        else:
            code = t2c.generate_code(card, refined, answers, appearance=appearance)
            src = t2c.write_source(name, code)
            cp["code_done"] = True
            _checkpoint(job)
        result = t2c.build_and_snapshot(name, src, heartbeat=lambda: _checkpoint(job))

        result = _finalize_result(result, card, answers)
        result["refined"] = refined
        result["appearance"] = appearance
        CARDS[name] = card
        job["result"] = result
        job["status"] = "done"
        _checkpoint(job)
    except Exception as e:  # noqa: BLE001
        job["error"] = str(e)[:800]
        job["error_kind"] = _error_kind(job["error"])
        job["status"] = "error"
        _checkpoint(job)
    # 按实际 token 消耗扣费(无论成败,token 都已真实消耗;允许欠费)
    tokens = t2c.get_token_usage()
    watchdog_paid = int(job.get("watchdog_billed_tokens") or 0)
    net_tokens = max(0, tokens - watchdog_paid)  # 看门狗已结算过的部分不重复扣
    points = billing.tokens_to_points(net_tokens)
    deducted, bal = billing.consume(user_id, points, reason=f"生成消耗 {net_tokens} tokens")
    if net_tokens > 0:
        billing.log_usage(user_id, net_tokens, round(deducted, 2), "generate")
    if job.get("result") is not None:
        job["result"]["tokens"] = tokens
        job["result"]["points_used"] = round(deducted, 2)
        job["result"]["balance"] = round(bal, 2)
    job["billed_tokens"] = int(job.get("billed_tokens") or 0) + net_tokens
    _checkpoint(job)


@app.get("/")
def index():
    resp = send_file(WEB_DIR / "index.html")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


@app.get("/cases/<path:fn>")
def case_image(fn):
    p = (WEB_DIR / "cases" / fn).resolve()
    if not str(p).startswith(str((WEB_DIR / "cases").resolve())) or not p.is_file():
        return jsonify({"error": "not found"}), 404
    return send_file(p)


@app.get("/demos/<path:fn>")
def demo_video(fn):
    p = (WEB_DIR / "demos" / fn).resolve()
    if not str(p).startswith(str((WEB_DIR / "demos").resolve())) or not p.is_file():
        return jsonify({"error": "not found"}), 404
    return send_file(p, mimetype="video/mp4")


@app.get("/fonts/<path:fn>")
def font_file(fn):
    p = (WEB_DIR / "fonts" / fn).resolve()
    if not str(p).startswith(str((WEB_DIR / "fonts").resolve())) or not p.is_file():
        return jsonify({"error": "not found"}), 404
    resp = send_file(p, mimetype="font/woff2")
    resp.headers["Cache-Control"] = "public, max-age=2592000"
    return resp


# ---------- 标准件库(零积分、免登录) ----------

LIB_OUT = Path(os.environ.get("ZW_DATA_DIR", str(BASE))) / "proto_out" / "library"
LIB_OUT.mkdir(parents=True, exist_ok=True)


@app.get("/api/library/catalog")
def library_catalog():
    cats = library.catalog()
    oscad = []
    oscad_json = BASE / "library" / "oscad_catalog.json"
    if oscad_json.is_file():
        try:
            oscad = json.loads(oscad_json.read_text(encoding="utf-8"))
        except Exception:
            oscad = []
    return jsonify({"catalog": cats, "oscad": oscad})


@app.post("/api/library/build")
def library_build():
    """原生 build123d 标准件:参数 -> STEP/STL,缓存复用,零积分、免登录。"""
    data = request.get_json(silent=True) or {}
    part_id = str(data.get("part_id", ""))
    spec = library.PART_REGISTRY.get(part_id)
    if not spec:
        return jsonify({"error": "未知零件"}), 404

    kwargs = {}
    for p in spec.params:
        v = data.get("params", {}).get(p.key, p.default)
        if p.kind == "options":
            if v not in (p.options or []):
                v = p.default
        else:
            try:
                v = float(v)
                if p.min is not None:
                    v = max(p.min, v)
                if p.max is not None:
                    v = min(p.max, v)
            except (TypeError, ValueError):
                v = p.default
        kwargs[p.key] = v

    key = hashlib.md5(json.dumps(kwargs, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:10]
    base = f"{part_id}_{key}"
    outdir = LIB_OUT / part_id / key
    outdir.mkdir(parents=True, exist_ok=True)
    step_path = outdir / f"{base}.step"
    stl_path = outdir / f"{base}.stl"
    src_path = outdir / f"{base}.step.py"

    if not step_path.is_file():
        try:
            with t2c._cadgen_lock:  # build123d 非线程安全,与生成管线共用锁
                part = spec.build(**kwargs)
                exporters3d.export_step(part, str(step_path))
                exporters3d.export_stl(part, str(stl_path))
        except Exception as e:
            return jsonify({"error": f"生成失败:{e}"}), 500

    # 预览器后端会执行该源码:自带路径引导,保证任何子进程都能 import library
    args = ", ".join(f"{k}={v!r}" for k, v in kwargs.items())
    src_text = (
        "import sys\n"
        "sys.path.insert(0, '/app')\n"
        f"from build123d import *\n"
        f"from library.parts import {spec.build.__name__}\n\n"
        f"def gen_step():\n    return {spec.build.__name__}({args})\n"
    )
    if not src_path.is_file() or src_path.read_text(encoding="utf-8") != src_text:
        src_path.write_text(src_text, encoding="utf-8")

    return jsonify({
        "ok": True, "name": spec.name, "params": kwargs, "standard": spec.standard,
        "viewer_url": viewer_url(str(outdir), base),
        "step_url": f"/api/libfiles/{part_id}/{key}/{base}.step",
        "stl_url": f"/api/libfiles/{part_id}/{key}/{base}.stl",
    })


@app.get("/api/libfiles/<part_id>/<key>/<filename>")
def libfiles(part_id, key, filename):
    p = (LIB_OUT / part_id / key / filename).resolve()
    root = LIB_OUT.resolve()
    if not str(p).startswith(str(root)) or not p.is_file():
        return jsonify({"error": "not found"}), 404
    return send_file(p)


# ---------- OpenSCAD 打印件库(开源库渲染 STL,零积分、免登录) ----------

OSCAD_ROOT = BASE / "library" / "oscad"
OSCAD_WRAP = Path(os.environ.get("ZW_DATA_DIR", str(BASE))) / "library_oscad" / "wrappers"
OSCAD_OUT = Path(os.environ.get("ZW_DATA_DIR", str(BASE))) / "proto_out" / "library_oscad"


@app.post("/api/library/oscad")
def library_oscad():
    data = request.get_json(silent=True) or {}
    entry_id = str(data.get("id", ""))
    try:
        entries = json.loads((BASE / "library" / "oscad_catalog.json").read_text(encoding="utf-8"))
    except Exception:
        entries = []
    entry = next((e for e in entries if e.get("id") == entry_id), None)
    if not entry:
        return jsonify({"error": "未知打印件"}), 404

    kwargs = {}
    for p in entry.get("params", []):
        v = data.get("params", {}).get(p.get("key"), p.get("default"))
        try:
            v = float(v)
            v = max(float(p.get("min", v)), min(float(p.get("max", v)), v))
        except (TypeError, ValueError):
            v = float(p.get("default", 0))
        kwargs[p["key"]] = v

    key = hashlib.md5(json.dumps(kwargs, sort_keys=True).encode()).hexdigest()[:10]
    base = f"{entry_id}_{key}"
    outdir = OSCAD_OUT / entry_id / key
    outdir.mkdir(parents=True, exist_ok=True)
    stl = outdir / f"{base}.stl"

    if not stl.is_file():
        import subprocess as sp
        OSCAD_WRAP.mkdir(parents=True, exist_ok=True)
        wrap = OSCAD_WRAP / f"{base}.scad"
        text = entry.get("template", "")
        for k, v in kwargs.items():
            text = text.replace("{" + k.upper() + "}", f"{v:g}")
        wrap.write_text(text, encoding="utf-8")
        env = dict(os.environ)
        env["OPENSCADPATH"] = str(OSCAD_ROOT)
        try:
            r = sp.run(["openscad", "-o", str(stl), str(wrap)],
                       capture_output=True, text=True, timeout=240, env=env)
        except sp.TimeoutExpired:
            return jsonify({"error": "OpenSCAD 渲染超时"}), 500
        if r.returncode != 0:
            return jsonify({"error": "渲染失败: " + ((r.stderr or r.stdout)[-400:])}), 500
        if not stl.is_file():
            return jsonify({"error": "渲染未产出 STL"}), 500

    return jsonify({
        "ok": True, "name": entry.get("name"), "oscad": True,
        "viewer_url": viewer_url(str(outdir), base).replace(".step.py", ".stl"),
        "stl_url": f"/api/oscadfiles/{entry_id}/{key}/{base}.stl",
    })


@app.get("/api/oscadfiles/<entry_id>/<key>/<filename>")
def oscadfiles(entry_id, key, filename):
    p = (OSCAD_OUT / entry_id / key / filename).resolve()
    if not str(p).startswith(str(OSCAD_OUT.resolve())) or not p.is_file():
        return jsonify({"error": "not found"}), 404
    return send_file(p)


# ---------- step.parts 外部零件检索(12,000+ 开源 STEP) ----------

STEPPARTS_OUT = Path(os.environ.get("ZW_DATA_DIR", str(BASE))) / "proto_out" / "stepparts"


@app.get("/api/library/stepparts")
def stepparts_search():
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify({"error": "请输入至少 2 个字符"}), 400
    params = {"q": q, "limit": 10}
    for facet in ("category", "family", "standard", "tag"):
        v = (request.args.get(facet) or "").strip()
        if v:
            params[facet] = v
    try:
        r = requests.get("https://api.step.parts/v1/parts", params=params, timeout=25)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return jsonify({"error": f"step.parts 检索失败: {e}"}), 502
    out = []
    for it in (data.get("items") or []):
        attrs = {k: v for k, v in (it.get("attributes") or {}).items() if v not in (None, "")}
        std = it.get("standard")
        out.append({
            "id": it.get("id"),
            "name": it.get("name"),
            "standard": (std or {}).get("designation") if isinstance(std, dict) else std,
            "attrs": dict(list(attrs.items())[:8]),
            "page_url": f"https://www.step.parts/parts/{it.get('id')}",
            "step_url": it.get("stepUrl"),
            "sha256": it.get("sha256"),
        })
    return jsonify({"total": data.get("total"), "items": out})


@app.post("/api/library/stepparts/download")
def stepparts_download():
    data = request.get_json(silent=True) or {}
    pid = re.sub(r"[^A-Za-z0-9_\-]", "_", str(data.get("id", "")))[:80]
    url = str(data.get("step_url", ""))
    if not pid or not url.startswith("https://"):
        return jsonify({"error": "无效的下载参数"}), 400
    outdir = STEPPARTS_OUT / pid
    outdir.mkdir(parents=True, exist_ok=True)
    step_path = outdir / f"{pid}.step"
    if not step_path.is_file():
        try:
            with requests.get(url, stream=True, timeout=120) as r:
                r.raise_for_status()
                total = int(r.headers.get("Content-Length") or 0)
                if total > 30 * 1024 * 1024:
                    return jsonify({"error": "文件超过 30MB 上限"}), 413
                size = 0
                with open(step_path, "wb") as f:
                    for chunk in r.iter_content(65536):
                        f.write(chunk)
                        size += len(chunk)
                        if size > 30 * 1024 * 1024:
                            step_path.unlink(missing_ok=True)
                            return jsonify({"error": "文件超过 30MB 上限"}), 413
        except Exception as e:
            return jsonify({"error": f"下载失败: {e}"}), 502
    return jsonify({
        "ok": True,
        "viewer_url": viewer_url(str(outdir), pid).replace(".step.py", ".step"),
        "step_url": f"/api/steppartsfiles/{pid}/{pid}.step",
    })


@app.get("/api/steppartsfiles/<pid>/<filename>")
def steppartsfiles(pid, filename):
    p = (STEPPARTS_OUT / pid / filename).resolve()
    if not str(p).startswith(str(STEPPARTS_OUT.resolve())) or not p.is_file():
        return jsonify({"error": "not found"}), 404
    return send_file(p)


@app.post("/api/generate")
def generate():
    files = request.files.getlist("images")
    note = request.form.get("note", "")
    name = request.form.get("name", "")
    code_model = request.form.get("code_model", "") or None
    vision_model = request.form.get("vision_model", "") or None

    user_id = current_user_id()
    if user_id is None:
        return need_login()
    valid = [f for f in files if f and f.filename]
    if not valid and not note.strip():
        return jsonify({"error": "请上传图片,或填写文字描述"}), 400

    _cleanup_jobs()
    if _running_jobs_of(user_id) >= MAX_JOBS_PER_USER:
        return jsonify({"error": f"你已有 {MAX_JOBS_PER_USER} 个任务在跑,请等它们完成后再提交"}), 429

    # 计费:生成前只检查最低余额,实际按 token 消耗在生成后扣(允许欠费)
    if billing.balance(user_id) < billing.MIN_GENERATE_POINTS:
        debt = billing.debt(user_id)
        tip = f"(当前欠款 {debt} 积分)" if debt > 0 else ""
        return jsonify({"error": f"积分不足(最低需 {billing.MIN_GENERATE_POINTS} 积分){tip},请先充值"}), 402

    job_id = uuid.uuid4().hex[:12]
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    image_paths = []
    for f in valid:
        dest = job_dir / Path(f.filename).name
        f.save(dest)
        image_paths.append(str(dest))

    JOBS[job_id] = {"job_id": job_id, "status": "running", "result": None, "error": None, "questions": None,
                    "answers": None, "card": None, "user_id": user_id, "name": name,
                    "note": note, "image_paths": image_paths, "code_model": code_model,
                    "vision_model": vision_model, "tokens": 0, "billed_tokens": 0, "created_at": time.time()}
    jobstore.save(JOBS[job_id])

    # 全站并发控制:忙则排队(排队任务不占线程,由 _queue_pump 调度)
    if _busy_jobs() >= MAX_GLOBAL_JOBS:
        JOBS[job_id]["status"] = "queued"
        JOBS[job_id]["stage"] = "排队中,请稍候(前面还有任务在生成)…"
        jobstore.save(JOBS[job_id])
        return jsonify({"job_id": job_id, "balance": billing.balance(user_id), "queued": True})
    threading.Thread(target=_work, args=(job_id, image_paths, note, name, code_model, vision_model, user_id, JOBS[job_id]), daemon=True).start()
    return jsonify({"job_id": job_id, "balance": billing.balance(user_id)})


@app.post("/api/answer")
def answer():
    data = request.get_json(silent=True) or {}
    job_id = data.get("job_id", "")
    answers = data.get("answers", [])  # [{field, answer}]
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "job not found"}), 404
    mapping = {a.get("field"): a.get("answer") for a in answers if isinstance(a, dict)}
    job["answers"] = mapping
    ev = job.get("_event")
    if ev:
        ev.set()
    return jsonify({"ok": True})


@app.get("/api/status/<job_id>")
def status(job_id):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "job not found"}), 404
    return jsonify({
        "status": job.get("status"),
        "error": job.get("error"),
        "error_kind": job.get("error_kind", ""),
        "questions": job.get("questions"),
        "card": job.get("card"),
        "result": job.get("result"),
        "stage": job.get("stage", ""),
    })


def _modify_work(job_id: str, name: str, src: Path, tags: list[str], ref: str, user_id: str):
    job = JOBS[job_id]
    t2c.reset_token_usage()
    t2c.set_model_overrides()
    t2c.set_heartbeat(lambda: _checkpoint(job))
    try:
        job["stage"] = "正在修改模型…"
        code = src.read_text(encoding="utf-8")
        new_code = t2c.modify_code(code, tags, ref)
        src.write_text(new_code + "\n", encoding="utf-8")
        result = t2c.build_and_snapshot(name, src, heartbeat=lambda: jobstore.save(job))
        result = _finalize_result(result, CARDS.get(name), job.get("answers") or {})
        job["result"] = result
        job["status"] = "done"
        jobstore.save(job)
    except Exception as e:  # noqa: BLE001
        job["error"] = str(e)[:800]
        job["status"] = "error"
        jobstore.save(job)
    # 修改同样按实际 token 消耗扣费
    tokens = t2c.get_token_usage()
    points = billing.tokens_to_points(tokens)
    deducted, bal = billing.consume(user_id, points, reason=f"修改消耗 {tokens} tokens")
    billing.log_usage(user_id, tokens, round(deducted, 2), "modify")
    if job.get("result") is not None:
        job["result"]["tokens"] = tokens
        job["result"]["points_used"] = round(deducted, 2)
        job["result"]["balance"] = round(bal, 2)


@app.post("/api/modify")
def modify():
    user_id = current_user_id()
    if user_id is None:
        return need_login()
    data = request.get_json(silent=True) or {}
    name = data.get("name", "")
    tags = data.get("tags", [])
    ref = data.get("ref", "") or ""
    if not name or not tags:
        return jsonify({"error": "缺少 name 或 tags"}), 400
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", name):
        return jsonify({"error": "非法模型名"}), 400
    src = t2c.WORKSPACE / "proto_out" / name / f"{name}.step.py"
    if not src.is_file():
        return jsonify({"error": "源文件不存在,无法修改"}), 404

    _cleanup_jobs()
    if _running_jobs_of(user_id) >= MAX_JOBS_PER_USER:
        return jsonify({"error": f"你已有 {MAX_JOBS_PER_USER} 个任务在跑,请等它们完成后再提交"}), 429
    if billing.balance(user_id) < billing.MIN_GENERATE_POINTS:
        debt = billing.debt(user_id)
        tip = f"(当前欠款 {debt} 积分)" if debt > 0 else ""
        return jsonify({"error": f"积分不足(最低需 {billing.MIN_GENERATE_POINTS} 积分){tip},请先充值"}), 402

    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"job_id": job_id, "status": "running", "result": None, "error": None, "questions": None,
                    "card": CARDS.get(name), "user_id": user_id, "name": name,
                    "note": "", "image_paths": [], "tokens": 0, "billed_tokens": 0, "created_at": time.time()}
    jobstore.save(JOBS[job_id])
    threading.Thread(target=_modify_work, args=(job_id, name, src, [str(t) for t in tags], ref, user_id), daemon=True).start()
    return jsonify({"job_id": job_id})


# ---------------- 参数微调(滑杆二次调整,不走 LLM,几乎零成本) ----------------
def _reparam_work(job_id: str, name: str, src: Path, params: dict, user_id: str):
    job = JOBS[job_id]
    t2c.reset_token_usage()
    t2c.set_model_overrides()
    t2c.set_heartbeat(lambda: _checkpoint(job))
    try:
        job["stage"] = "正在按新参数重新生成…"
        code = src.read_text(encoding="utf-8")
        new_code = t2c.substitute_params(code, params)
        src.write_text(new_code, encoding="utf-8")
        result = t2c.build_and_snapshot(name, src, heartbeat=lambda: _checkpoint(job))
        result = _finalize_result(result, CARDS.get(name), job.get("answers") or {})
        job["result"] = result
        job["status"] = "done"
        _checkpoint(job)
    except Exception as e:  # noqa: BLE001
        job["error"] = str(e)[:800]
        job["error_kind"] = _error_kind(job["error"])
        job["status"] = "error"
        _checkpoint(job)
    tokens = t2c.get_token_usage()
    points = billing.tokens_to_points(tokens)
    deducted, bal = billing.consume(user_id, points, reason=f"参数调整消耗 {tokens} tokens")
    if tokens > 0:
        billing.log_usage(user_id, tokens, round(deducted, 2), "reparam")
    if job.get("result") is not None:
        job["result"]["tokens"] = tokens
        job["result"]["points_used"] = round(deducted, 2)
        job["result"]["balance"] = round(bal, 2)
    job["billed_tokens"] = int(job.get("billed_tokens") or 0) + tokens
    _checkpoint(job)


@app.post("/api/reparam")
def reparam():
    user_id = current_user_id()
    if user_id is None:
        return need_login()
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", ""))
    params = data.get("params") or {}
    if not name or not isinstance(params, dict) or not params:
        return jsonify({"error": "缺少 name 或 params"}), 400
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", name):
        return jsonify({"error": "非法模型名"}), 400
    src = t2c.WORKSPACE / "proto_out" / name / f"{name}.step.py"
    if not src.is_file():
        return jsonify({"error": "源文件不存在"}), 404
    # 只允许数值且为正
    clean = {}
    for k, v in params.items():
        if isinstance(v, bool):
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if fv <= 0 or fv > 100000:
            continue
        clean[str(k)] = fv
    if not clean:
        return jsonify({"error": "参数无效"}), 400

    _cleanup_jobs()
    if _running_jobs_of(user_id) >= MAX_JOBS_PER_USER:
        return jsonify({"error": "你已有任务在跑,请稍候"}), 429

    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"job_id": job_id, "status": "running", "result": None, "error": None, "questions": None,
                    "card": CARDS.get(name), "user_id": user_id, "name": name,
                    "note": "", "image_paths": [], "tokens": 0, "billed_tokens": 0, "created_at": time.time()}
    jobstore.save(JOBS[job_id])
    threading.Thread(target=_reparam_work, args=(job_id, name, src, clean, user_id), daemon=True).start()
    return jsonify({"job_id": job_id})


@app.get("/api/files/<name>/<filename>")
def get_file(name, filename):
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", name):
        return jsonify({"error": "not found"}), 404
    outdir = (t2c.WORKSPACE / "proto_out" / name).resolve()
    safe = (outdir / filename).resolve()
    if not str(safe).startswith(str(outdir)) or not safe.is_file():
        return jsonify({"error": "not found"}), 404
    as_attachment = filename.endswith(".step") or filename.endswith(".step.py")
    return send_file(safe, as_attachment=as_attachment)


@app.get("/api/credits")
def credits():
    user_id = current_user_id() or "default"
    phone = user_id if user_id != "default" else None
    return jsonify({
        "balance": billing.balance(user_id),
        "debt": billing.debt(user_id),
        "history": billing.history(user_id, 20),
        "pricing": billing.pricing(),
        "user": {"phone": phone},
        "require_auth": REQUIRE_AUTH,
        "pay_gateway": pay.PAY_GATEWAY,
        "pay_enabled": PAY_ENABLED,
    })


# ---------------- 登录:内测邀请码 ----------------
@app.post("/api/auth/invite")
def auth_invite():
    data = request.get_json(silent=True) or {}
    code = data.get("code", "")
    inv = users.redeem_invite(code)
    if not inv:
        return jsonify({"error": "邀请码无效或已被使用"}), 400
    user_id = inv["user_id"]
    billing.recharge(user_id, inv["quota"], amount=None, channel="invite")
    token = users.issue_token(user_id)
    return jsonify({"ok": True, "token": token, "code": inv["code"],
                    "quota": inv["quota"], "balance": billing.balance(user_id),
                    "debt": billing.debt(user_id)})


# ---------------- 登录 / 注册(手机号,备用) ----------------
@app.post("/api/sms/send")
def sms_send():
    data = request.get_json(silent=True) or {}
    phone = data.get("phone", "")
    if users.valid_phone(phone) is False:
        return jsonify({"ok": False, "error": "手机号格式不对(11 位大陆手机号)"}), 400
    res = users.send_code(phone)
    if not res.get("ok"):
        return jsonify({"ok": False, "error": res.get("error")}), 429
    return jsonify({"ok": True, "code": res.get("code")})  # code 仅 mock 模式返回


@app.post("/api/auth/login")
def auth_login():
    data = request.get_json(silent=True) or {}
    phone = data.get("phone", "")
    code = data.get("code", "")
    if not users.valid_phone(phone) or not users.verify_code(phone, code):
        return jsonify({"error": "验证码错误或已过期"}), 400
    users.ensure_user(phone)
    token = users.issue_token(phone)
    return jsonify({"ok": True, "token": token, "phone": phone,
                    "balance": billing.balance(phone), "debt": billing.debt(phone)})


@app.post("/api/auth/logout")
def auth_logout():
    token = (request.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
    users.logout(token)
    return jsonify({"ok": True})


@app.get("/api/me")
def me():
    user_id = current_user_id()
    if user_id is None:
        return jsonify({"user": None})
    return jsonify({"user": {"phone": user_id}, "balance": billing.balance(user_id),
                    "debt": billing.debt(user_id)})


@app.get("/api/mymodels")
def my_models():
    """当前用户的生成历史(从任务记录聚合)。"""
    user_id = current_user_id()
    if user_id is None:
        return need_login()
    merged = {**jobstore.load_all(), **JOBS}
    rows: dict[str, dict] = {}
    for j in merged.values():
        if j.get("user_id") != user_id or j.get("status") != "done" or not j.get("result"):
            continue
        name = str(j.get("name") or "").strip()
        if not name or name in rows:
            continue
        res = j["result"]
        rows[name] = {
            "name": name,
            "at": j.get("updated_at"),
            "tokens": res.get("tokens"),
            "points": res.get("points_used"),
            "viewer_url": res.get("viewer_url", ""),
            "step_url": res.get("step_url", ""),
            "stl_url": res.get("stl_url", ""),
            "png_url": res.get("png_url", ""),
        }
    models = sorted(rows.values(), key=lambda x: float(x.get("at") or 0), reverse=True)[:50]
    return jsonify({"models": models})


# ---------------- 反馈 ----------------
def _feedback_path() -> Path:
    return Path(os.environ.get("ZW_DATA_DIR", str(BASE))) / "feedback_store.json"


@app.post("/api/feedback")
def feedback():
    data = request.get_json(silent=True) or {}
    text = str(data.get("text", "")).strip()[:2000]
    if not text:
        return jsonify({"error": "反馈内容不能为空"}), 400
    user_id = current_user_id() or "anonymous"
    p = _feedback_path()
    items = []
    if p.is_file():
        try:
            items = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            items = []
    items.append({"user_id": user_id, "text": text, "at": time.strftime("%Y-%m-%d %H:%M:%S")})
    p.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    return jsonify({"ok": True})


@app.get("/api/admin/feedback")
def admin_feedback():
    if not _admin_ok():
        return jsonify({"error": "无权限"}), 401
    p = _feedback_path()
    items = []
    if p.is_file():
        try:
            items = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            items = []
    return jsonify({"feedback": list(reversed(items))[:100]})


@app.post("/api/admin/grant")
def admin_grant():
    """后台给指定用户补积分。"""
    if not _admin_ok():
        return jsonify({"error": "无权限"}), 401
    data = request.get_json(silent=True) or {}
    user_id = str(data.get("user_id", "")).strip()
    try:
        points = float(data.get("points", 0))
    except (TypeError, ValueError):
        points = 0
    if not user_id or points <= 0:
        return jsonify({"error": "请填写用户和正数积分"}), 400
    bal = billing.recharge(user_id, points, amount=None, channel="grant")
    return jsonify({"ok": True, "balance": bal})


# ---------------- 充值(支付) ----------------
def _pay_closed():
    return jsonify({"error": "内测期间暂未开放充值,额度由邀请码提供"}), 403


@app.post("/api/recharge/create")
def recharge_create():
    if not PAY_ENABLED:
        return _pay_closed()
    user_id = current_user_id()
    if user_id is None:
        return need_login()
    data = request.get_json(silent=True) or {}
    try:
        amount = float(data.get("amount", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "金额格式错误"}), 400
    pay.expire_orders()
    res = pay.create_order(user_id, amount)
    if not res.get("ok"):
        return jsonify({"error": res.get("error")}), 400
    if res.get("qr") and res.get("gateway") != "mock":
        import base64
        res["qr_img"] = "data:image/png;base64," + base64.b64encode(pay.qr_png(res["qr"])).decode()
    return jsonify(res)


@app.post("/api/recharge/confirm")
def recharge_confirm():
    """mock 网关的"模拟支付成功"(仅 PAY_GATEWAY=mock 时有效)。"""
    if not PAY_ENABLED:
        return _pay_closed()
    user_id = current_user_id()
    if user_id is None:
        return need_login()
    data = request.get_json(silent=True) or {}
    res = pay.confirm_mock(data.get("order_no", ""), user_id)
    if not res.get("ok"):
        return jsonify({"error": res.get("error")}), 400
    return jsonify({"ok": True, "balance": billing.balance(user_id), "debt": billing.debt(user_id)})


@app.get("/api/recharge/status/<order_no>")
def recharge_status(order_no):
    user_id = current_user_id()
    if user_id is None:
        return need_login()
    o = pay.get_order(order_no)
    if not o or o.get("user_id") != user_id:
        return jsonify({"error": "订单不存在"}), 404
    return jsonify({"order_no": o["order_no"], "status": o.get("status"),
                    "amount": o.get("amount"), "points": o.get("points"),
                    "balance": billing.balance(user_id), "debt": billing.debt(user_id)})


@app.get("/api/recharge/qr/<order_no>.png")
def recharge_qr(order_no):
    user_id = current_user_id()
    if user_id is None:
        return need_login()
    o = pay.get_order(order_no)
    if not o or o.get("user_id") != user_id or not o.get("qr"):
        return jsonify({"error": "订单不存在或未生成二维码"}), 404
    from flask import Response
    return Response(pay.qr_png(o["qr"]), mimetype="image/png")


@app.post("/api/pay/alipay/notify")
def pay_alipay_notify():
    body, _ = pay.handle_notify("alipay", dict(request.form))
    return body


@app.route("/api/pay/epay/notify", methods=["GET", "POST"])
def pay_epay_notify():
    params = dict(request.values)
    body, _ = pay.handle_notify("epay", params)
    return body


# ---------------- 管理后台 ----------------
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "zaowu-admin")
ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "zaowu-admin-secret-change-me")


def _admin_sign() -> str:
    from itsdangerous import URLSafeTimedSerializer
    return URLSafeTimedSerializer(ADMIN_SECRET, salt="zw-admin").dumps({"role": "admin"})


def _admin_ok() -> bool:
    from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
    token = (request.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
    if not token:
        return False
    s = URLSafeTimedSerializer(ADMIN_SECRET, salt="zw-admin")
    try:
        data = s.loads(token, max_age=12 * 3600)
        return data.get("role") == "admin"
    except (BadSignature, SignatureExpired):
        return False


@app.get("/admin")
def admin_page():
    resp = send_file(WEB_DIR / "admin.html")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


@app.post("/api/admin/login")
def admin_login():
    data = request.get_json(silent=True) or {}
    if str(data.get("password", "")) != ADMIN_PASSWORD:
        return jsonify({"error": "密码错误"}), 401
    return jsonify({"ok": True, "token": _admin_sign()})


@app.get("/api/admin/overview")
def admin_overview():
    if not _admin_ok():
        return jsonify({"error": "无权限"}), 401
    usage = billing.usage_summary(1)
    today = next(iter(usage.values()), {"tokens": 0, "points": 0.0})
    users = billing.all_users()
    debtors = [u for u in users if u["debt"] > 0]
    orders = pay._load()["orders"]
    paid_today = sum(1 for o in orders.values() if o.get("status") == "paid")
    pending = sum(1 for o in orders.values() if o.get("status") == "pending")
    return jsonify({
        "users_count": len(users),
        "today_tokens": today["tokens"],
        "today_points": today["points"],
        "revenue_points": billing.revenue_total(),
        "debtors_count": len(debtors),
        "debt_total": round(sum(u["debt"] for u in debtors), 2),
        "orders_total": len(orders),
        "orders_paid": paid_today,
        "orders_pending": pending,
        "running_jobs": sum(1 for v in JOBS.values() if v.get("status") in ("running", "awaiting_clarification")),
    })


@app.get("/api/admin/users")
def admin_users():
    if not _admin_ok():
        return jsonify({"error": "无权限"}), 401
    return jsonify({"users": billing.all_users()})


@app.get("/api/admin/orders")
def admin_orders():
    if not _admin_ok():
        return jsonify({"error": "无权限"}), 401
    limit = min(int(request.args.get("limit", "100")), 500)
    orders = sorted(pay._load()["orders"].values(), key=lambda o: o.get("created_at", 0), reverse=True)[:limit]
    return jsonify({"orders": orders})


@app.get("/api/admin/usage")
def admin_usage():
    if not _admin_ok():
        return jsonify({"error": "无权限"}), 401
    days = min(int(request.args.get("days", "14")), 90)
    return jsonify({"usage": billing.usage_summary(days)})


@app.get("/api/admin/invites")
def admin_invites():
    if not _admin_ok():
        return jsonify({"error": "无权限"}), 401
    return jsonify({"invites": users.list_invites(),
                    "invite_quota": users.INVITE_QUOTA_DEFAULT})


@app.post("/api/admin/invites/create")
def admin_invites_create():
    if not _admin_ok():
        return jsonify({"error": "无权限"}), 401
    data = request.get_json(silent=True) or {}
    try:
        count = max(1, min(int(data.get("count", 10)), 200))
    except (TypeError, ValueError):
        count = 10
    quota = int(data.get("quota", users.INVITE_QUOTA_DEFAULT)) or users.INVITE_QUOTA_DEFAULT
    codes = users.generate_invites(count, quota)
    return jsonify({"ok": True, "codes": codes})


@app.post("/api/admin/invites/set_quota")
def admin_invites_set_quota():
    if not _admin_ok():
        return jsonify({"error": "无权限"}), 401
    data = request.get_json(silent=True) or {}
    code = data.get("code", "")
    try:
        quota = int(data.get("quota", 0))
    except (TypeError, ValueError):
        quota = 0
    if quota <= 0 or not users.set_invite_quota(code, quota):
        return jsonify({"error": "邀请码不存在或已使用"}), 400
    return jsonify({"ok": True})


@app.get("/api/admin/health")
def admin_health():
    if not _admin_ok():
        return jsonify({"error": "无权限"}), 401
    import shutil
    total, _used, free = shutil.disk_usage("/")
    mem = {}
    try:
        for line in open("/proc/meminfo", encoding="utf-8"):
            if line.startswith("MemTotal:"):
                mem["total"] = int(line.split()[1]) * 1024
            if line.startswith("MemAvailable:"):
                mem["available"] = int(line.split()[1]) * 1024
    except OSError:
        mem = {}
    uptime = 0
    try:
        uptime = float(open("/proc/uptime", encoding="utf-8").read().split()[0])
    except OSError:
        pass
    return jsonify({
        "http": "ok",
        "uptime_sec": int(uptime),
        "disk_total": total,
        "disk_free": free,
        "mem_total": mem.get("total", 0),
        "mem_available": mem.get("available", 0),
        "running_jobs": sum(1 for v in JOBS.values() if v.get("status") in ("running", "awaiting_clarification")),
    })


@app.get("/api/admin/jobs")
def admin_jobs():
    if not _admin_ok():
        return jsonify({"error": "无权限"}), 401
    merged = {**jobstore.load_all(), **JOBS}
    rows = sorted(merged.values(), key=lambda j: float(j.get("created_at") or j.get("updated_at") or 0), reverse=True)[:30]
    out = []
    for j in rows:
        tokens = int(j.get("tokens") or 0)
        out.append({
            "job_id": j.get("job_id"),
            "user_id": j.get("user_id", ""),
            "name": j.get("name", ""),
            "status": j.get("status", ""),
            "stage": j.get("stage", ""),
            "tokens": tokens,
            "points": round(billing.tokens_to_points(tokens), 2),
            "at": j.get("created_at"),
        })
    return jsonify({"jobs": out})


if __name__ == "__main__":
    _recover_jobs()
    threading.Thread(target=_watchdog, daemon=True).start()
    threading.Thread(target=_queue_pump, daemon=True).start()
    threading.Thread(target=_maintenance_loop, daemon=True).start()
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    print(f"造物工坊 Web: http://{host}:{port}")
    app.run(host=host, port=port, threaded=True, debug=False)
