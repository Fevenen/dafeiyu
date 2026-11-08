# sender.py — OneBot v11 HTTP 封装（NapCat / SnowLuma / Lagrange 通用）
import json
import os
import time
import uuid
from collections import deque

import requests

from . import config
from .config import LOG_DIR

os.makedirs(LOG_DIR, exist_ok=True)

ACTIONS_LOG = os.path.join(LOG_DIR, "actions.jsonl")
_sent_ids = None
_sent_ids_mtime = 0
_send_times = deque()  # 发送时间戳队列，用于每分钟限流


def _api(action: str, params: dict, timeout: int = 15) -> dict:
    url = f"{config.onebot_url()}/{action}"
    r = requests.post(
        url,
        params={"access_token": config.onebot_token()},
        json=params,
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()


def get_login_info() -> dict:
    return _api("get_login_info", {})


def get_version() -> dict:
    """OneBot 标准接口：返回 app_name/app_version，用来识别后端类型。"""
    return _api("get_version", {})


def get_friend_list() -> dict:
    return _api("get_friend_list", {})


def get_group_list() -> dict:
    return _api("get_group_list", {})


def _load_sent_ids() -> set:
    """把历史发送记录读进内存（幂等检查用），文件变了自动重读。"""
    global _sent_ids, _sent_ids_mtime
    try:
        mtime = os.path.getmtime(ACTIONS_LOG)
    except OSError:
        mtime = 0
    if _sent_ids is not None and mtime == _sent_ids_mtime:
        return _sent_ids
    ids = set()
    if os.path.exists(ACTIONS_LOG):
        with open(ACTIONS_LOG, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if rec.get("status") == "sent":
                        ids.add(rec["action_id"])
                except json.JSONDecodeError:
                    continue
    _sent_ids, _sent_ids_mtime = ids, mtime
    return ids


def _log_action(rec: dict):
    with open(ACTIONS_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _check_rate_limit() -> tuple[bool, str]:
    limit = config.int_cfg("MAX_SEND_PER_MINUTE", 3)
    now = time.time()
    while _send_times and now - _send_times[0] > 60:
        _send_times.popleft()
    if len(_send_times) >= limit:
        return False, f"发送太频繁（每分钟最多 {limit} 条），请稍后再试"
    return True, ""


def send_private(user_id: int, text: str, action_id: str | None = None) -> dict:
    """发送私聊消息。幂等：同一个 action_id 只发一次。"""
    action_id = action_id or uuid.uuid4().hex
    sent = _load_sent_ids()
    if action_id in sent:
        return {"status": "ok", "retcode": 0, "data": {"message_id": 0},
                "note": "already_sent"}

    ok, why = _check_rate_limit()
    if not ok:
        return {"status": "failed", "retcode": -1, "error": why}

    text = (text or "").strip()
    if not text:
        return {"status": "failed", "retcode": -1, "error": "消息内容为空"}

    # dry-run：只记录，不真发
    if config.config.get("DRY_RUN") == "1":
        rec = {"action_id": action_id, "ts": time.time(), "user_id": user_id,
               "text": text, "status": "sent", "retcode": 0, "dry_run": True}
        _log_action(rec)
        return {"status": "ok", "retcode": 0,
                "data": {"message_id": 0}, "dry_run": True}

    _send_times.append(time.time())
    try:
        res = _api("send_private_msg", {"user_id": int(user_id), "message": text},
                   timeout=20)
    except Exception as e:
        _log_action({"action_id": action_id, "ts": time.time(), "user_id": user_id,
                     "text": text, "status": "failed", "retcode": -2,
                     "error": str(e)})
        return {"status": "failed", "retcode": -2, "error": str(e)}

    retcode = res.get("retcode", -1)
    status = "sent" if retcode == 0 else "failed"
    _log_action({"action_id": action_id, "ts": time.time(), "user_id": user_id,
                 "text": text, "status": status, "retcode": retcode})
    return res
