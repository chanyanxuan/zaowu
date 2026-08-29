"""造物工坊 支付模块:充值订单 + 三种网关(mock / alipay 当面付 / epay 易支付)。

流程: 前端 POST /api/recharge/create -> 后端建订单(未支付,10 分钟过期)
      -> 网关返回二维码内容 -> 前端展示二维码并轮询订单状态
      -> 用户付款 -> 网关异步回调 /api/pay/<gateway>/notify(验签)
      -> 后端幂等地标记已支付 -> 自动加积分(先抵扣欠款)

配置全部走环境变量;未配置时默认 mock(模拟支付,仅本地测试用)。
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import time
import uuid
import urllib.parse
from pathlib import Path

import billing

BASE = Path(__file__).resolve().parent
STORE_PATH = Path(os.environ.get("ZW_DATA_DIR", str(BASE))) / "orders_store.json"

PAY_GATEWAY = os.environ.get("PAY_GATEWAY", "mock")   # mock | alipay | epay
PUBLIC_BASE = os.environ.get("PUBLIC_BASE", "http://127.0.0.1:5000")  # 公网域名,回调必须可访问

# 支付宝当面付(预下单)
ALIPAY_APP_ID = os.environ.get("ALIPAY_APP_ID", "")
ALIPAY_PRIVATE_KEY = os.environ.get("ALIPAY_PRIVATE_KEY", "")   # 应用私钥(PEM,一行格式需含 \n)
ALIPAY_PUBLIC_KEY = os.environ.get("ALIPAY_PUBLIC_KEY", "")     # 支付宝公钥(验签用)
ALIPAY_GATEWAY = "https://openapi.alipay.com/gateway.do"

# 易支付/免签(epay 协议)
EPAY_API_URL = os.environ.get("EPAY_API_URL", "")   # 如 https://xxx.com/submit.php
EPAY_PID = os.environ.get("EPAY_PID", "")
EPAY_KEY = os.environ.get("EPAY_KEY", "")

ORDER_TTL = 600  # 订单有效期 10 分钟


def _load() -> dict:
    if STORE_PATH.is_file():
        try:
            return json.loads(STORE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"orders": {}}


def _save(data: dict) -> None:
    STORE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _alipay_sign(params: dict) -> str:
    """RSA2(SHA256)签名。"""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    key = ALIPAY_PRIVATE_KEY
    if "\\n" in key:
        key = key.replace("\\n", "\n")
    if "-----" not in key:
        key = f"-----BEGIN RSA PRIVATE KEY-----\n{key}\n-----END RSA PRIVATE KEY-----"
    pk = serialization.load_pem_private_key(key.encode(), password=None)
    content = "&".join(f"{k}={v}" for k, v in sorted(params.items()) if v not in ("", None))
    sig = pk.sign(content.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(sig).decode()


def _alipay_verify(params: dict) -> bool:
    """验签支付宝异步通知(RSA2/SHA256)。"""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    sign = params.get("sign", "")
    sign_type = params.get("sign_type", "RSA2")
    content = "&".join(f"{k}={v}" for k, v in sorted(params.items()) if k not in ("sign", "sign_type") and v not in ("", None))
    pub = ALIPAY_PUBLIC_KEY
    if "\\n" in pub:
        pub = pub.replace("\\n", "\n")
    if "-----" not in pub:
        pub = f"-----BEGIN PUBLIC KEY-----\n{pub}\n-----END PUBLIC KEY-----"
    pk = serialization.load_pem_public_key(pub.encode())
    try:
        pk.verify(base64.b64decode(sign), content.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
        return True
    except Exception:  # noqa: BLE001
        return False


def create_order(user_id: str, amount_yuan: float) -> dict:
    amount = float(amount_yuan)
    if amount <= 0:
        return {"ok": False, "error": "金额必须大于 0"}
    order_no = "ZW" + time.strftime("%Y%m%d%H%M%S") + uuid.uuid4().hex[:8].upper()
    data = _load()
    data["orders"][order_no] = {
        "order_no": order_no, "user_id": user_id, "amount": round(amount, 2),
        "points": int(amount * billing.POINTS_PER_YUAN),
        "status": "pending", "gateway": PAY_GATEWAY, "created_at": int(time.time()),
        "paid_at": None,
    }
    _save(data)

    if PAY_GATEWAY == "alipay":
        if not all([ALIPAY_APP_ID, ALIPAY_PRIVATE_KEY]):
            return {"ok": False, "error": "支付宝当面付未配置(APP_ID/PRIVATE_KEY)"}
        notify = f"{PUBLIC_BASE}/api/pay/alipay/notify"
        params = {
            "app_id": ALIPAY_APP_ID, "method": "alipay.trade.precreate",
            "charset": "utf-8", "sign_type": "RSA2", "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "version": "1.0", "notify_url": notify,
            "biz_content": json.dumps({
                "out_trade_no": order_no, "total_amount": f"{amount:.2f}",
                "subject": "造物工坊 积分充值", "timeout_express": "10m",
            }, ensure_ascii=False),
        }
        params["sign"] = _alipay_sign(params)
        import requests
        r = requests.post(ALIPAY_GATEWAY, data=params, timeout=10)
        resp = r.json().get("alipay_trade_precreate_response", {})
        if resp.get("code") != "10000":
            return {"ok": False, "error": f"支付宝下单失败: {resp.get('sub_msg') or resp.get('msg')}"}
        qr = resp.get("qr_code", "")
    elif PAY_GATEWAY == "epay":
        if not all([EPAY_API_URL, EPAY_PID, EPAY_KEY]):
            return {"ok": False, "error": "易支付未配置(API_URL/PID/KEY)"}
        import requests
        params = {
            "pid": EPAY_PID, "type": "alipay", "out_trade_no": order_no,
            "notify_url": f"{PUBLIC_BASE}/api/pay/epay/notify",
            "return_url": PUBLIC_BASE, "name": "造物工坊 积分充值", "money": f"{amount:.2f}",
        }
        params["sign"] = _epay_sign(params)
        params["sign_type"] = "MD5"
        r = requests.get(EPAY_API_URL, params=params, timeout=10)
        try:
            resp = r.json()
        except Exception:  # noqa: BLE001
            resp = {}
        if resp.get("code") != 1:
            return {"ok": False, "error": f"易支付下单失败: {resp.get('msg', '未知错误')}"}
        qr = resp.get("qrcode") or resp.get("payurl") or resp.get("url", "")
    else:  # mock
        qr = "MOCK"

    if not qr:
        return {"ok": False, "error": "网关未返回二维码"}
    data = _load()
    data["orders"][order_no]["qr"] = qr
    _save(data)
    return {"ok": True, "order_no": order_no, "qr": qr, "gateway": PAY_GATEWAY,
            "amount": round(amount, 2), "points": data["orders"][order_no]["points"]}


def _epay_sign(params: dict) -> str:
    raw = "&".join(f"{k}={v}" for k, v in sorted(params.items()) if v not in ("", None) and k not in ("sign", "sign_type"))
    return hashlib.md5((raw + EPAY_KEY).encode("utf-8")).hexdigest()


def _epay_verify(params: dict) -> bool:
    sign = params.get("sign", "")
    return _epay_sign(params) == sign


def _credit(order: dict) -> None:
    """标记已支付并自动加积分(先抵扣欠款)。幂等:只处理 pending 订单。"""
    data = _load()
    o = data["orders"].get(order["order_no"])
    if not o or o.get("status") != "pending":
        return
    o["status"] = "paid"
    o["paid_at"] = int(time.time())
    _save(data)
    debt_before = billing.debt(o["user_id"])
    billing.recharge(o["user_id"], o["points"], amount=o["amount"], channel=o["gateway"])
    print(f"[支付] 订单 {o['order_no']} 到账 {o['amount']} 元 -> +{o['points']} 积分"
          + (f" (抵扣欠款 {min(debt_before, o['points'])})" if debt_before > 0 else ""))


def confirm_mock(order_no: str, user_id: str) -> dict:
    """mock 网关的"模拟支付成功"(仅本地测试)。"""
    data = _load()
    o = data["orders"].get(order_no)
    if not o or o.get("user_id") != user_id:
        return {"ok": False, "error": "订单不存在"}
    if o.get("gateway") != "mock":
        return {"ok": False, "error": "该订单不是模拟支付"}
    _credit(o)
    return {"ok": True}


def handle_notify(gateway: str, params: dict) -> tuple[str, str]:
    """处理异步回调。返回 (响应体, 订单号)。"""
    out_trade_no = str(params.get("out_trade_no", ""))
    data = _load()
    o = data["orders"].get(out_trade_no)
    if not o:
        return ("fail" if gateway == "epay" else "failure"), out_trade_no
    if o.get("status") == "paid":
        return ("success", out_trade_no)
    if gateway == "alipay":
        if not _alipay_verify(params):
            return "failure", out_trade_no
        if params.get("trade_status") not in ("TRADE_SUCCESS", "TRADE_FINISHED"):
            return "success", out_trade_no
        # 金额核对
        if abs(float(params.get("total_amount", 0)) - o["amount"]) > 0.01:
            return "failure", out_trade_no
        _credit(o)
        return "success", out_trade_no
    if gateway == "epay":
        if not _epay_verify(params):
            return "fail", out_trade_no
        if params.get("trade_status") != "TRADE_SUCCESS":
            return "success", out_trade_no
        if abs(float(params.get("money", 0)) - o["amount"]) > 0.01:
            return "fail", out_trade_no
        _credit(o)
        return "success", out_trade_no
    return ("fail" if gateway == "epay" else "failure"), out_trade_no


def get_order(order_no: str) -> dict | None:
    return _load()["orders"].get(order_no)


def expire_orders() -> None:
    data = _load()
    now = int(time.time())
    changed = False
    for o in data["orders"].values():
        if o.get("status") == "pending" and now - o.get("created_at", 0) > ORDER_TTL:
            o["status"] = "expired"
            changed = True
    if changed:
        _save(data)


def qr_png(content: str) -> bytes:
    """把二维码内容渲染成 PNG。"""
    import io
    import qrcode
    qr = qrcode.QRCode(box_size=6, border=2)
    qr.add_data(content)
    qr.make(fit=True)
    img = qr.make_image()
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
