# 造物工坊 (Text2CAD)

> 用一段话或一张照片,造一个可以制造的 3D 模型。

造物工坊是一个 AI 生成式 3D 建模产品:输入文字描述或照片,系统自动调研外观、澄清细节、生成 build123d 参数化代码,输出工业通用的 **STEP** 与 **STL** 文件,并提供在线三维预览、参数微调与自然语言修改。

在线地址:<https://zaowugongfang.com>

## 功能

- **文/图生成 3D 模型**:文字或 1~3 张照片 → 工程规格 → 澄清问答(推荐默认值,可一键全选)→ 自纠错代码生成 → STEP/STL + 快照
- **外观调研**:生成前由模型内置知识整理造型规格书(不联网)
- **参数微调**:自动提取顶层尺寸常量,拖动滑杆本地重建(≈0 积分)
- **自然语言修改**:在预览中点选零件,一句话改模型
- **装配体**:多零件装配 + 结构树 + 爆炸展开
- **标准件库**(零积分、免登录):
  - 12 个 build123d 原生标准件(紧固件/运动件/结构件/打印件,国标查表)
  - 4 个 OpenSCAD 打印件(BOSL2 / dotSCAD / Gridfinity,服务器渲染 STL)
  - step.parts 外部零件检索(12,000+ 开源 STEP,支持中文检索与一键搜)
- **积分计费**:1 元 = 10 积分,允许欠费,补款优先还欠款;邀请码登录
- **运营**:全局队列(并发可配)、心跳看门狗、每日备份与清理、管理后台

## 技术栈

- 后端:Python / Flask
- 几何内核:build123d + cadquery-ocp(OpenCascade),OpenSCAD(打印件渲染)
- 大模型:DeepSeek(代码/辅助)+ Moonshot Kimi(视觉)
- 前端:单页原生 JS + 深色设计系统(构建源见 `redesign/`,由 `redesign/build.py` 组装)
- 三维预览:自研 CAD Viewer(WebGL,已汉化,源码见 `cad-viewer-src/`)
- 部署:Docker Compose + nginx + Let's Encrypt

## 目录结构

```
web_app.py            # Flask 入口与全部接口
text2cad_proto.py     # 生成管线(精炼/理解/问答/代码/构建/参数)
library/              # 标准件库(build123d 零件 + OpenSCAD 目录)
web/                  # 前端(含构建产物 index.html)
redesign/             # 前端构建源(part1.html + extra.js + build.py)
cad-viewer-src/       # 三维预览器(汉化版)
billing.py users.py pay.py jobstore.py   # 计费/账号/支付/任务持久化
make_zip.py redeploy2.py                 # 打包与部署脚本
Dockerfile docker-compose.yml nginx.conf start.sh
docs: 上线清单.md 部署说明.md 产品形态方案.md …
```

## 本地开发

```bash
pip install -r requirements_server.txt
python -m playwright install --with-deps chromium

# 环境变量(参考 .env.example)
$env:DEEPSEEK_API_KEY = "sk-..."
$env:MOONSHOT_API_KEY  = "sk-..."
$env:REQUIRE_AUTH      = "0"   # 本地调试可关闭登录
python web_app.py               # http://127.0.0.1:5000
```

三维预览器构建:见 `cad-viewer-src/` 与 `make_zip.py`(默认引用本机 skill 目录)。

## 部署

见 `部署说明.md` 与 `上线清单.md`。核心流程:`make_zip.py` 打包 → `redeploy2.py` 上传并重建容器。
部署脚本不再内置服务器密码:运行前设置环境变量 `ZW_SERVER_PASS`。

## 许可与致谢

- 本项目代码基于 [earthtojake/text-to-cad](https://github.com/earthtojake/text-to-cad)(MIT)演进而来
- 标准件库引用:BOSL2(BSD-3)、dotSCAD(MIT)、Gridfinity Rebuilt(MIT);NopSCADlib(GPLv3)仅作数据表参考,未并入代码
- 外部零件检索数据来自 [step.parts](https://www.step.parts)(开源 STEP 集合,各件遵循其来源许可)

## 免责声明

本产品定位为「零件级」生成式设计工具,输出适合原型验证、3D 打印与设计沟通;
公差、强度校核、模具设计等工业级环节需专业工程师复核。
