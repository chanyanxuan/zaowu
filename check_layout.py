from playwright.sync_api import sync_playwright

URL = "https://zaowugongfang.com/"

with sync_playwright() as pw:
    browser = pw.chromium.launch(channel="msedge", headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.goto(URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)
    # 顶栏布局检查
    t = page.evaluate("""() => {
      const tb = document.querySelector('.topbar').getBoundingClientRect();
      const h1 = document.querySelector('.topbar h1').getBoundingClientRect();
      const right = document.querySelector('.topbar-right').getBoundingClientRect();
      return {topbarW: Math.round(tb.width), h1Left: Math.round(h1.left), rightRight: Math.round(right.right), h1Top: Math.round(h1.top), rightTop: Math.round(right.top)};
    }""")
    print("顶栏布局:", t)
    # 登录弹窗里的中文检查
    page.click("#loginBtn")
    page.wait_for_timeout(600)
    body = page.inner_text("#loginOverlay")
    print("登录弹窗文本:", body.replace("\n", " | ")[:120])
    page.screenshot(path=r"C:\Users\Administrator\Desktop\text2cad\layout_check.png")
    browser.close()
