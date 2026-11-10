"""Independent notification channels, leases and conservative timeout handling."""

import json
import urllib.error
import urllib.request
from . import settings
from .net import urlopen
from .v0_load import reminders, sender


def notify_pet(text, rid):
    req = urllib.request.Request(
        settings.PET_API + "/api/say",
        data=json.dumps(
            {
                "text": "提醒时间到了：" + text,
                "enqueue": True,
                "job_id": "reminder:" + rid,
            }
        ).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(req, timeout=10) as response:
            data = json.load(response)
        return "sent" if data.get("ok") and data.get("clients", 0) > 0 else "pending"
    except urllib.error.HTTPError:
        return "pending"
    except (TimeoutError, urllib.error.URLError):
        return "unknown"


def deliver(item):
    service = reminders()
    if not service.claim(item["id"]):
        return
    try:
        if item["qq"] == "pending":
            try:
                uid = (sender().get_login_info().get("data") or {}).get("user_id")
                if uid:
                    # Persist before I/O: a crash must not blindly repeat a send.
                    service.delivery(item["id"], "qq", "unknown")
                    res = sender().send_private(
                        int(uid),
                        "⏰ 提醒：" + item["text"],
                        action_id="reminder:" + item["id"],
                    )
                    status = (
                        "sent"
                        if res.get("retcode") == 0 and not res.get("dry_run")
                        else ("unknown" if res.get("retcode") == -2 else "pending")
                    )
                    service.delivery(item["id"], "qq", status)
            except Exception:
                pass
        if item["pet"] == "pending":
            service.delivery(item["id"], "pet", "unknown")
            service.delivery(item["id"], "pet", notify_pet(item["text"], item["id"]))
    finally:
        service.release(item["id"])
