# reminders.py — 待办/提醒的存储（纯 JSON，重启不丢）

import json
import os
import threading
import uuid
from datetime import datetime

_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reminders.json")
_lock = threading.Lock()


def _load() -> list:
    try:
        with open(_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save(items: list) -> None:
    with _lock:
        try:
            with open(_FILE, "w", encoding="utf-8") as f:
                json.dump(items, f, ensure_ascii=False, indent=2)
        except Exception:
            pass


def add(text: str, due: datetime) -> dict:
    item = {
        "id": uuid.uuid4().hex[:8],
        "text": (text or "").strip(),
        "due": due.strftime("%Y-%m-%dT%H:%M:%S"),
        "created": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "fired": False,
        "fired_at": None,
        "done": False,
    }
    items = _load()
    items.append(item)
    _save(items)
    return item


def pending() -> list:
    items = [x for x in _load() if not x.get("fired") and not x.get("done")]
    return sorted(items, key=lambda x: x.get("due") or "")


def due_now(now: datetime = None) -> list:
    now = now or datetime.now()
    out = []
    for x in _load():
        if x.get("fired") or x.get("done"):
            continue
        try:
            due = datetime.fromisoformat(x["due"])
        except Exception:
            continue
        if due <= now:
            out.append(x)
    return out


def mark_fired(ids) -> None:
    ids = set(ids)
    items = _load()
    stamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    for x in items:
        if x.get("id") in ids:
            x["fired"] = True
            x["fired_at"] = stamp
    _save(items)


def remove(rid: str) -> bool:
    items = _load()
    left = [x for x in items if x.get("id") != rid]
    if len(left) == len(items):
        return False
    _save(left)
    return True


def recent(limit: int = 20) -> list:
    items = [x for x in _load() if x.get("fired")]
    items.sort(key=lambda x: x.get("fired_at") or "", reverse=True)
    return items[:limit]


def clear_fired() -> int:
    items = _load()
    left = [x for x in items if not x.get("fired")]
    _save(left)
    return len(items) - len(left)
