# name_match.py — 名字匹配的唯一实现
#
# 之前这套逻辑散在几个地方：
#   vault._norm / nameguard / fastpath
# 现在统一到这里，各处只调用，不再各写一份。
#
# 两个归一化级别：
#   base()  —— 全角转半角、小写、去空格和标点。名字本来就准确时用它（QQ）
#   ocr()   —— base + 0→o / 1→l / i→l。给 OCR 读出来的文本用
#             注意 i→l 会让 "li"/"il" 撞车，所以只在 OCR 场景开。

import re

_PUNCT = re.compile(r"[\s\^_~\-\.\,\'\"`\*\#\@\!\:\;\|\/\\\?（）\(\)\+]")
_NON_WORD = re.compile(r"^[0-9a-z\u4e00-\u9fff]")


def base(s: str) -> str:
    """全角转半角 + 小写 + 去空格/标点。"""
    s = str(s or "").strip().lower()
    out = []
    for ch in s:
        code = ord(ch)
        out.append(chr(code - 0xFEE0) if 0xFF01 <= code <= 0xFF5E else ch)
    return _PUNCT.sub("", "".join(out))


def ocr(s: str) -> str:
    """OCR 场景：在 base 基础上再处理易混字符。"""
    return base(s).replace("0", "o").replace("1", "l").replace("i", "l")


# ---------------- 群聊识别 ----------------

_GROUP_WORDS = re.compile(r"群聊|交流群|互助群|通知群|工作群|家族群|同乡群|部门群|讨论组")


def is_group_like(s: str) -> bool:
    """看起来像群聊的名字（群关键词 / 末尾人数 / 第二段是人数）。"""
    t = (s or "").strip()
    if not t:
        return False
    if _GROUP_WORDS.search(t):
        return True
    seg = re.split(r"\s+", t, maxsplit=1)[0]
    if re.search(r"[\(（]\d+[\)）]$", seg):
        return True
    parts = re.split(r"\s+", t)
    if len(parts) >= 2 and re.match(r"^[\(（]\d+[\)）]$", parts[1]):
        return True
    return False


# ---------------- 严格比对 ----------------

def _strict(display: str, hint: str, norm) -> bool:
    """hint 能不能唯一确定 display。"""
    display = (display or "").strip()
    hint = (hint or "").strip()
    if len(display) < 2 or not hint:
        return False
    if is_group_like(display):
        return False

    nd, nh = norm(display), norm(hint)
    if not nd or not nh:
        return False
    if nd == nh:
        return True

    # hint 是前缀，且后面不能紧跟名字字符（防 张三 → 张三丰）
    if nd.startswith(nh):
        tail = nd[len(nh):]
        if tail and _NON_WORD.match(tail[0]):
            return False
        return True
    return False


def strict_ok(display: str, hint: str) -> bool:
    """QQ 侧用：自动发送前的闸门（不做 OCR 字符映射）。"""
    return _strict(display, hint, base)


# ---------------- 候选打分 ----------------

def score(candidate: str, query: str) -> tuple:
    """给一个候选名字打分，返回 (分数, 理由)。

    和 QQ 侧 vault._score 同一套思路：完全一致 100、前缀 85、包含 75、
    拼音 70/60、模糊匹配 >=80 相似度时打 0.8 折。
    >=50 才算候选，>=90 才允许自动发送。
    """
    c = base(candidate)
    q = base(query)
    if not c or not q:
        return 0, ""

    if c == q:
        return 100, "完全一致"
    if c.startswith(q):
        return 85, "前缀匹配"
    if q in c:
        return 75, "包含"

    # OCR 容易把 0/1/i/l 认混（"zz10rz" 可能是 "zzlorz"），再比一次
    alt = ocr(candidate)
    if alt and alt != c:
        if alt == q:
            return 100, "完全一致（OCR 归一）"
        if alt.startswith(q):
            return 85, "前缀匹配（OCR 归一）"
        if q in alt:
            return 75, "包含（OCR 归一）"

    try:
        from pypinyin import lazy_pinyin
        cp = "".join(lazy_pinyin(candidate)).lower()
        ci = "".join(p[0] for p in lazy_pinyin(candidate)).lower()
        if q == cp:
            return 70, "拼音全拼"
        if q == ci:
            return 60, "拼音首字母"
    except Exception:
        pass

    try:
        from rapidfuzz import fuzz
        r = fuzz.ratio(q, c)
        if r >= 80:
            return int(r * 0.8), "模糊匹配"
    except Exception:
        pass

    return 0, ""


def rank(candidates, query: str) -> list:
    """给一批候选名字打分排序，返回 [(分数, 理由, 名字)]，过滤 <50、去重。"""
    out, seen = [], set()
    for cand in candidates or []:
        name = (cand or "").strip()
        if not name or name in seen:
            continue
        s, reason = score(name, query)
        if s >= 50:
            seen.add(name)
            out.append((s, reason, name))
    out.sort(key=lambda x: -x[0])
    return out
