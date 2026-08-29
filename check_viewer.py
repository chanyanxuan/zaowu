from playwright.sync_api import sync_playwright

URL = ("https://zaowugongfang.com/viewer/data/proto_out/"
       "model_20260821_163435?file=model_20260821_163435.step.py")

with sync_playwright() as pw:
    browser = pw.chromium.launch(channel="msedge", headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    bad = []
    page.on("response", lambda r: bad.append(r.status) if r.status >= 400 else None)
    page.goto(URL, wait_until="domcontentloaded", timeout=120000)
    page.wait_for_timeout(75000)
    body = page.inner_text("body")
    print("Loading CAD:", "Loading CAD" in body, "| Loading tree:", "Loading STEP tree" in body)
    print("结构树含模型名:", "model_20260821_163435" in body)
    print("失败请求:", len(bad))
    page.screenshot(path=r"C:\Users\Administrator\Desktop\text2cad\viewer_ok.png")
    browser.close()
