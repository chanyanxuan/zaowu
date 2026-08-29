from playwright.sync_api import sync_playwright

with sync_playwright() as pw:
    browser = pw.chromium.launch(channel="msedge", headless=True)
    # 桌面
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto("https://zaowugongfang.com/", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2500)
    d = page.evaluate("""() => {
      const body = getComputedStyle(document.body);
      const h1 = document.querySelector('.hero h1');
      const h1s = getComputedStyle(h1);
      const brand = getComputedStyle(document.querySelector('.brand'));
      return { bodyBg: body.backgroundColor, heroSize: h1s.fontSize, heroWeight: h1s.fontWeight, brandSize: brand.fontSize, heroText: h1.innerText };
    }""")
    print("桌面版:", d)
    print("JS 错误:", errors[:5] if errors else "无")
    # 手机
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(1500)
    m = page.evaluate("""() => {
      const h1 = getComputedStyle(document.querySelector('.hero h1'));
      const grid = getComputedStyle(document.querySelector('.grid'));
      const iframe = document.querySelector('iframe');
      return { heroSize: h1.fontSize, gridCols: grid.gridTemplateColumns, iframeH: iframe ? iframe.getBoundingClientRect().height : 0, topbarDir: getComputedStyle(document.querySelector('.topbar')).flexDirection };
    }""")
    print("手机版:", m)
    page.screenshot(path=r"C:\Users\Administrator\Desktop\text2cad\ui_mobile.png")
    browser.close()
