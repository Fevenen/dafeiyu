"""Read completed, user-visible replies from DSH v4 journals, never outline previews."""

import io
import json
from pathlib import Path

from . import settings


def text_content(content):
    if isinstance(content, str):
        return content
    return "".join(
        part.get("text", "") for part in (content or [])
        if isinstance(part, dict) and part.get("type") == "text"
    )


class HistoryReader:
    def __init__(self, root=None):
        self.root = Path(root) if root else settings.path("dsh_history", Path.home() / ".dsh/sessions")
        self.cache = {}

    def turns(self, summary_path):
        matches = list(self.root.glob("*/" + summary_path.stem + "/session.v4.jsonl.zstd"))
        if len(matches) != 1:
            return []
        path = matches[0]
        stat = path.stat()
        stamp = (stat.st_mtime_ns, stat.st_size)
        cached = self.cache.get(path)
        if cached and cached[0] == stamp:
            return cached[1]
        import zstandard

        turns = {}
        current = None
        # Frames are appended while DSH runs; an unfinished last line is retried later.
        with path.open("rb") as raw:
            with zstandard.ZstdDecompressor().stream_reader(raw, read_across_frames=True) as stream:
                for line in io.TextIOWrapper(stream, encoding="utf-8"):
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    data = event.get("data") or {}
                    kind = event.get("type")
                    if kind == "turn/start":
                        current = data.get("turn")
                        turns[current] = {"turn": current, "response": "", "complete": False}
                    elif kind == "assistant/message":
                        turn = turns.get(data.get("turn", current))
                        message = data.get("message") or {}
                        if turn is not None:
                            text = text_content(message.get("content"))
                            if text:
                                turn["response"] += ("\n\n" if turn["response"] else "") + text
                    elif kind == "turn/end":
                        turn = turns.get(data.get("turn", current))
                        if turn is not None:
                            turn["complete"] = (data.get("reason") or {}).get("kind") == "completed"
        result = list(turns.values())
        self.cache = {path: (stamp, result)}
        return result
