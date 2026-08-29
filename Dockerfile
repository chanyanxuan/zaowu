# 造物工坊 生产镜像(Web 应用 + 3D 预览器同容器)
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# OCP 内核、Chromium 快照、OpenSCAD 打印件渲染所需的系统库
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libxkbcommon0 libxcomposite1 libxdamage1 \
    fonts-noto-cjk curl openscad git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 依赖层(利用 Docker 缓存;cadquery-ocp 体积大)
COPY requirements_server.txt .
RUN pip install -r requirements_server.txt \
 && python -m playwright install --with-deps chromium

# 应用代码
COPY web_app.py text2cad_proto.py billing.py users.py pay.py jobstore.py ./
COPY web ./web
COPY library ./library
COPY text-to-cad/skills/cad ./text-to-cad/skills/cad

# 开源 OpenSCAD 打印件库(BOSL2 / dotSCAD / gridfinity)
RUN git clone --depth 1 https://github.com/BelfrySCAD/BOSL2 /app/library/oscad/BOSL2 \
 && git clone --depth 1 https://github.com/JustinSDK/dotSCAD /app/library/oscad/dotSCAD \
 && git clone --depth 1 https://github.com/kennetek/gridfinity-rebuilt-openscad /app/library/oscad/gridfinity-rebuilt-openscad \
 && rm -rf /app/library/oscad/*/.git

# 生产环境用 Chromium 截图(本机 Windows 开发时用 Edge)
RUN sed -i 's/channel="msedge"/channel="chromium"/' \
    /app/text-to-cad/skills/cad/scripts/packages/cadgen/src/cadgen/snapshot_core.py || true

# 3D 预览器(预构建 dist + Python 静态服务)
COPY viewer /viewer

COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

ENV ZW_DATA_DIR=/viewer/data HOST=0.0.0.0 PORT=5000
VOLUME /viewer/data
EXPOSE 5000 3245
CMD ["/app/start.sh"]
