"""Prepare text for TTS without changing the displayed reply.

Unsupported letters are rendered as pronounceable Chinese syllables. Long digit
sequences are read one digit at a time, for example 1234567890. This module only
transforms speech text; it does not change contacts, messages or visible text.
"""

import re

_LETTER = {
    "a": "诶",
    "b": "必",
    "c": "西",
    "d": "迪",
    "e": "伊",
    "f": "艾弗",
    "g": "吉",
    "h": "艾尺",
    "i": "艾",
    "j": "杰",
    "k": "开",
    "l": "艾勒",
    "m": "艾姆",
    "n": "艾恩",
    "o": "哦",
    "p": "屁",
    "q": "扣",
    "r": "啊",
    "s": "艾斯",
    "t": "提",
    "u": "优",
    "v": "维",
    "w": "达不溜",
    "x": "艾克斯",
    "y": "歪",
    "z": "贼",
}
_DIGIT = "零一二三四五六七八九"


def to_speech(text: str) -> str:
    t = text or ""
    # 动作/表情/标签：念出来很出戏，去掉（显示的文字不变）
    t = re.sub(r"[（(][^）)]{0,60}[）)]", "", t)  # （翻白眼） (sigh)
    t = re.sub(r"【[^】]{0,30}】", "", t)  # 【动作】
    t = re.sub(r"\[[^\]]{0,30}\]", "", t)  # [neutral] 之类
    t = re.sub(r"<[^>]{0,30}>", "", t)  # <动作>
    t = re.sub(r"\*{1,2}[^*\n]{0,60}\*{1,2}", "", t)  # *动作* / **加粗**
    t = re.sub(r"[`#>]+", "", t)  # markdown 符号
    # 括号里的长数字（QQ 号）念出来又慢又乱，直接略过；号码仍显示在气泡里
    t = re.sub(r"[（(]\s*\d{4,}\s*[）)]", "", t)
    # ASCII 字母：逐字读
    t = re.sub(
        r"[A-Za-z]+",
        lambda m: "".join(_LETTER.get(c.lower(), c) for c in m.group(0)),
        t,
    )
    # 其余数字：逐位读（避免"二十九亿"）
    t = re.sub(r"\d+", lambda m: "".join(_DIGIT[int(c)] for c in m.group(0)), t)
    # 清掉多余空白
    t = re.sub(r"[ \t]{2,}", " ", t).strip()
    return t
