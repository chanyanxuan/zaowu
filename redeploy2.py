import os
import paramiko
import time

# 服务器 root 密码不再硬编码:部署前设置环境变量 ZW_SERVER_PASS
SERVER_PASS = os.environ.get("ZW_SERVER_PASS", "")
if not SERVER_PASS:
    raise SystemExit("请先设置环境变量 ZW_SERVER_PASS(服务器 root 密码),再运行本脚本")

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("47.236.164.118", username="root", password=SERVER_PASS, timeout=20)


def run(cmd, timeout=1200):
    print("$", cmd)
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout, get_pty=True)
    out = ""
    while True:
        line = stdout.readline()
        if not line:
            break
        out += line
        print(line.rstrip("\n"))
    rest = stdout.read().decode(errors="replace")
    if rest:
        out += rest
        print(rest.rstrip("\n"))
    code = stdout.channel.recv_exit_status()
    return code, out


# 上传新包并解压
sftp = ssh.open_sftp()
sftp.put(r"C:\Users\Administrator\Desktop\text2cad\zaowu-deploy.zip", "/tmp/zaowu-deploy.zip")
sftp.close()
print("已上传")
run("cd /opt/zaowu && python3 -m zipfile -e /tmp/zaowu-deploy.zip .")

# 前端需要把 REQUIRE_AUTH=1 + PAY_ENABLED 保持(已是 1/默认 0)
run("grep -E 'REQUIRE_AUTH|PAY_ENABLED|ADMIN_PASSWORD' /opt/zaowu/.env")

# 重建并启动(依赖层缓存,几分钟);构建完清理悬空镜像,防止磁盘被旧镜像占满
run("cd /opt/zaowu && docker compose build 2>&1 | tail -n 5")
run("docker image prune -f 2>&1 | tail -n 1")
run("cd /opt/zaowu && docker compose up -d 2>&1 | tail -n 2")

time.sleep(10)
run("docker ps -a --format '{{.Names}} {{.Status}}'", timeout=60)
code, out = run("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:80", timeout=60)
print("本机 80:", out.strip())
ssh.close()
