"""One side-effect boundary: rules -> optional constrained intent -> selected tool.

Callers supply session/request IDs. Model classification can never confirm a send.
"""

import re
from . import safety, store, tools
from .context import request_id
from .capabilities import REGISTRY, command_text
from .screen_context import wants_screen

SEND = re.compile(
    r"^(?:请)?(?:帮我|替我)?(?:给|跟|和)\s*(.+?)\s*(?:发(?:个)?消息|发信息|说|讲)\s*[，,:：]?\s*(?:说|讲)?\s*(.+)$"
)
REMIND = re.compile(
    r"^(?:请)?(?:帮我)?(.{1,30}?)(?:提醒我|提醒一下我|叫我一下|叫我|喊我)\s*[，,:：]?\s*(.+)$"
)
VERB = re.compile(
    r"^(?:请)?(?:帮我|替我)?(?:喊|叫|让|通知|告诉|转告)\s*(?:一下|一声|下)?\s*"
)


def parse(text):
    q = (text or "").strip()
    if safety.is_cancel(q):
        return "cancel_send", {}
    if safety.is_confirm(q):
        return "confirm_send", {}
    q = command_text(q)
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
        if m[1].strip() in ("我", "你", "自己"):
            return None
        return "send_qq_message", dict(to=m[1].strip(), text=m[2].strip())
    # A name lookup happens only for an explicit recipient-style command.
    m = VERB.match(q)
    if m:
        rest = q[m.end() :]
        if rest.startswith(("我", "你", "什么", "啥", "他", "她")):
            return None
        wake = re.fullmatch(r"(.{1,30}?)\s*((?:起(?:个)?床|(?:去)?睡觉|吃饭)[\s\S]*)", rest)
        if wake:
            return "send_qq_message", dict(to=wake[1].strip(), text=wake[2].strip())
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


def route(text, classifier=None, decision_sink=None, allow_screen=True, recent_messages=None):
    if decision_sink is not None:
        decision_sink(False)
    q = (text or "").strip()
    if not q:
        return None
    cached = store.cached_request(request_id())
    if cached is not None:
        return cached
    normalized = command_text(q)
    dialogue = store.get_dialogue()
    if dialogue.get("kind") == "contact_choice" and safety.is_confirm(q):
        return "请先选联系人，再确认消息；目前还没有发送。"
    if dialogue.get("kind") == "contact_choice" and (
        re.fullmatch(r"第?[1-5一二三四五](?:个|位)?[。！!]?", q)
        or any(q.casefold() == row["name"].casefold() for row in dialogue["candidates"])
    ):
        return store.request_once(request_id(), lambda: tools.select_recipient(q))
    if re.fullmatch(r"第[1-9一二三四五六七八九](?:个|位)[。！!]?", q):
        return "没有有效的联系人候选，请重新说要发给谁和内容。"
    delayed = re.match(r"^(?:等下|等会儿?|一会儿?|待会儿?|稍后)\s*", normalized)
    if delayed:
        later = parse(normalized[delayed.end():])
        if later and later[0] == "send_qq_message":
            def ask_time():
                store.cancel()
                store.set_dialogue({"kind": "reminder_time", **later[1]})
                return "多久后？我可以定时提醒你去喊；如果要现在发QQ，请回复「现在」。"
            return store.request_once(request_id(), ask_time)
    if dialogue.get("kind") == "reminder_time":
        if q.strip("。！! ") in ("现在", "现在发", "现在就发"):
            return store.request_once(request_id(), lambda: tools.send_qq_message(dialogue["to"], dialogue["text"]))
        dt, _ = safety.parse_time(q)
        if dt is not None:
            def remind():
                result = tools.set_reminder(q, "通过QQ喊%s：%s" % (dialogue["to"], dialogue["text"]))
                store.clear_dialogue()
                return result
            return store.request_once(request_id(), remind)
    command = parse(q)
    if command is None and re.fullmatch(r"(?:喊|叫|通知)(?:一下|一声|下)?(?:他|她)(?:一下|一声)?[啊呀吧呗。！!]*", normalized):
        for item in reversed((recent_messages or [])[:-1]):
            if item.get("role") != "user":
                continue
            value = item.get("content", "")
            if isinstance(value, list):
                value = "".join(part.get("text", "") for part in value if isinstance(part, dict) and part.get("type") == "text")
            previous = parse(value) if isinstance(value, str) else None
            if previous and previous[0] == "send_qq_message":
                command = previous
            break
        if command is None and classifier is None:
            return "你指哪位QQ好友？请说名字和要发的内容。"
    if command is None and allow_screen and wants_screen(q):
        if decision_sink is not None:
            decision_sink(True)
        return None
    if command is None and classifier is not None:
        # Every unmatched turn reaches semantics, including chat and unfamiliar phrasing.
        catalogue = [cap for cap in REGISTRY if cap.name != 'screen' or allow_screen]
        try:
            proposed = classifier(q, catalogue)
        except Exception:
            proposed = None
        if not proposed:
            return "这次意图判断暂时失败，没有执行操作，请重试。"
        try:
            action, args = proposed
            if (not isinstance(action, str) or not isinstance(args, dict)
                    or any(not isinstance(value, str) or len(value) > 10000 for value in args.values())):
                raise ValueError('Invalid arguments')
        except (TypeError, ValueError):
            return "意图结果格式不正确，没有执行操作，请重试。"
        if action in ('confirm_send', 'cancel_send'):
            return "请明确回复「确认」或「取消」，意图模型不能代你确认或取消消息。"
        if action == 'chat' and args == {}:
            return None
        if action == 'clarify':
            question = {'recipient': '要发给哪位QQ好友？请说名字。',
                        'content': '要发什么内容？',
                        'time': '具体多久后或几点？定时提醒会提醒你，不会自动给好友发QQ。',
                        'intent': '请说清楚这轮要做的一件事，以及对象和内容。'}
            return question.get(args.get('missing'), question['intent'])
        if action == 'observe_screen' and args == {} and allow_screen:
            if decision_sink is not None:
                decision_sink(True)
            return None
        allowed = {name for cap in catalogue for name in cap.tools} - {'confirm_send', 'cancel_send'}
        if action not in allowed or set(args) - set(ARGUMENTS[action]):
            return "意图结果不在当前能力范围内，没有执行操作。"
        if action == 'send_qq_message':
            if not args.get('to'):
                return '要发给哪位QQ好友？请说名字。'
            if not args.get('text'):
                return '要给这位好友发什么内容？'
        if action == 'set_reminder' and not args.get('time_text'):
            return '具体多久后或几点提醒你？'
        if action == 'set_reminder' and args['time_text'] not in q:
            return '请在本轮说出具体提醒时间，我不会猜测时间。'
        command = action, args
    if command is None:
        return None
    action, args = command
    if action == "confirm_send" and not store.latest():
        return None
    return store.request_once(request_id(), lambda: execute(action, args, q))
