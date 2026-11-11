"""safety.py — 三个闸门：联系人匹配、时间解析、待确认状态。

设计原则：模型负责"理解"，这里负责"事实"。
模型抽出来的名字/时间，必须先过这里，才能变成真正动作。
"""

from .v0_load import name_match, vault, when
from . import store
from ._v0.config import int_cfg

# 确认 / 取消 的判定词（纯规则，不走模型）
_CONFIRM_WORDS = (
    "确认",
    "确定",
    "发吧",
    "发",
    "好的",
    "好",
    "嗯",
    "可以",
    "发送",
    "行",
    "ok",
    "OK",
)
_CANCEL_WORDS = ("取消", "算了", "别发", "不发了", "不用了", "不要", "停", "不了")


# ---------------- 联系人 ----------------


def _contact_by_display(display: str):
    for c in getattr(vault(), "contacts", []):
        if (c.remark or c.nickname or "") == display:
            return c
    return None


def ensure_contacts(force: bool = False) -> int:
    """联系人缓存为空时，从 OneBot 拉一次；force=True 时强制重拉。"""
    v = vault()
    if not force and getattr(v, "contacts", None):
        return len(v.contacts)
    try:
        return v.refresh()
    except Exception as e:
        try:
            v.last_error = "%s: %s" % (type(e).__name__, e)
        except Exception:
            pass
        return 0


def list_contacts(query: str = "", limit: int = 0) -> list:
    ensure_contacts()
    q = (query or "").strip().lower()
    out = []
    for c in getattr(vault(), "contacts", []):
        name = c.remark or c.nickname or str(c.user_id)
        if q and q not in name.lower() and q not in str(c.user_id):
            continue
        out.append(
            {"name": name, "uid": c.user_id, "remark": c.remark, "nickname": c.nickname}
        )
    return out[:limit] if limit else out


def resolve_contact(hint: str):
    """返回 (contact, error, candidates)。

    contact 有值 = 唯一确定；error 有值 = 不能发；candidates = 需要用户选。
    """
    hint = (hint or "").strip()
    if not hint:
        return None, "没说发给谁", []

    ensure_contacts()
    try:
        cands = vault().resolve(hint)
    except Exception as e:
        return None, f"查联系人出错：{type(e).__name__}", []

    # 查不到就强制重拉一次：可能是会话刚创建时 QQ 桥还没连上，缓存是空的
    if not cands:
        try:
            ensure_contacts(force=True)
            cands = vault().resolve(hint)
        except Exception:
            pass

    if not cands:
        if not getattr(vault(), "contacts", None):
            return None, "QQ 这边没连上（SnowLuma 没开或没登录），好友列表拉不到", []
        return None, f"没找到「{hint}」这个人（QQ 好友里没有）", []

    strict = [
        c for c in cands if c.score >= 90 and name_match().strict_ok(c.display, hint)
    ]
    if len(strict) == 1:
        c = vault().find_by_id(strict[0].user_id)
        if c:
            return c, "", []
        return None, f"找到「{strict[0].display}」但取不到 QQ 号", []

    if len(strict) > 1:
        return None, "", [{"name": c.display, "score": c.score, "uid": c.user_id} for c in strict]

    return (
        None,
        f"「{hint}」匹配不确定（最像的是「{cands[0].display}」，{cands[0].score} 分）",
        [{"name": c.display, "score": c.score, "uid": c.user_id} for c in cands[:5]],
    )


# ---------------- 时间 ----------------


def parse_time(time_text: str):
    """返回 (datetime, 剩余文字)。解析不出来返回 (None, 原文)。"""
    try:
        return when().parse_when(time_text or "")
    except Exception:
        return None, time_text or ""


def human_time(dt) -> str:
    try:
        return when().human(dt)
    except Exception:
        return dt.strftime("%m-%d %H:%M")


# ---------------- 待确认状态（跨进程：写文件） ----------------


def set_pending(uid: int, name: str, text: str) -> dict:
    return store.prepare(int(uid), name, text, int_cfg("CONFIRM_TIMEOUT", 300))


def get_pending() -> dict:
    return store.pending(int_cfg("CONFIRM_TIMEOUT", 300))


def clear_pending() -> None:
    store.cancel()


# ---------------- 确认 / 取消 判定 ----------------


def is_confirm(text: str) -> bool:
    t = (text or "").strip().lower().rstrip("。！!，, ")
    return t in {w.lower() for w in _CONFIRM_WORDS}


def is_cancel(text: str) -> bool:
    t = (text or "").strip().lower().rstrip("。！!，, ")
    return t in {w.lower() for w in _CANCEL_WORDS}
