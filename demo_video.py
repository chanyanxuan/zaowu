"""录制造物工坊演示视频:打开网站 → 邀请码登录 → 文字生成 → 确认细节 → 3D 预览旋转。"""
import sys
import time

from playwright.sync_api import sync_playwright

SITE = "https://zaowugongfang.com"
CODE = "GK58-CQK2-RW5D"
NOTE = "一个100×60×8毫米的安装板,四角各一个M4通孔,孔心距边8毫米,外棱圆角R4,3D打印"
OUT_DIR = r"C:\Users\Administrator\Desktop\text2cad\video_out"


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge", headless=True)
        ctx = browser.new_context(
            viewport={"width": 1440, "height": 900},
            record_video_dir=OUT_DIR,
            record_video_size={"width": 1440, "height": 900},
        )
        page = ctx.new_page()
        page.on("dialog", lambda d: d.accept())

        print("[1] 打开首页…")
        page.goto(SITE, wait_until="load", timeout=60000)
        page.wait_for_timeout(2500)

        print("[2] 邀请码登录…")
        page.click("#loginBtn")
        page.wait_for_timeout(800)
        page.fill("#inviteCode", CODE)
        page.wait_for_timeout(600)
        page.click("#loginGo")
        page.wait_for_timeout(2500)

        print("[3] 输入描述…")
        page.fill("#note", NOTE)
        page.wait_for_timeout(1500)
        page.click("#go")

        print("[4] 等待生成(最长 6 分钟)…")
        deadline = time.time() + 360
        answered = False
        while time.time() < deadline:
            # 澄清弹窗:自动点确认
            if page.locator("#overlay.show").count() and not answered:
                print("    [澄清] 自动确认细节…")
                page.wait_for_timeout(2000)
                page.click("#submitAnswers")
                answered = True
                page.wait_for_timeout(1000)
                continue
            if page.locator("#result:visible").count():
                print("    生成完成!")
                break
            page.wait_for_timeout(3000)

        print("[5] 展示结果页…")
        page.wait_for_timeout(1500)
        page.evaluate("window.scrollBy(0, 600)")
        page.wait_for_timeout(1200)
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(1000)

        print("[6] 3D 预览旋转…")
        frame = page.frame_locator("#viewer")
        try:
            frame.locator("canvas").first.wait_for(state="visible", timeout=30000)
        except Exception as e:  # noqa: BLE001
            print("    画布等待警告:", e)
        page.wait_for_timeout(3000)
        try:
            box = page.locator("#viewer").bounding_box()
            if box:
                cx, cy = box["x"] + box["width"] * 0.62, box["y"] + box["height"] * 0.45
                page.mouse.move(cx, cy)
                page.mouse.down()
                for i in range(30):
                    page.mouse.move(cx + (i - 15) * 8, cy + 15 * (1 if i % 2 else -1))
                    page.wait_for_timeout(40)
                page.mouse.up()
                page.wait_for_timeout(2500)
        except Exception as e:  # noqa: BLE001
            print("    旋转失败:", e)

        print("[7] 收尾…")
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(2000)

        ctx.close()
        browser.close()
        print("✅ 录制完成,视频在:", OUT_DIR)


if __name__ == "__main__":
    main()
