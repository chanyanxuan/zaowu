"""生成 og:image 分享卡 1200x630(品牌渐变 + 立方体 + 标题),输出 web/cases/og.png(走 /cases 路由)。"""
from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 630
img = Image.new("RGB", (W, H), (10, 12, 20))
d = ImageDraw.Draw(img)

# 背景径向光斑(多层同心圆近似)
for i, (r, col) in enumerate([(520, (44, 38, 110)), (400, (34, 44, 120)), (280, (50, 26, 100)), (180, (24, 30, 70))]):
    d.ellipse([W * 0.72 - r, H * 0.42 - r, W * 0.72 + r, H * 0.42 + r], fill=col)
# 底噪点
import random
random.seed(7)
for _ in range(4200):
    x, y = random.randint(0, W - 1), random.randint(0, H - 1)
    v = random.randint(0, 12)
    d.point((x, y), fill=(v + 8, v + 10, v + 16))

f_title = ImageFont.truetype("C:/Windows/Fonts/msyhbd.ttc", 92)
f_sub = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 34)
f_brand = ImageFont.truetype("C:/Windows/Fonts/msyhbd.ttc", 30)

# 品牌
d.text((70, 58), "造物工坊", font=f_brand, fill=(174, 162, 251))
d.text((70, 130), "用一段话,", font=f_title, fill=(240, 241, 248))
# 渐变字近似:后半句用紫色
d.text((70, 260), "造一个物", font=f_title, fill=(167, 139, 250))
d.text((70, 392), "AI 生成式 3D 建模 · 输出标准 STEP / STL", font=f_sub, fill=(150, 157, 178))
d.text((70, 452), "描述 → 确认 → 下载,无需 CAD 基础", font=f_sub, fill=(150, 157, 178))

# 右侧渐变立方体(等距投影)
cx, cy = 920, 330
s = 150
grad = [(108, 92, 231), (79, 102, 253)]
def tri(pts, fill):
    d.polygon(pts, fill=fill)
# 顶面
tri([(cx, cy - s * 0.72), (cx + s, cy - s * 0.36), (cx, cy), (cx - s, cy - s * 0.36)], (150, 132, 242))
# 左面
tri([(cx - s, cy - s * 0.36), (cx, cy), (cx, cy + s * 0.9), (cx - s, cy + s * 0.54)], (90, 80, 200))
# 右面
tri([(cx + s, cy - s * 0.36), (cx, cy), (cx, cy + s * 0.9), (cx + s, cy + s * 0.54)], (118, 90, 220))
# 棱线高光
d.line([(cx, cy - s * 0.72), (cx, cy + s * 0.9)], fill=(214, 208, 255), width=3)
d.line([(cx - s, cy - s * 0.36), (cx - s, cy + s * 0.54)], fill=(150, 140, 235), width=3)
d.line([(cx + s, cy - s * 0.36), (cx + s, cy + s * 0.54)], fill=(170, 150, 245), width=3)

# 底部徽章
d.rounded_rectangle([70, 536, 470, 588], radius=26, outline=(120, 108, 230), width=2)
d.text((96, 548), "零件级生成式设计 · 诚实交付", font=f_sub, fill=(174, 162, 251))

img.save(r"C:\Users\Administrator\Desktop\text2cad\web\cases\og.png", optimize=True)
print("og.png saved", img.size)
