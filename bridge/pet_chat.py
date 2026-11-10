"""pet_chat.py — 从外部（DSH / 命令行）跟桌宠说话。

用法：
  python pet_chat.py "今天好累"           # 跟她说一句，等她回，打印回复
  python pet_chat.py --say "该喝水了"     # 让她直接念这句（不动脑）
  python pet_chat.py --transcript 20      # 看最近 20 条

前提：桌宠后端在 127.0.0.1:12393 上跑着，客户端窗口开着。
"""

import json
import os
import sys
import time
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))


def _pet_api() -> str:
    if os.path.dirname(_HERE) not in sys.path:
        sys.path.insert(0, os.path.dirname(_HERE))
    from bridge.settings import PET_API

    return PET_API


BASE = _pet_api()
from bridge.net import urlopen


def _post(path: str, payload: dict) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        BASE + path, data=body, headers={"Content-Type": "application/json"}
    )
    with urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


def _get(path: str) -> dict:
    with urlopen(BASE + path, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def transcript(limit: int = 20):
    data = _get("/api/transcript?limit=%d" % limit)
    for m in data.get("messages", []):
        who = "你" if m.get("role") == "human" else (m.get("name") or "她")
        print("%s: %s" % (who, (m.get("content") or "").strip()))


def chat(text: str, timeout: float = 90.0) -> str:
    before = _get("/api/transcript?limit=200").get("messages", [])
    seen = len(before)
    _post("/api/chat", {"text": text})

    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(0.8)
        msgs = _get("/api/transcript?limit=200").get("messages", [])
        new = msgs[seen:]
        reply = [m.get("content", "") for m in new if m.get("role") == "ai"]
        if reply:
            return "".join(reply).strip()
    return "（%.0f 秒内没等到回复）" % timeout


def say(text: str) -> str:
    _post("/api/say", {"text": text})
    return "（已让她念出来）"


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    if args[0] == "--say" and len(args) > 1:
        print(say(" ".join(args[1:])))
    elif args[0] == "--transcript":
        transcript(int(args[1]) if len(args) > 1 else 20)
    else:
        print(chat(" ".join(args)))


if __name__ == "__main__":
    main()
