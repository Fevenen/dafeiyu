"""tools.py — 工具实现（MCP server 只负责把这里包一层）。

所有对外文字都是给模型看的中文，模型会转述给用户。
每次调用都会记到 pet\\logs\\tool_calls.jsonl，方便核对"模型是不是真调了"。
"""

import functools
import json
import os
import time

from . import safety, settings, store
from .context import session_id, request_id
from .v0_load import reminders

_LOG = str(settings.LOG_DIR / "tool_calls.jsonl")


def _audit(name: str, args: dict, result: str, ok: bool = True) -> None:
    try:
        os.makedirs(os.path.dirname(_LOG), exist_ok=True)
        rec = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "tool": name,
            "args": args,
            "ok": ok,
            "result": (result or "")[:400],
            "pid": os.getpid(),
            "session": session_id(),
            "request_id": request_id(),
        }
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _logged(name: str):
    def deco(fn):
        sig = list(fn.__code__.co_varnames[: fn.__code__.co_argcount])

        @functools.wraps(fn)
        def wrapper(*a, **kw):
            args = dict(zip(sig, a))
            args.update(kw)
            try:
                r = fn(*a, **kw)
            except Exception as e:
                _audit(name, args, "%s: %s" % (type(e).__name__, e), False)
                raise
            _audit(name, args, str(r), True)
            return r

        return wrapper

    return deco


# ---------------- 查联系人 ----------------


def list_contacts(query: str = "") -> str:
    rows = safety.list_contacts(query)
    prefix = ""
    if not rows and query:
        # 模型可能把「QQ联系人」整个当成关键词，别再当过滤条件
        rows = safety.list_contacts("")
        if rows:
            prefix = "没有名字包含「%s」的。" % query
    if not rows:
        return "联系人列表是空的（SnowLuma 或 QQ 没登录）。"
    lines = ["%s（%s）" % (r["name"], r["uid"]) for r in rows]
    return prefix + "联系人共 %d 个：" % len(rows) + "、".join(lines)


# ---------------- 发消息 ----------------


def send_qq_message(to: str, text: str) -> str:
    text = (text or "").strip()
    if not text:
        return "要发的内容是空的，没发。"

    contact, error, candidates = safety.resolve_contact(to)

    if error and not candidates:
        return error

    if candidates and not contact:
        # Selecting a recipient is a separate step from confirming a send.
        store.cancel()
        store.set_dialogue({"kind": "contact_choice", "text": text, "candidates": candidates[:5]})
        names = "、".join(
            "%d. %s" % (i, c["name"]) for i, c in enumerate(candidates[:5], 1)
        )
        return "「%s」匹配到多个人：%s。要发给哪一个？" % (to, names)

    # 唯一确定 → 挂起，等确认（不直接发）
    store.clear_dialogue()
    old = safety.get_pending()
    same = (
        old
        and int(old.get("uid") or 0) == int(contact.user_id)
        and str(old.get("text") or "").strip() == text
    )
    safety.set_pending(contact.user_id, contact.remark or contact.nickname, text)
    if same:
        return "这条已经挂起过了：%s（发给 %s）。确认发送吗？" % (
            text,
            contact.remark or contact.nickname,
        )
    return (
        "准备发给 %s（%s）：%s\n确认发送吗？回复「确认」就发，回复「算了」就取消。"
        % (
            contact.remark or contact.nickname,
            contact.user_id,
            text,
        )
    )


def confirm_send() -> str:
    from .message_service import confirm

    return confirm()


def cancel_send() -> str:
    from .message_service import cancel

    return cancel()


def select_recipient(selection: str) -> str:
    import re

    choice = store.get_dialogue()
    if choice.get("kind") != "contact_choice":
        return "没有待选择的联系人，请重新说要发给谁和内容。"
    rows = choice["candidates"]
    value = selection.strip().strip("。！!，, ")
    match = re.fullmatch(r"第?([1-5一二三四五])(?:个|位)?", value)
    index = (int(match[1]) if match and match[1].isdigit() else "一二三四五".find(match[1]) + 1) if match else 0
    matches = [row for row in rows if value.casefold() == row["name"].casefold()]
    selected = rows[index - 1] if 0 < index <= len(rows) else (matches[0] if len(matches) == 1 else None)
    if selected is None:
        return "请回复候选序号或完整名字；选择联系人还不会发送消息。"
    contact = safety.vault().find_by_id(int(selected["uid"]))
    if contact is None:
        return "联系人缓存已变化，请重新说要发给谁。"
    name = contact.remark or contact.nickname
    safety.set_pending(contact.user_id, name, choice["text"])
    store.clear_dialogue()
    return "准备发给 %s（%s）：%s\n确认发送吗？回复「确认」就发，回复「算了」就取消。" % (name, contact.user_id, choice["text"])


# ---------------- 提醒 ----------------


def set_reminder(time_text: str, content: str) -> str:
    content = (content or "").strip()
    if not content:
        return "要提醒你做什么？没听清。"

    dt, rest = safety.parse_time(time_text)
    if dt is None:
        return "时间没听懂：「%s」。说具体点，例如「10分钟后」「明天早上8点」。" % (
            time_text or ""
        )

    what = (rest or "").strip(" ，,。、") or content
    reminders().add(what, dt)
    return "好，%s提醒你：%s" % (safety.human_time(dt), what)


def list_reminders() -> str:
    items = reminders().pending()
    if not items:
        return "现在没有待办提醒。"
    lines = []
    for x in items:
        delivery = ""
        if x.get("attempts", 0):
            delivery = " [QQ:%s / 语音入队:%s]" % (x.get("qq"), x.get("pet"))
        lines.append(
            "%s — %s%s"
            % (x.get("due", "")[:16].replace("T", " "), x.get("text", ""), delivery)
        )
    return "待办 %d 条：\n" % len(items) + "\n".join(lines)


def cancel_reminder(keyword: str = "") -> str:
    keyword = (keyword or "").strip()
    items = reminders().pending()
    if not items:
        return "没有待办可取消。"
    if not keyword:
        return "要取消哪一条？现在的待办：\n" + "\n".join(
            "%s — %s" % (x.get("due", "")[:16].replace("T", " "), x.get("text", ""))
            for x in items
        )
    hit = [x for x in items if keyword in x.get("text", "")]
    if not hit:
        return "没找到包含「%s」的待办。" % keyword
    if len(hit) > 1:
        return "有 %d 条都包含「%s」，说细一点：\n" % (len(hit), keyword) + "\n".join(
            "%s — %s" % (x.get("due", "")[:16].replace("T", " "), x.get("text", ""))
            for x in hit
        )
    if not reminders().remove(hit[0]["id"]):
        return "该提醒正在投递，请稍后再取消。"
    return "取消了一条：%s" % hit[0].get("text", "")


def recent_actions(limit: int = 3) -> str:
    from . import store

    return json.dumps(store.recent(limit), ensure_ascii=False)


# 给所有对外工具套一层调用记录（写在模块末尾，保证内部互相调用也能记上）
for _n in (
    "list_contacts",
    "send_qq_message",
    "set_reminder",
    "list_reminders",
    "cancel_reminder",
    "confirm_send",
    "cancel_send",
    "recent_actions",
    "select_recipient",
):
    globals()[_n] = _logged(_n)(globals()[_n])
