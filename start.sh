#!/bin/sh
set -e
mkdir -p /viewer/data /app
# 让预览器后端也能 import 标准件库(/app/library)
export PYTHONPATH="/app${PYTHONPATH:+:$PYTHONPATH}"

# 3D 预览器(容器内监听 0.0.0.0,由 nginx 反代 /viewer/)
# 数据目录 /viewer/data 在预览器根内:前端 dir 参数与文件路径全链路一致
cd /viewer
python -m server_py.server --host 0.0.0.0 --port 3245 &
VIEWER_PID=$!
trap 'kill $VIEWER_PID 2>/dev/null || true' EXIT

# Web 应用(前台运行)
cd /app
exec python web_app.py
