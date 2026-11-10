# when.py — 把中文时间说法解析成 datetime
#
# 支持：
#   10分钟后 / 半小时后 / 2小时后 / 3天后
#   今天/明天/后天 + 上午|下午|晚上|中午|凌晨 + 8点 / 8:30 / 8点半
#   只说"8点"——过了今天就顺延到明天
#
# 解析成功返回 (datetime, 去掉时间部分后的剩余文本)

import re
from datetime import datetime, timedelta

_CN_NUM = {
    "零": 0,
    "一": 1,
    "两": 2,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "十一": 11,
    "十二": 12,
}


def _num(s: str, default=None):
    s = (s or "").strip()
    if not s:
        return default
    if s.isdigit():
        return int(s)
    return _CN_NUM.get(s, default)


_REL = re.compile(
    r"(半\s*个?\s*小时|(\d+|[一二两三四五六七八九十]+)\s*(?:个)?\s*(分钟|分|小时|钟头|天))\s*(?:之后|以后|后)?"
)
_DAY = re.compile(r"(今天|今晚|今早|明天|明早|明晚|后天|大后天)")
# 这周六 / 下周三 / 周六 / 礼拜天 / 下下周一
_WEEK = re.compile(r"(下下|下|这|本)?(?:个)?(?:周|星期|礼拜)([一二三四五六日天])")
_CLOCK = re.compile(
    r"(凌晨|早上|早晨|上午|中午|下午|傍晚|晚上)?\s*"
    r"(\d{1,2}|[一二两三四五六七八九十]+)\s*(?:[:：]\s*(\d{1,2})|点\s*(半|\d{1,2})?)"
)

_WEEKDAY = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 7, "天": 7}


def _weekday_offset(prefix: str, wd: str, now: datetime) -> int:
    """把「这周六 / 下周三」换算成距今天数。"""
    target = _WEEKDAY[wd]
    today = now.isoweekday()
    delta = (target - today) % 7
    if prefix in ("下", "下个"):
        delta += 7 if delta else 7
    elif prefix == "下下":
        delta += 14 if delta else 14
    return delta


def parse_when(text: str, now: datetime = None):
    """返回 (datetime, 剩余文本)；解析不出来返回 (None, 原文)。"""
    if not text:
        return None, text

    now = now or datetime.now()
    text = text.strip()

    # ---------- 相对时间 ----------
    m = _REL.search(text)
    if m:
        unit = m.group(3)
        raw = m.group(1)
        if raw.startswith("半"):
            delta = timedelta(minutes=30)
        else:
            n = _num(m.group(2), 1)
            if unit in ("分钟", "分"):
                delta = timedelta(minutes=n)
            elif unit in ("小时", "钟头"):
                delta = timedelta(hours=n)
            else:
                delta = timedelta(days=n)
        rest = (text[: m.start()] + text[m.end() :]).strip()
        return now + delta, rest

    # ---------- 绝对时间 ----------
    day_m = _DAY.search(text)
    day_offset = None
    if day_m:
        word = day_m.group(1)
        day_offset = {
            "今天": 0,
            "今晚": 0,
            "今早": 0,
            "明天": 1,
            "明早": 1,
            "明晚": 1,
            "后天": 2,
            "大后天": 3,
        }[word]

    # 这周六 / 下周三 / 周六
    week_m = _WEEK.search(text)
    if week_m:
        day_offset = _weekday_offset(week_m.group(1) or "", week_m.group(2), now)

    clock_m = _CLOCK.search(text)
    if not clock_m:
        # 只有"明天"没有具体钟点 → 不算可解析
        return None, text

    period = clock_m.group(1) or ""
    hour = _num(clock_m.group(2))
    if hour is None:
        return None, text
    minute = 0
    if clock_m.group(3):
        minute = _num(clock_m.group(3), 0)
    elif clock_m.group(4):
        minute = 30 if clock_m.group(4) == "半" else _num(clock_m.group(4), 0)

    # 上午/下午修正
    if period in ("下午", "傍晚", "晚上") and hour < 12:
        hour += 12
    elif period == "中午" and hour < 11:
        hour += 12
    elif period in ("凌晨", "早上", "早晨", "上午") and hour == 12:
        hour = 0
    elif not period and day_m and day_m.group(1) in ("今晚", "明晚") and hour < 12:
        # "今晚8点" —— 晚上的信息被"今"吃掉了，这里补回来
        hour += 12

    hour = max(0, min(23, hour))
    minute = max(0, min(59, minute))

    base = (now + timedelta(days=day_offset or 0)).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )

    # 没写哪一天、且时间已过 → 顺延到明天
    if day_offset is None and base <= now:
        base += timedelta(days=1)
    # 写了星期但今天这个时间已经过了 → 顺延到下周同一天
    elif week_m and base <= now:
        base += timedelta(days=7)

    # 把命中的片段从原文里去掉（星期、日期、钟点都要去掉）
    cut = [m.span() for m in (week_m, day_m, clock_m) if m]
    rest = text
    for a, b in sorted(cut, reverse=True):
        rest = rest[:a] + rest[b:]
    rest = re.sub(r"\s+", " ", rest).strip(" ，,。、")

    return base, rest


def human(dt: datetime, now: datetime = None) -> str:
    """给人看的相对时间：今天 20:00（2 小时后）。"""
    now = now or datetime.now()
    delta = dt - now
    secs = delta.total_seconds()
    # 四舍五入到整分：「10 分钟后」算出来常是 9.99 分钟，不该显示成 9
    mins = int(round(secs / 60.0)) if secs > 0 else int(secs // 60)

    if mins < 0:
        return dt.strftime("%m-%d %H:%M") + "（已过期）"
    if mins < 60:
        return f"{mins} 分钟后"
    if mins < 60 * 24 and dt.date() == now.date():
        return f"今天 {dt.strftime('%H:%M')}（{mins // 60} 小时后）"
    if (dt.date() - now.date()).days == 1:
        return f"明天 {dt.strftime('%H:%M')}"
    if (dt.date() - now.date()).days == 2:
        return f"后天 {dt.strftime('%H:%M')}"
    return dt.strftime("%m-%d %H:%M")
