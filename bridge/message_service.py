"""Single atomic confirmation service shared by MCP, proxy and desktop input."""

import time
from . import store, safety
from .context import user_text
from .v0_load import sender
from ._v0.config import int_cfg


def confirm():
    original = user_text()
    if original is not None and not safety.is_confirm(original):
        return "请明确回复「确认」或「发吧」，这句话没有作为发送确认。"
    item = store.claim(int_cfg("CONFIRM_TIMEOUT", 300))
    if not item:
        last = store.latest()
        if last and time.time() - last["updated"] < 300:
            if last["status"] in ("sending", "unknown"):
                return "这条消息正在发送或结果未知，请先核对 QQ，系统不会自动重复发送。"
            if last["status"] == "sent":
                return last["result"]
            if last["status"] == "failed":
                return "上次发送失败，消息内容已保留。请重新提出发送请求，再确认。"
        return "没有待确认的消息。"
    try:
        res = sender().send_private(item["uid"], item["text"], action_id=item["id"])
        if res.get("dry_run"):
            status, result = (
                "dry_run",
                "模拟发送完成（未发送真实消息）：%s：%s" % (item["name"], item["text"]),
            )
        elif res.get("retcode") == 0:
            status, result = "sent", "已发送给 %s：%s" % (item["name"], item["text"])
        elif res.get("retcode") == -2:
            status, result = (
                "unknown",
                "发送结果未知：请求超时或连接中断，请先核对 QQ；不会自动重发。",
            )
        else:
            status, result = (
                "failed",
                "发送失败：%s。消息内容已保留。"
                % (res.get("error") or res.get("wording") or res.get("retcode")),
            )
    except Exception:
        status, result = "unknown", "发送结果未知，请先核对 QQ；不会自动重发。"
    store.finish(item["id"], status, result)
    return result


def cancel():
    return "好，不发了。" if store.cancel() else "没有待确认的消息。"
