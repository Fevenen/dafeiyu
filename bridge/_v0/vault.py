# vault.py — 隐私保险柜：联系人快照、匹配、一次性令牌、审计
import json
import os
import re
import time
import uuid
from collections import deque

from pypinyin import Style, lazy_pinyin
from rapidfuzz import fuzz

from . import sender
from .config import LOG_DIR, int_cfg
from .models import Candidate, Contact

os.makedirs(LOG_DIR, exist_ok=True)
AUDIT_LOG = os.path.join(LOG_DIR, "audit.jsonl")


_PUNCT = re.compile(r"[^\w\u4e00-\u9fff]+", re.UNICODE)

# "我的设备"伪联系人（QQ 文件传输用），不是真人
_DEVICE_NAMES = {
    "我的电脑",
    "我的手机",
    "我的pad",
    "我的平板",
    "我的设备",
    "文件传输助手",
}


def _is_device_account(uid: int, nickname: str, remark: str) -> bool:
    if nickname.strip().lower() in _DEVICE_NAMES:
        return True
    if remark.strip().lower() in _DEVICE_NAMES:
        return True
    # QQ 内部设备号段
    if 2113929216 <= uid <= 2113929230:
        return True
    return False


_PREFIXES = ("小", "老", "阿", "大", "啊")
_SUFFIXES = ("哥", "姐", "总", "老师", "同学", "老板")


def _norm(s: str) -> str:
    """（统一到 name_match）小写、全角转半角、去标点空格。"""
    from . import name_match

    return name_match.base(s)


def _variants(h: str) -> set:
    """口语称呼的变体："小z" -> {"小z","z"}；"老王" -> {"老王","王"}。"""
    out = {h}
    for p in _PREFIXES:
        if h.startswith(p) and len(h) > len(p):
            out.add(h[len(p) :])
    for s in _SUFFIXES:
        if h.endswith(s) and len(h) > len(s):
            out.add(h[: -len(s)])
    return out


class Vault:
    def __init__(self):
        self.contacts: list[Contact] = []
        self.last_error = ""
        self._tokens: dict[str, tuple[Candidate, float]] = {}
        self._resolve_times: deque = deque()

    # ---------- 数据 ----------

    def refresh(self) -> int:
        res = sender.get_friend_list()
        self.contacts = []
        for f in res.get("data") or []:
            uid = int(f.get("user_id", 0))
            if _is_device_account(uid, f.get("nickname") or "", f.get("remark") or ""):
                continue
            c = Contact(
                user_id=uid,
                nickname=f.get("nickname") or "",
                remark=f.get("remark") or "",
            )
            base = c.remark or c.nickname
            c.pinyin = "".join(lazy_pinyin(base)).lower()
            c.pinyin_initials = "".join(
                lazy_pinyin(base, style=Style.FIRST_LETTER)
            ).lower()
            self.contacts.append(c)
        return len(self.contacts)

    def find_by_id(self, user_id: int) -> Contact | None:
        for c in self.contacts:
            if c.user_id == user_id:
                return c
        return None

    # ---------- 审计 / 限流 ----------

    def _audit(self, **kw):
        rec = {"ts": time.time(), **kw}
        with open(AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def _resolve_allowed(self) -> bool:
        limit = int_cfg("VAULT_RESOLVE_PER_MINUTE", 10)  # 防"扫通讯录"
        now = time.time()
        while self._resolve_times and now - self._resolve_times[0] > 60:
            self._resolve_times.popleft()
        return len(self._resolve_times) < limit

    # ---------- 匹配 ----------

    def _score(self, h: str, c: Contact) -> tuple[int, str]:
        if h == _norm(c.remark):
            return 100, "备注完全一致"
        if h == _norm(c.nickname):
            return 95, "昵称完全一致"
        if _norm(c.remark).startswith(h):
            return 85, "备注前缀匹配"
        if h in _norm(c.nickname):
            return 75, "昵称包含"
        if c.pinyin and h == c.pinyin:
            return 70, "拼音全拼匹配"
        if c.pinyin_initials and h == c.pinyin_initials:
            return 60, "拼音首字母匹配"
        r = fuzz.ratio(h, _norm(c.remark)) if c.remark else 0
        r2 = fuzz.ratio(h, _norm(c.nickname))
        best = max(r, r2)
        if best >= 80:
            # 原来是 int(best/2)，90 分只能拿 45，永远低于 50 的候选门槛，
            # 等于模糊匹配这条分支是死代码。改成 0.8 倍：88.9 -> 71 分。
            return int(best * 0.8), "模糊匹配"
        return 0, ""

    def resolve(self, hint: str, limit: int = 5) -> list[Candidate]:
        """匹配联系人，返回候选（token 形式，不含明文给模型）。"""
        h = _norm(hint)
        self.last_error = ""
        if len(h) < 1:
            self._audit(op="resolve", hint=hint, count=0, reason="empty")
            return []
        if not self._resolve_allowed():
            self.last_error = "rate_limited"
            self._audit(op="resolve", hint=hint, count=0, reason="rate_limited")
            return []

        variants = _variants(h)
        scored = []
        for c in self.contacts:
            best_score, best_reason, best_variant = 0, "", h
            for v in variants:
                s, reason = self._score(v, c)
                if s > best_score:
                    best_score, best_reason, best_variant = s, reason, v
            if best_score >= 50:
                if best_variant != h:
                    best_reason = f"{best_reason}（按「{best_variant}」匹配）"
                scored.append((best_score, best_reason, c))

        scored.sort(key=lambda x: -x[0])

        # 不做静默收窄：只要有多个候选，就交给编排层让用户确认
        out = []
        for s, reason, c in scored[:limit]:
            token = uuid.uuid4().hex
            cand = Candidate(
                token=token,
                user_id=c.user_id,
                display=c.remark or c.nickname,
                score=s,
                reason=reason,
            )
            self._tokens[token] = (cand, time.time() + int_cfg("VAULT_TOKEN_TTL", 600))
            out.append(cand)
        self._audit(
            op="resolve", hint=hint, count=len(out), tokens=[c.token for c in out]
        )
        self._resolve_times.append(time.time())
        return out

    # ---------- 令牌 ----------

    def describe(self, token: str) -> dict | None:
        """给人看的通道：返回名字+号码。禁止把结果传回给模型。"""
        item = self._tokens.get(token)
        if not item:
            return None
        cand, exp = item
        if time.time() > exp:
            self._tokens.pop(token, None)
            return None
        c = self.find_by_id(cand.user_id)
        return {
            "display": cand.display,
            "user_id": cand.user_id,
            "reason": cand.reason,
            "remark": c.remark if c else "",
            "nickname": c.nickname if c else "",
        }

    def consume(self, token: str) -> Contact | None:
        """确认后兑换成联系人，令牌一次性使用。"""
        item = self._tokens.pop(token, None)
        if not item:
            return None
        cand, exp = item
        if time.time() > exp:
            return None
        return self.find_by_id(cand.user_id)


vault = Vault()
