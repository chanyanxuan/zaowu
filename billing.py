"""积分 / 计费模块(JSON 持久化;支付先 mock,后续接真实商户号再替换)。

计费规则:
  充值: 1 元 = POINTS_PER_YUAN 积分
  消耗: 每 100 万 token = TOKENS_PER_MILLION_POINTS 积分
  生成按「实际 token 消耗」扣费: 积分 = tokens / 1_000_000 * TOKENS_PER_MILLION_POINTS

数据模型(单用户 default,预留 user_id 便于以后接登录):
  users[user_id] = {"balance": float, "transactions": [...]}
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

# 数据目录可用 ZW_DATA_DIR 覆盖(容器部署时挂数据卷)
STORE_PATH = Path(os.environ.get("ZW_DATA_DIR", str(Path(__file__).resolve().parent))) / "billing_store.json"

POINTS_PER_YUAN = 10                 # 1 元 = 10 积分
TOKENS_PER_MILLION_POINTS = 500      # 每 100 万 token = 500 积分
MIN_GENERATE_POINTS = 5              # 生成前最低余额(积分)


def pricing() -> dict:
    return {
        "points_per_yuan": POINTS_PER_YUAN,
        "tokens_per_million_points": TOKENS_PER_MILLION_POINTS,
        "min_generate_points": MIN_GENERATE_POINTS,
    }


def tokens_to_points(tokens: int | float) -> float:
    """把 token 数换算成积分(按每百万 500 积分)。"""
    return float(tokens) * TOKENS_PER_MILLION_POINTS / 1_000_000.0


def _load() -> dict:
    if STORE_PATH.is_file():
        try:
            return json.loads(STORE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"users": {}}
    return {"users": {}}


def _save(data: dict) -> None:
    STORE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _user(data: dict, user_id: str) -> dict:
    return data["users"].setdefault(user_id, {"balance": 0.0, "transactions": []})


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def balance(user_id: str = "default") -> float:
    data = _load()
    return _user(data, user_id)["balance"]


def history(user_id: str = "default", limit: int = 50) -> list[dict]:
    data = _load()
    tx = _user(data, user_id)["transactions"]
    return list(reversed(tx[-limit:]))


def recharge(user_id: str, points: float, *, amount: float | None = None, channel: str = "mock") -> float:
    """充值(支付 mock 成功,直接到账)。返回充值后的余额。"""
    if points <= 0:
        raise ValueError("充值积分必须大于 0")
    data = _load()
    u = _user(data, user_id)
    u["balance"] += points
    u["transactions"].append({
        "id": uuid.uuid4().hex[:12],
        "type": "recharge",
        "points": points,
        "amount": amount,
        "channel": channel,
        "at": _now(),
    })
    _save(data)
    return u["balance"]


def consume(user_id: str, points: float, reason: str) -> tuple[float, float]:
    """按实际 token 换算的积分扣费。返回 (实际扣掉, 扣后余额)。

    允许余额为负(欠费):真实成本全额扣,余额不足时记入欠款,
    下次充值时自动先抵扣欠款(见 recharge)。
    """
    points = float(points)
    if points <= 0:
        return 0.0, balance(user_id)
    data = _load()
    u = _user(data, user_id)
    deducted = points
    u["balance"] -= deducted
    u["transactions"].append({
        "id": uuid.uuid4().hex[:12],
        "type": "consume",
        "points": round(-deducted, 4),
        "reason": reason,
        "at": _now(),
    })
    _save(data)
    return deducted, u["balance"]


def debt(user_id: str = "default") -> float:
    """当前欠款(>=0)。余额为负时返回欠款金额,否则返回 0。"""
    return round(max(0.0, -balance(user_id)), 2)


def log_usage(user_id: str, tokens: int, points: float, kind: str) -> None:
    """记录一次模型用量(按日汇总给管理后台)。"""
    data = _load()
    data.setdefault("usage", []).append({
        "user_id": user_id,
        "tokens": int(tokens),
        "points": round(float(points), 4),
        "kind": kind,
        "date": time.strftime("%Y-%m-%d"),
        "at": _now(),
    })
    _save(data)


def usage_summary(days: int = 14) -> dict:
    """按日汇总 token/积分消耗,返回 {'YYYY-MM-DD': {tokens, points}}。"""
    data = _load()
    out: dict[str, dict] = {}
    for r in data.get("usage", []):
        d = str(r.get("date", ""))
        if not d:
            continue
        out.setdefault(d, {"tokens": 0, "points": 0.0})
        out[d]["tokens"] += int(r.get("tokens", 0))
        out[d]["points"] = round(out[d]["points"] + float(r.get("points", 0.0)), 4)
    return dict(sorted(out.items())[-days:])


def all_users() -> list[dict]:
    """管理后台用的用户列表(按累计消费排序)。"""
    data = _load()
    users = []
    for uid, u in data.get("users", {}).items():
        spent = 0.0
        recharged = 0.0
        for t in u.get("transactions", []):
            pts = float(t.get("points", 0) or 0)
            if t.get("type") == "consume":
                spent += -pts
            elif t.get("type") == "recharge" and pts > 0:
                recharged += pts
        bal = float(u.get("balance", 0.0))
        users.append({
            "user_id": uid,
            "balance": round(bal, 2),
            "debt": round(max(0.0, -bal), 2),
            "spent": round(spent, 2),
            "recharged": round(recharged, 2),
        })
    users.sort(key=lambda x: x["spent"], reverse=True)
    return users


def revenue_total() -> float:
    """真实收款总额(按非 mock/refund 的充值流水,单位:积分)。"""
    data = _load()
    total = 0.0
    for u in data.get("users", {}).values():
        for t in u.get("transactions", []):
            if t.get("type") == "recharge" and float(t.get("points", 0) or 0) > 0:
                if str(t.get("channel", "")) not in ("mock", "refund", "test"):
                    total += float(t.get("points", 0) or 0)
    return round(total, 2)
