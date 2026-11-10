# aliases.py — 联系人别名表（识别错的写法 → 标准名）
#
# 例：飞问 -> feven
# 用过的错法记下来，下次直接字符串替换，不用再过一遍模型。

import json
import threading

from ..settings import DATA_DIR

_FILE = str(DATA_DIR / "aliases.json")

_lock = threading.Lock()
_cache = None


def _load() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    try:
        with open(_FILE, encoding="utf-8") as f:
            data = json.load(f)
        _cache = {str(k): str(v) for k, v in data.items() if k and v}
    except Exception:
        _cache = {}
    return _cache


def save() -> None:
    with _lock:
        try:
            with open(_FILE, "w", encoding="utf-8") as f:
                json.dump(_cache or {}, f, ensure_ascii=False, indent=2)
        except Exception:
            pass


def add(wrong: str, right: str) -> bool:
    """记一条映射。太短的（单个字）不记，避免误伤正常用词。"""
    wrong = (wrong or "").strip()
    right = (right or "").strip()
    if len(wrong) < 2 or not right or wrong == right:
        return False
    d = _load()
    if d.get(wrong) == right:
        return False
    d[wrong] = right
    save()
    return True


def apply(text: str) -> str:
    """把已知的错写法替换成标准名（长的优先，避免部分覆盖）。"""
    text = text or ""
    d = _load()
    for wrong in sorted(d, key=len, reverse=True):
        if wrong in text:
            text = text.replace(wrong, d[wrong])
    return text


def all() -> dict:
    return dict(_load())
