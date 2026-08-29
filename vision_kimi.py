"""调用 Kimi(Moonshot)视觉模型看图,输出 CAD 规格卡草稿。

用法:
  python vision_kimi.py <图片路径> [--prompt 文本] [--model 模型名]
依赖环境变量 MOONSHOT_API_KEY(由调用方注入)。
"""
import base64
import io
import json
import os
import sys

import requests
from PIL import Image

MOONSHOT_BASE = "https://api.moonshot.cn/v1"
DEFAULT_MODEL = "moonshot-v1-8k-vision-preview"
MAX_EDGE = 1280


def prepare_image(path: str) -> str:
    """压缩/降采样图片,返回 base64 data URL(JPEG)。"""
    im = Image.open(path).convert("RGBA")
    # 合成到白底(去透明)
    bg = Image.new("RGB", im.size, (255, 255, 255))
    bg.paste(im, mask=im.split()[3])
    im = bg
    # 降采样
    im.thumbnail((MAX_EDGE, MAX_EDGE), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=88)
    data = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/jpeg;base64,{data}"


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print("usage: python vision_kimi.py <image> [--prompt text]", file=sys.stderr)
        return 2
    image_path = args[0]
    prompt = (
        "你是一名 CAD 逆向建模助手。请仔细观察这张照片中的物体,并分点回答:\n"
        "1) 这是什么物体,用途是什么;\n"
        "2) 整体外形(板状/块状/圆柱/异形截面等),以及哪个面是底面/放置面;\n"
        "3) 可见的特征:孔、槽、圆角、倒角、凸台、筋、文字等,尽量说清数量和位置;\n"
        "4) 长/宽/高的大致比例关系;\n"
        "5) 照片里看不到的(背面、底面、内部结构、厚度等)。\n"
        "重要:不要编造具体毫米尺寸,除非图里能确定;不确定的就说不知道。"
    )
    model = DEFAULT_MODEL
    if "--prompt" in args:
        prompt = args[args.index("--prompt") + 1]
    if "--model" in args:
        model = args[args.index("--model") + 1]

    api_key = os.environ.get("MOONSHOT_API_KEY")
    if not api_key:
        print("ERROR: MOONSHOT_API_KEY 未设置", file=sys.stderr)
        return 1

    data_url = prepare_image(image_path)
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        r = requests.post(
            f"{MOONSHOT_BASE}/chat/completions",
            headers=headers,
            json=payload,
            timeout=120,
        )
    except requests.RequestException as e:
        print(f"ERROR: 请求失败: {e}", file=sys.stderr)
        return 1

    if r.status_code != 200:
        print(f"ERROR: HTTP {r.status_code}: {r.text[:500]}", file=sys.stderr)
        return 1

    data = r.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        print(f"ERROR: 响应结构异常: {json.dumps(data, ensure_ascii=False)[:500]}", file=sys.stderr)
        return 1

    usage = data.get("usage", {})
    print(content)
    print("\n----[usage]----", file=sys.stderr)
    print(json.dumps(usage, ensure_ascii=False), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
