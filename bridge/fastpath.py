"""fastpath.py — 常见句式的确定性处理（兜底，不让模型自由发挥）。

模型有时候不调工具、直接编"已经发了"。这里用规则兜住最常见的两种说法：
  · 给X发消息说Y / 跟X说Y
  · X分钟后提醒我Y / X点叫我Y
命中就走工具；没命中返回 handled=False，交给模型。
"""

import re

from . import safety, tools

_SEND = re.compile(
    r"^(?:帮我)?(?:给|跟|和)\s*(?P<to>.+?)\s*"
    r"(?:发(?:个)?消息|发信息|说|讲)\s*[，,:：]?\s*(?:说|讲)?\s*(?P<text>.+)$"
)

_REMIND = re.compile(
    r"^(?:帮我)?(?P<time>.{1,20}?)(?:后|以后|之后)?\s*"
    r"(?:提醒我|提醒一下我|叫我一下|叫我|喊我一下|喊我)\s*[，,:：]?\s*(?P<what>.+)$"
)

# "喊feven明天来找我" / "叫Z晚上吃饭" / "让泡芙把文件发我"
_CALL = re.compile(
    r"^(?:帮我)?(?:喊|叫|让)\s*(?P<to>[^\s，,。！!？?]{1,20})\s*[，,:：]?\s*(?P<text>.+)$"
)

_PRONOUNS = {"他", "她", "它", "他们", "她们", "大家", "所有人", "你", "我"}


def try_handle(text: str):
    """返回 (handled, reply)。handled=False 时交给模型。"""
    t = (text or "").strip()
    if not t:
        return False, ""

    m = _REMIND.search(t)
    if m:
        time_text = m.group("time").strip()
        what = m.group("what").strip()
        if time_text and what:
            return True, tools.set_reminder(time_text, what)

    m = _SEND.search(t)
    if m:
        to = m.group("to").strip()
        body = m.group("text").strip()
        # "发消息喊他回家" → 真正要发的是"回家"，不是"喊他回家"
        body = re.sub(
            r"^(?:喊他|喊她|叫他|叫她|告诉他|告诉她|让他|让她|跟他说|跟她说|说|讲)\s*",
            "",
            body,
        ).strip()
        if to and body:
            return True, tools.send_qq_message(to, body)

    # 喊X做什么 / 叫X做什么 / 让X做什么（等价于给 X 发消息）
    # 名字长度不定，所以用「已知联系人」做前缀匹配，不靠正则猜
    m = re.match(r"^(?:帮我)?(?:喊|叫|让)\s*", t)
    if m:
        rest = t[m.end():].lstrip(" ，,：:")
        try:
            names = [c["name"] for c in safety.list_contacts("")]
        except Exception:
            names = []
        # 长的名字优先，避免 "Z" 抢了 "Z，"；比较时忽略名字里的标点（"Z，" → "Z"）
        pairs = [(n, n.strip(" ，,。、：:")) for n in names if n]
        for full, key in sorted(pairs, key=lambda x: len(x[1]), reverse=True):
            if key and rest.lower().startswith(key.lower()):
                body = rest[len(key):].strip(" ，,：:、")
                if body:
                    return True, tools.send_qq_message(full, body)

    # 查联系人：明确提到 联系人/好友/名单，且带 有/看/查/多少/列出
    if re.search(r"(联系人|好友|名单)", t) and re.search(r"(有|看|查|多少|列出|几个)", t):
        return True, tools.list_contacts("")

    # 查提醒：提到 提醒/待办，且带 有/看/查/列出/多少（"提醒我"已在上面的分支处理）
    if re.search(r"(提醒|待办)", t) and re.search(r"(有|看|查|列出|多少|什么)", t):
        return True, tools.list_reminders()

    return False, ""
