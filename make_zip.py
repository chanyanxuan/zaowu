"""用 Python zipfile 打包部署包(条目全部用正斜杠,避免 Windows 反斜杠坑)。"""
import os
import zipfile

ROOT = r"C:\Users\Administrator\Desktop\text2cad"
VIEWER = r"C:\Users\Administrator\.agents\skills\cad-viewer\scripts\viewer"
OUT = os.path.join(ROOT, "zaowu-deploy.zip")

EXCLUDE_DIRS = {"__pycache__", "dist.bak", "moveit2_server", "node_modules", ".git"}
FILES = [
    "web_app.py", "text2cad_proto.py", "billing.py", "users.py", "pay.py",
    "jobstore.py", "Dockerfile", "docker-compose.yml", "nginx.conf",
    "start.sh", "requirements_server.txt", ".env.example", "上线清单.md",
]


def add_dir(z, src, arc_prefix):
    for dirpath, dirnames, filenames in os.walk(src):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, src).replace("\\", "/")
            z.write(full, arc_prefix + "/" + rel)


z = zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED)
for f in FILES:
    p = os.path.join(ROOT, f)
    if os.path.isfile(p):
        z.write(p, f)
add_dir(z, os.path.join(ROOT, "web"), "web")
add_dir(z, os.path.join(ROOT, "library"), "library")
add_dir(z, os.path.join(ROOT, "text-to-cad", "skills", "cad", "scripts"), "text-to-cad/skills/cad/scripts")
add_dir(z, VIEWER, "viewer")
z.close()

print("打包完成:", OUT, f"{os.path.getsize(OUT) / 1024 / 1024:.1f} MB")
z2 = zipfile.ZipFile(OUT)
bad = sum(1 for n in z2.namelist() if "\\" in n)
print("含反斜杠条目:", bad, "(应为 0)")
print("条目总数:", len(z2.namelist()))
