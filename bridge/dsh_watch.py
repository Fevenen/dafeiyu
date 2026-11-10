"""Read-only DSH adapter: session JSON -> bounded speech queue. Never executes tools."""

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bridge import settings
from bridge.net import urlopen


def load_json(path, default):
    try:
        with open(path, encoding="utf-8-sig") as stream:
            return json.load(stream)
    except (OSError, ValueError):
        return default


def session_turns(path):
    data = load_json(path, {})
    rows = data.get("record", {}).get("rows", {})
    return (
        (rows.get("title") or {}).get("val", ""),
        (rows.get("workingDirectory") or {}).get("val", ""),
        ((rows.get("turnOutline") or {}).get("val") or {}).get("turns", []),
    )


def split_sentences(text, limit=70):
    result = []
    for sentence in re.split(r"(?<=[。！？!?；;\n])", text):
        sentence = sentence.strip()
        while sentence:
            result.append(sentence[:limit])
            sentence = sentence[limit:]
    return [x for x in result if re.search(r"[\w\u4e00-\u9fff]", x)]


def post(api, path, payload):
    req = urllib.request.Request(
        api + path,
        data=json.dumps(payload, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(req, timeout=10) as response:
        data = json.load(response)
    if not data.get("ok"):
        raise RuntimeError(data.get("error", "speech request failed"))
    return data


def say(api, text, key):
    result = post(api, "/api/say", {"text": text, "enqueue": True, "job_id": key})
    if result.get("clients", 0) < 1:
        raise RuntimeError("no online pet client; cursor was not advanced")


def latest(folder, sessions):
    paths = []
    for path in sessions.glob("*.json"):
        _, cwd, _ = session_turns(path)
        if not folder or os.path.normcase(
            os.path.abspath(cwd or ".")
        ) == os.path.normcase(os.path.abspath(folder)):
            paths.append(path)
    return max(paths, key=lambda p: p.stat().st_mtime) if paths else None


def save(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default="")
    parser.add_argument("--session", default="")
    parser.add_argument("--latest", action="store_true")
    parser.add_argument("--list", action="store_true")
    parser.add_argument(
        "--dry",
        action="store_true",
        help="read and print only; no speech, actions or cursor writes",
    )
    parser.add_argument("--sessions")
    parser.add_argument("--api")
    parser.add_argument(
        "--once", action="store_true", help="process one snapshot (diagnostics)"
    )
    args = parser.parse_args()
    sessions = settings.path("dsh_sessions", settings.SESSIONS_DIR, args.sessions)
    api = str(settings.get("pet_api", settings.PET_API, args.api)).rstrip("/")
    if args.list:
        for path in sorted(
            sessions.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True
        ):
            title, cwd, turns = session_turns(path)
            print(path.name, title, cwd, len(turns), flush=True)
        return
    state_path = settings.DATA_DIR / "state/dsh_watch.json"
    state = load_json(state_path, {})
    active = None
    seen_response = ""
    changed = time.monotonic()
    while True:
        if args.session:
            name = args.session
            if not name.startswith("session-"):
                name = "session-" + name
            if not name.endswith(".json"):
                name += ".json"
            path = sessions / name
        else:
            path = latest(args.dir, sessions)
        if path is None:
            time.sleep(0.3)
            continue
        _, _, turns = session_turns(path)
        if not turns:
            time.sleep(0.3)
            continue
        turn = turns[-1]
        key = str(path) + ":" + str(turn.get("turn", len(turns)))
        response = (turn.get("response") or "").strip()
        if key != active:
            active = key
            seen_response = response
            changed = time.monotonic()
        if response != seen_response:
            seen_response = response
            changed = time.monotonic()
        cursor = state.get(key, "")
        # Edits are treated as a new revision with distinct chunk IDs.
        if not response.startswith(cursor):
            cursor = ""
        tail = response[len(cursor) :]
        end = max([tail.rfind(c) for c in "。！？!?；;\n"] + [-1])
        if time.monotonic() - changed >= 1.2:
            end = len(tail) - 1
        chunk = tail[: end + 1]
        if chunk:
            pieces = split_sentences(clean(chunk))
            success = True
            for index, piece in enumerate(pieces):
                job = hashlib.sha256(
                    (
                        key + ":" + str(len(cursor)) + ":" + str(index) + ":" + piece
                    ).encode()
                ).hexdigest()
                try:
                    if args.dry:
                        print("[dry]", piece, flush=True)
                    else:
                        say(api, piece, job)
                except Exception as exc:
                    print("Speech enqueue failed:", type(exc).__name__, flush=True)
                    success = False
                    break
            if success:
                state[key] = cursor + chunk
                if not args.dry:
                    save(state_path, state)
            elif not args.once:
                time.sleep(2)
        if args.once:
            return
        time.sleep(0.3)


def clean(text):
    """把 Markdown / 表情符号去掉，只留能念的文字。"""
    t = text or ""
    t = re.sub(r"```.*?```", " ", t, flags=re.S)
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", t)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"^\s{0,3}#{1,6}\s*", "", t, flags=re.M)
    t = re.sub(r"#{1,6}\s*", "", t)
    t = re.sub(r"[*_~>]+", "", t)
    t = re.sub(r"\[[^\]]{1,12}\]", "", t)
    t = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF]", "", t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{2,}", "\n", t)
    return t.strip()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        from bridge.singleton import singleton

        with singleton("watcher"):
            main()
    except KeyboardInterrupt:
        pass
