"""SQLite transactions for cross-process message claims, requests and reminders."""

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from . import settings
from .context import session_id


@contextmanager
def db():
    settings.ensure_dirs()
    conn = sqlite3.connect(str(settings.DATA_DIR / "bridge.sqlite3"), timeout=20)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS messages (
          id TEXT PRIMARY KEY, session TEXT NOT NULL, uid INTEGER NOT NULL,
          name TEXT NOT NULL, text TEXT NOT NULL, ts REAL NOT NULL,
          status TEXT NOT NULL, result TEXT DEFAULT '', updated REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS msg_session ON messages(session, ts);
        CREATE TABLE IF NOT EXISTS requests (
          session TEXT, id TEXT, status TEXT, result TEXT, ts REAL,
          PRIMARY KEY(session,id));
        CREATE TABLE IF NOT EXISTS reminders (
          id TEXT PRIMARY KEY, session TEXT NOT NULL, text TEXT NOT NULL,
          due TEXT NOT NULL, created TEXT NOT NULL, fired INTEGER DEFAULT 0,
          fired_at TEXT, done INTEGER DEFAULT 0, qq TEXT DEFAULT 'pending',
          pet TEXT DEFAULT 'pending', lease REAL DEFAULT 0, attempts INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS migrations (name TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS conversation_heads (
          session TEXT PRIMARY KEY, digest TEXT, length INTEGER, conflict INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS dialogue (
          session TEXT PRIMARY KEY, payload TEXT NOT NULL, updated REAL NOT NULL);
        """)
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def prepare(uid, name, text, ttl=300):
    now = time.time()
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute(
            "SELECT * FROM messages WHERE session=? AND status='pending' AND ts>? ORDER BY ts DESC LIMIT 1",
            (session_id(), now - ttl),
        ).fetchone()
        if current and current["uid"] == uid and current["text"] == text:
            return dict(current)
        conn.execute(
            "UPDATE messages SET status='cancelled',updated=? WHERE session=? AND status='pending'",
            (now, session_id()),
        )
        mid = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO messages(id,session,uid,name,text,ts,status,updated) VALUES(?,?,?,?,?,?,'pending',?)",
            (mid, session_id(), uid, name, text, now, now),
        )
        return dict(
            conn.execute("SELECT * FROM messages WHERE id=?", (mid,)).fetchone()
        )


def set_dialogue(payload):
    with db() as conn:
        conn.execute("INSERT OR REPLACE INTO dialogue VALUES(?,?,?)",
                     (session_id(), json.dumps(payload, ensure_ascii=False), time.time()))


def get_dialogue(ttl=300):
    with db() as conn:
        row = conn.execute("SELECT payload FROM dialogue WHERE session=? AND updated>?",
                           (session_id(), time.time() - ttl)).fetchone()
        return json.loads(row["payload"]) if row else {}


def clear_dialogue():
    with db() as conn:
        conn.execute("DELETE FROM dialogue WHERE session=?", (session_id(),))


def pending(ttl=300):
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM messages WHERE session=? AND status='pending' AND ts>? ORDER BY ts DESC LIMIT 1",
            (session_id(), time.time() - ttl),
        ).fetchone()
        return dict(row) if row else {}


def claim(ttl=300):
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM messages WHERE session=? AND status='pending' AND ts>? ORDER BY ts DESC LIMIT 1",
            (session_id(), time.time() - ttl),
        ).fetchone()
        if not row:
            return {}
        conn.execute(
            "UPDATE messages SET status='sending',updated=? WHERE id=?",
            (time.time(), row["id"]),
        )
        return dict(row)


def finish(mid, status, result):
    with db() as conn:
        conn.execute(
            "UPDATE messages SET status=?,result=?,updated=? WHERE id=?",
            (status, result, time.time(), mid),
        )


def cancel():
    with db() as conn:
        n = conn.execute(
            "UPDATE messages SET status='cancelled',updated=? WHERE session=? AND status='pending'",
            (time.time(), session_id()),
        ).rowcount
        return bool(n)


def latest():
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM messages WHERE session=? ORDER BY ts DESC LIMIT 1",
            (session_id(),),
        ).fetchone()
        return dict(row) if row else {}


def cached_request(rid):
    if not rid:
        return None
    with db() as conn:
        row = conn.execute("SELECT status,result FROM requests WHERE session=? AND id=?",
                           (session_id(), rid)).fetchone()
        if row:
            return row['result'] if row['status'] == 'done' else '这条请求正在处理或上次处理未完成，请先查询状态，不要重复执行。'
    return None


def request_once(rid, fn):
    if not rid:
        return fn()
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM requests WHERE session=? AND id=?", (session_id(), rid)
        ).fetchone()
        if row:
            return (
                row["result"]
                if row["status"] == "done"
                else "这条请求正在处理或上次处理未完成，请先查询状态，不要重复执行。"
            )
        conn.execute(
            "INSERT INTO requests VALUES(?,?,'running','',?)",
            (session_id(), rid, time.time()),
        )
    try:
        result = fn()
    except Exception:
        with db() as conn:
            conn.execute(
                "UPDATE requests SET status='done',result=? WHERE session=? AND id=?",
                ("请求处理异常，执行结果需要核对。", session_id(), rid),
            )
        raise
    with db() as conn:
        conn.execute(
            "UPDATE requests SET status='done',result=? WHERE session=? AND id=?",
            (result, session_id(), rid),
        )
    return result


def recent(limit=3):
    with db() as conn:
        return [
            dict(x)
            for x in conn.execute(
                "SELECT id,name,text,status,result FROM messages WHERE session=? ORDER BY ts DESC LIMIT ?",
                (session_id(), max(1, min(20, int(limit)))),
            )
        ]


def bind_history(session, current_digest, length, prefix_digest):
    """Fingerprint fallback must stop on divergent histories, never merge two branches."""
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM conversation_heads WHERE session=?", (session,)
        ).fetchone()
        if row and (
            row["conflict"]
            or not (
                row["digest"] == current_digest
                or (
                    length > row["length"]
                    and row["digest"] == prefix_digest(row["length"])
                )
            )
        ):
            conn.execute(
                "UPDATE conversation_heads SET conflict=1 WHERE session=?", (session,)
            )
            return False
        conn.execute(
            "INSERT OR REPLACE INTO conversation_heads VALUES(?,?,?,0)",
            (session, current_digest, length),
        )
        return True


def migrate_reminders():
    """Import legacy JSON once, keep original files. Pending sends are never imported."""
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        for file in [settings.BRIDGE_ROOT / "_v0/reminders.json"]:
            key = str(file)
            if conn.execute("SELECT 1 FROM migrations WHERE name=?", (key,)).fetchone():
                continue
            if file.exists():
                with file.open(encoding="utf-8-sig") as stream:
                    items = json.load(stream)
                for item in items:
                    conn.execute(
                        "INSERT OR IGNORE INTO reminders(id,session,text,due,created,fired,fired_at,done) VALUES(?,?,?,?,?,?,?,?)",
                        (
                            item["id"],
                            "local",
                            item["text"],
                            item["due"],
                            item.get("created", ""),
                            bool(item.get("fired")),
                            item.get("fired_at"),
                            bool(item.get("done")),
                        ),
                    )
            conn.execute("INSERT INTO migrations VALUES(?)", (key,))
