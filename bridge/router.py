"""One side-effect boundary: rules -> optional constrained intent -> selected tool.

Callers supply session/request IDs. Model classification can never confirm a send.
"""

import re
from . import safety, store, tools
from .context import request_id
from .capabilities import candidates

SEND = re.compile(
    r"^(?:请)?(?:帮我|替我)?(?:给|跟|和)\s*(.+?)\s*(?:发(?:个)?消息|发信息|说|讲)\s*[，,:：]?\s*(?:说|讲)?\s*(.+)$"
)
REMIND = re.compile(
    r"^(?:请)?(?:帮我)?(.{1,30}?)(?:提醒我|提醒一下我|叫我一下|叫我|喊我)\s*[，,:：]?\s*(.+)$"
)
VERB = re.compile(
    r"^(?:请)?(?:帮我|替我)?(?:喊|叫|让|通知|告诉|转告)\s*(?:一下|一声)?\s*"
)


def parse(text):
    q = (text or "").strip()
    if safety.is_cancel(q):
        return "cancel_send", {}
    if safety.is_confirm(q):
        return "confirm_send", {}
    m = REMIND.match(q)
    if m:
        return "set_reminder", dict(time_text=m[1].strip(), content=m[2].strip())
    if re.search(r"^(?:请)?(?:帮我)?(?:取消|删除).*(?:提醒|待办)", q):
        keyword = re.sub(
            r"^(?:请)?(?:帮我)?(?:取消|删除)(?:那个|这个)?(?:提醒|待办)?\s*", "", q
        )
        return "cancel_reminder", dict(keyword=keyword.strip(" ，,：:"))
    m = SEND.match(q)
    if m:
        return "send_qq_message", dict(to=m[1].strip(), text=m[2].strip())
    # A name lookup happens only for an explicit recipient-style command.
    m = VERB.match(q)
    if m:
        rest = q[m.end() :]
        for row in sorted(safety.list_contacts(), key=lambda x: -len(x["name"])):
            key = row["name"].strip(" ，,。：:")
            if key and rest.lower().startswith(key.lower()):
                body = rest[len(key) :].lstrip(" ，,：:")
                if body:
                    return "send_qq_message", dict(to=row["name"], text=body)
    if re.search(r"联系人|好友|名单", q) and re.search(r"有|看|查|多少|列出|几个", q):
        return "list_contacts", dict(query="")
    if re.search(r"提醒|待办", q) and re.search(r"有|看|查|列出|多少|什么", q):
        return "list_reminders", {}
    return None


ARGUMENTS = {
    "send_qq_message": ("to", "text"),
    "set_reminder": ("time_text", "content"),
    "list_contacts": ("query",),
    "list_reminders": (),
    "cancel_reminder": ("keyword",),
    "confirm_send": (),
    "cancel_send": (),
}


def execute(action, args, original):
    if action not in ARGUMENTS or not isinstance(args, dict):
        return "没有识别出可执行的能力，请说明要做什么。"
    if action == "confirm_send" and not safety.is_confirm(original):
        return "请明确回复「确认」或「发吧」，尚未发送。"
    if action == "cancel_send" and not safety.is_cancel(original):
        return "请明确回复「取消」或「算了」。"
    kwargs = {key: args.get(key, "") for key in ARGUMENTS[action]}
    if any(not isinstance(v, str) or len(v) > 10000 for v in kwargs.values()):
        return "工具参数格式不正确，未执行。"
    return getattr(tools, action)(**kwargs)


def route(text, classifier=None):
    q = (text or "").strip()
    if not q:
        return None
    command = parse(q)
    relevant = candidates(q)
    if command is None and classifier is not None and relevant and len(q) <= 500:
        proposed = classifier(q, relevant)
        if proposed:
            action, args = proposed
            allowed = {t for c in relevant for t in c.tools}
            if action in allowed:
                command = action, args
    if command is None:
        return None
    action, args = command
    if action == "confirm_send" and not store.latest():
        return None
    return store.request_once(request_id(), lambda: execute(action, args, q))
