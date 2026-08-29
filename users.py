"""造物工坊 用户系统:手机验证码注册/登录 + 会话 token + 短信发送适配。

短信供应商可切换(mock / tencent / webhook),全部走环境变量配置;
本地开发默认 mock:验证码直接打印到日志并随响应返回,方便联调。

存储: users_store.json (手机号 -> 用户; token -> 手机号; 验证码与限流)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import random
import secrets
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
STORE_PATH = Path(os.environ.get("ZW_DATA_DIR", str(BASE))) / "users_store.json"

# ---------------- 配置(环境变量优先) ----------------
SMS_PROVIDER = os.environ.get("SMS_PROVIDER", "mock")     # mock | tencent | webhook
SMS_SIGN = os.environ.get("SMS_SIGN", "造物工坊")          # 短信签名(需在供应商后台报备)
SMS_TEMPLATE_ID = os.environ.get("SMS_TEMPLATE_ID", "")    # 腾讯云模板 ID
TENCENT_SECRET_ID = os.environ.get("TENCENT_SECRET_ID", "")
TENCENT_SECRET_KEY = os.environ.get("TENCENT_SECRET_KEY", "")
TENCENT_SMS_SDK_APP_ID = os.environ.get("TENCENT_SMS_SDK_APP_ID", "")
SMS_WEBHOOK_URL = os.environ.get("SMS_WEBHOOK_URL", "")    # 通用 HTTP 模板,{phone} {code} 占位
SMS_WEBHOOK_METHOD = os.environ.get("SMS_WEBHOOK_METHOD", "GET")

CODE_TTL = 300        # 验证码有效期(秒)
SEND_INTERVAL = 60    # 同号发送间隔(秒)
CODE_LEN = 6
TOKEN_TTL = 60 * 60 * 24 * 30   # 登录态 30 天


def _load() -> dict:
    if STORE_PATH.is_file():
        try:
            return json.loads(STORE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"users": {}, "tokens": {}, "codes": {}}


def _save(data: dict) -> None:
    STORE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _now() -> int:
    return int(time.time())


def valid_phone(phone: str) -> bool:
    p = str(phone or "").strip()
    return len(p) == 11 and p.isdigit() and p.startswith("1")


# ---------------- 短信发送 ----------------
def _tencent_send(phone: str, code: str) -> tuple[bool, str]:
    """腾讯云短信 TC3-HMAC-SHA256 签名(纯标准库,无 SDK)。"""
    import requests
    host = "sms.tencentcloudapi.com"
    service = "sms"
    version = "2021-01-11"
    action = "SendSms"
    region = "ap-guangzhou"
    payload = json.dumps({
        "PhoneNumberSet": ["+86" + phone],
        "SmsSdkAppId": TENCENT_SMS_SDK_APP_ID,
        "SignName": SMS_SIGN,
        "TemplateId": SMS_TEMPLATE_ID,
        "TemplateParamSet": [code],
    }, separators=(",", ":"))
    ts = int(time.time())
    date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
    ct = "application/json; charset=utf-8"
    canonical_request = "\n".join(["POST", "/", "", f"content-type:{ct}", f"host:{host}", "", "content-type;host", hashlib.sha256(payload.encode()).hexdigest()])
    credential_scope = f"{date}/{service}/tc3_request"
    string_to_sign = "\n".join(["TC3-HMAC-SHA256", str(ts), credential_scope, hashlib.sha256(canonical_request.encode()).hexdigest()])
    def _hmac(key, msg):
        return hmac.new(key, msg.encode(), hashlib.sha256).digest()
    secret_date = _hmac(("TC3" + TENCENT_SECRET_KEY).encode(), date)
    secret_service = _hmac(secret_date, service)
    secret_signing = _hmac(secret_service, "tc3_request")
    signature = hmac.new(secret_signing, string_to_sign.encode(), hashlib.sha256).hexdigest()
    auth = (f"TC3-HMAC-SHA256 Credential={TENCENT_SECRET_ID}/{credential_scope}, "
            f"SignedHeaders=content-type;host, Signature={signature}")
    r = requests.post(
        f"https://{host}", data=payload.encode(), timeout=8,
        headers={"Authorization": auth, "Content-Type": ct, "X-TC-Action": action,
                 "X-TC-Version": version, "X-TC-Timestamp": str(ts), "X-TC-Region": region},
    )
    resp = r.json().get("Response", {})
    if resp.get("Error"):
        return False, f"腾讯云短信错误: {resp['Error'].get('Code')} {resp['Error'].get('Message')}"
    statuses = resp.get("SendStatusSet") or []
    for s in statuses:
        if s.get("Code") != "Ok":
            return False, f"短信发送失败: {s.get('Code')} {s.get('Message')}"
    return True, ""


def _webhook_send(phone: str, code: str) -> tuple[bool, str]:
    import requests
    url = SMS_WEBHOOK_URL.replace("{phone}", phone).replace("{code}", code)
    try:
        if SMS_WEBHOOK_METHOD.upper() == "POST":
            r = requests.post(url, timeout=8)
        else:
            r = requests.get(url, timeout=8)
        return (r.status_code == 200), f"HTTP {r.status_code}"
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def _send_sms(phone: str, code: str) -> tuple[bool, str]:
    if SMS_PROVIDER == "tencent":
        if not all([TENCENT_SECRET_ID, TENCENT_SECRET_KEY, TENCENT_SMS_SDK_APP_ID, SMS_TEMPLATE_ID]):
            return False, "腾讯云短信未配置(SECRET_ID/SECRET_KEY/SDK_APP_ID/TEMPLATE_ID)"
        return _tencent_send(phone, code)
    if SMS_PROVIDER == "webhook":
        if not SMS_WEBHOOK_URL:
            return False, "SMS_WEBHOOK_URL 未配置"
        return _webhook_send(phone, code)
    # mock:直接打印,不真正发送
    print(f"[SMS-MOCK] 向 {phone} 发送验证码: {code} (签名:{SMS_SIGN})")
    return True, ""


# ---------------- 验证码 ----------------
def send_code(phone: str) -> dict:
    """发送验证码。返回 {ok, error?, code?} —— code 仅在 mock 模式返回,便于本地测试。"""
    if not valid_phone(phone):
        return {"ok": False, "error": "手机号格式不对(11 位大陆手机号)"}
    data = _load()
    last = data["codes"].get(phone, {}).get("sent_at", 0)
    if _now() - last < SEND_INTERVAL:
        return {"ok": False, "error": f"发送太频繁,{SEND_INTERVAL - (_now() - last)} 秒后再试"}
    code = "".join(str(random.randint(0, 9)) for _ in range(CODE_LEN))
    ok, err = _send_sms(phone, code)
    if not ok:
        return {"ok": False, "error": err}
    data["codes"][phone] = {"code": code, "sent_at": _now(), "expire_at": _now() + CODE_TTL, "tries": 0}
    _save(data)
    return {"ok": True, "code": code if SMS_PROVIDER == "mock" else None}


def verify_code(phone: str, code: str) -> bool:
    data = _load()
    rec = data["codes"].get(phone)
    if not rec or not code:
        return False
    if _now() > rec.get("expire_at", 0):
        return False
    if rec.get("tries", 0) >= 5:
        return False
    if hmac.compare_digest(str(rec.get("code", "")), str(code).strip()):
        data["codes"].pop(phone, None)
        _save(data)
        return True
    rec["tries"] = rec.get("tries", 0) + 1
    _save(data)
    return False


# ---------------- 用户与会话 ----------------
def ensure_user(user_id: str) -> dict:
    data = _load()
    u = data["users"].get(user_id)
    if not u:
        u = {"user_id": user_id, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "uid": uuid.uuid4().hex[:12]}
        data["users"][user_id] = u
        _save(data)
    return u


def issue_token(user_id: str) -> str:
    data = _load()
    token = secrets.token_hex(24)
    data["tokens"][token] = {"user": user_id, "expire_at": _now() + TOKEN_TTL}
    # 清理过期 token
    for t in [t for t, v in data["tokens"].items() if _now() > v.get("expire_at", 0)]:
        data["tokens"].pop(t, None)
    _save(data)
    return token


def token_to_user(token: str) -> str | None:
    data = _load()
    rec = data["tokens"].get(token or "")
    if not rec or _now() > rec.get("expire_at", 0):
        return None
    return rec.get("user")


def token_to_phone(token: str) -> str | None:
    """兼容旧接口:仅当绑定的用户是 11 位手机号时返回。"""
    u = token_to_user(token)
    return u if u and len(u) == 11 and u.isdigit() else None


def logout(token: str) -> None:
    data = _load()
    data["tokens"].pop(token or "", None)
    _save(data)


# ---------------- 内测邀请码 ----------------
INVITE_QUOTA_DEFAULT = 50  # 每个邀请码 = 50 积分(5 元额度)


def generate_invites(count: int, quota: int = INVITE_QUOTA_DEFAULT) -> list[str]:
    """生成 count 个邀请码。格式 XXXX-XXXX-XXXX。"""
    codes = []
    data = _load()
    for _ in range(int(count)):
        while True:
            code = "-".join(
                "".join(secrets.choice("ABCDEFGHJKMNPQRSTUVWXYZ23456789") for _ in range(4))
                for _ in range(3)
            )
            if code not in data.setdefault("invites", {}):
                break
        data["invites"][code] = {"quota": int(quota), "status": "unused",
                                 "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                 "used_by": None, "used_at": None}
        codes.append(code)
    _save(data)
    return codes


def list_invites() -> list[dict]:
    data = _load()
    out = []
    for code, inv in data.get("invites", {}).items():
        out.append({"code": code, **inv})
    out.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return out


def redeem_invite(code: str) -> dict | None:
    """兑换邀请码:未用过则标记已用并返回用户信息。"""
    code = str(code or "").strip().upper()
    data = _load()
    inv = data.get("invites", {}).get(code)
    if not inv or inv.get("status") != "unused":
        return None
    user_id = "u_" + code.replace("-", "").lower()
    inv["status"] = "used"
    inv["used_by"] = user_id
    inv["used_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _save(data)
    ensure_user(user_id)
    return {"user_id": user_id, "quota": int(inv.get("quota", 0)), "code": code}


def set_invite_quota(code: str, quota: int) -> bool:
    """修改未使用邀请码的额度。返回是否成功。"""
    code = str(code or "").strip().upper()
    data = _load()
    inv = data.get("invites", {}).get(code)
    if not inv or inv.get("status") != "unused":
        return False
    inv["quota"] = max(1, int(quota))
    _save(data)
    return True
