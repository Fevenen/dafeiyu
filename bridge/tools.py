"""tools.py — 工具实现（MCP server 只负责把这里包一层）。

所有对外文字都是给模型看的中文，模型会转述给用户。
每次调用都会记到 pet\\logs\\tool_calls.jsonl，方便核对"模型是不是真调了"。
"""

import functools
import json
import os
import time

from . import safety
from .v0_load import reminders, sender

_LOG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs", "tool_calls.jsonl"
)


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
        names = "、".join("%s（%d 分）" % (c["name"], c["score"]) for c in candidates[:5])
        return "「%s」匹配到多个人：%s。要发给哪一个？" % (to, names)

    # 唯一确定 → 挂起，等确认（不直接发）
    old = safety.get_pending()
    same = (
        old
        and int(old.get("uid") or 0) == int(contact.user_id)
        and str(old.get("text") or "").strip() == text
    )
    safety.set_pending(contact.user_id, contact.remark or contact.nickname, text)
    if same:
        return "这条已经挂起过了：%s（发给 %s）。确认发送吗？" % (text, contact.remark or contact.nickname)
    return "准备发给 %s（%s）：%s\n确认发送吗？回复「确认」就发，回复「算了」就取消。" % (
        contact.remark or contact.nickname,
        contact.user_id,
        text,
    )


_LAST_SEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bridge", "state", "last_send.json")


def _remember_send(uid: int, name: str, text: str) -> None:
    try:
        os.makedirs(os.path.dirname(_LAST_SEND), exist_ok=True)
        with open(_LAST_SEND, "w", encoding="utf-8") as f:
            json.dump({"ts": time.time(), "uid": uid, "name": name, "text": text}, f, ensure_ascii=False)
    except Exception:
        pass


def _recent_send(seconds: float = 120.0):
    try:
        with open(_LAST_SEND, encoding="utf-8") as f:
            d = json.load(f)
        if time.time() - float(d.get("ts", 0)) <= seconds:
            return d
    except Exception:
        pass
    return None


def do_send(uid: int, text: str) -> str:
    """真正发送（只由确认闸门调用，不给模型当工具）。"""
    try:
        res = sender().send_private(int(uid), text)
    except Exception as e:
        return "发送失败：%s: %s" % (type(e).__name__, e)
    if res.get("retcode") == 0:
        return "已发送 ✓"
    return "发送失败：%s" % (res.get("error") or res.get("wording") or res.get("retcode"))


def confirm_send() -> str:
    """确认发送挂起的那条消息（给 DSH 的模型当工具用）。

    幂等：没有待确认但两分钟内刚发过 → 返回"已经发过了"，而不是报错。
    这样"代码路由 + 模型"同时处理"确认"时会得到一致结果。
    """
    pending = safety.get_pending()
    if not pending:
        last = _recent_send(120)
        if last:
            return "刚才已经发过了（%s）：%s" % (last.get("name") or last.get("uid"), last.get("text") or "")
        return "没有待确认的消息。"
    uid = int(pending.get("uid") or 0)
    content = str(pending.get("text") or "")
    name = pending.get("name") or ""
    safety.clear_pending()
    if not uid or not content:
        return "那条待发的消息丢了，重新说要发什么吧。"
    result = do_send(uid, content)
    if result.startswith("已发送"):
        _remember_send(uid, name, content)
        return "已发送给 %s：" % name + content
    return result


def cancel_send() -> str:
    """取消挂起的那条消息。"""
    pending = safety.get_pending()
    if not pending:
        return "没有待确认的消息。"
    safety.clear_pending()
    return "好，不发了。"


# ---------------- 提醒 ----------------

def set_reminder(time_text: str, content: str) -> str:
    content = (content or "").strip()
    if not content:
        return "要提醒你做什么？没听清。"

    dt, rest = safety.parse_time(time_text)
    if dt is None:
        return "时间没听懂：「%s」。说具体点，例如「10分钟后」「明天早上8点」。" % (time_text or "")

    what = (rest or "").strip(" ，,。、") or content
    item = reminders().add(what, dt)
    return "好，%s提醒你：%s" % (safety.human_time(dt), what)


def list_reminders() -> str:
    items = reminders().pending()
    if not items:
        return "现在没有待办提醒。"
    lines = []
    for x in items:
        lines.append("%s — %s" % (x.get("due", "")[:16].replace("T", " "), x.get("text", "")))
    return "待办 %d 条：\n" % len(items) + "\n".join(lines)


def cancel_reminder(keyword: str = "") -> str:
    keyword = (keyword or "").strip()
    items = reminders().pending()
    if not items:
        return "没有待办可取消。"
    if not keyword:
        return "要取消哪一条？现在的待办：\n" + "\n".join(
            "%s — %s" % (x.get("due", "")[:16].replace("T", " "), x.get("text", "")) for x in items
        )
    hit = [x for x in items if keyword in x.get("text", "")]
    if not hit:
        return "没找到包含「%s」的待办。" % keyword
    if len(hit) > 1:
        return "有 %d 条都包含「%s」，说细一点：\n" % (len(hit), keyword) + "\n".join(
            "%s — %s" % (x.get("due", "")[:16].replace("T", " "), x.get("text", "")) for x in hit
        )
    reminders().remove(hit[0]["id"])
    return "取消了一条：%s" % hit[0].get("text", "")


def recent_actions(limit: int = 3) -> str:
    """最近几条"代码已经替用户执行过"的动作（路由层写的日志）。

    模型在回答前可以查一下，避免重复执行或编造。
    """
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "bridge",
        "state",
        "router_log.jsonl",
    )
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()[-max(1, int(limit or 3)):]
    except Exception:
        return "最近没有代码执行记录。"
    if not lines:
        return "最近没有代码执行记录。"
    out = []
    for line in lines:
        try:
            r = json.loads(line)
        except Exception:
            continue
        out.append(
            "%s [%s] 用户说「%s」→ %s"
            % (r.get("ts", ""), r.get("action", ""), r.get("prompt", ""), r.get("result", ""))
        )
    return "最近 %d 条代码执行记录：\n" % len(out) + "\n".join(out)


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
):
    globals()[_n] = _logged(_n)(globals()[_n])
