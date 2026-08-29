"""任务持久化:每个任务一个 JSON 文件,服务器重启后自动恢复未完成任务。

保存时会跳过以 _ 开头的内存字段(线程事件等不可序列化对象)。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
JOBS_DIR = Path(os.environ.get("ZW_DATA_DIR", str(BASE))) / "jobs"


def _path(job_id: str) -> Path:
    return JOBS_DIR / f"{job_id}.json"


def save(job: dict) -> None:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    job["updated_at"] = time.time()
    payload = {k: v for k, v in job.items() if not k.startswith("_")}
    _path(str(job.get("job_id", ""))).write_text(
        json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")


def load_all() -> dict[str, dict]:
    if not JOBS_DIR.is_dir():
        return {}
    out: dict[str, dict] = {}
    for p in JOBS_DIR.glob("*.json"):
        try:
            j = json.loads(p.read_text(encoding="utf-8"))
            if j.get("job_id"):
                out[j["job_id"]] = j
        except Exception:  # noqa: BLE001
            continue
    return out


def delete(job_id: str) -> None:
    try:
        _path(job_id).unlink(missing_ok=True)
    except OSError:
        pass
