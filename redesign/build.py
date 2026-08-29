"""组装新首页:redesign/part1.html + 旧 JS(带改造替换) + redesign/extra.js -> web/index.html。"""
import re

SRC = r"C:\Users\Administrator\Desktop\text2cad\web\index.html"
PART1 = open(r"C:\Users\Administrator\Desktop\text2cad\redesign\part1.html", encoding="utf-8").read()
EXTRA = open(r"C:\Users\Administrator\Desktop\text2cad\redesign\extra.js", encoding="utf-8").read()

src = open(SRC, encoding="utf-8").read()
blocks = re.findall(r"<script>([\s\S]*?)</script>", src)
assert len(blocks) >= 1, f"script blocks = {len(blocks)}"
EXTRA_MARK = "// ====== 新版 UI 增强 ======"
# 业务 JS = 第一个 script 块去掉可能混入的旧 extra 内容
js = blocks[0].split(EXTRA_MARK)[0]
assert "myModelsBtn" in js and "showResult" in js, "业务 JS 提取异常"

# 1) alert -> toast
n_alert = js.count("alert(")
js = js.replace("alert(", "toast(")

# 2) 案例「用文字试这个」滚动到生成区
js = js.replace("window.scrollTo({top:0, behavior:'smooth'});",
                "document.getElementById('generator').scrollIntoView({behavior:'smooth'});")

# 3) 登录按钮图标
js = js.replace("'<button id=\"loginBtn\" class=\"mini ghost\">🔑 邀请码登录</button>'",
                "'<button id=\"loginBtn\" class=\"mini ghost\"><svg class=\"ic\" style=\"width:14px;height:14px;\"><use href=\"#i-key\"/></svg>邀请码登录</button>'")

# 4) showResult:剧场交付(幂等,适配任意历史版本)
_needle = "function showResult(res) {\n"
if _needle not in js:
    raise SystemExit("showResult 锚点未找到")
if "_empty.style.display = 'none'" not in js:
    js = js.replace(_needle, _needle + "  const _empty = document.getElementById('resultEmpty'); if (_empty) _empty.style.display = 'none';\n", 1)
if "uiStageDone();" not in js:
    js = js.replace(_needle, _needle + "  uiStageDone();\n", 1)
if "theaterDeliver" not in js:
    js = js.replace(_needle, _needle + "  theaterDeliver();\n", 1)

# 6) setStage 同步驱动阶段步骤(幂等)
if "uiStage(text);" not in js:
    js = js.replace("function setStage(text) {\n  stage.textContent = text;",
                    "function setStage(text) {\n  stage.textContent = text;\n  uiStage(text);")

# 5) 开始生成:恢复空态 + 输入区让位(各自幂等)
_r_anchor = "document.getElementById('resultSummary').style.display = 'none';"
if "const _re = document.getElementById('resultEmpty')" not in js:
    js = js.replace(_r_anchor, _r_anchor + "\n  const _re = document.getElementById('resultEmpty'); if (_re) _re.style.display = 'block';")
if "body.classList.add('generating')" not in js:
    js = js.replace(_r_anchor, _r_anchor + "\n  document.body.classList.add('generating');")

out = PART1 + "\n<script>\n" + js + "\n</script>\n<script>\n" + EXTRA + "\n</script>\n</body>\n</html>\n"
open(SRC, "w", encoding="utf-8", newline="\n").write(out)
print("组装完成:", len(out), "字符 | alert替换:", n_alert, "处")
