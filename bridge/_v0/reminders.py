"""Transactional reminder storage. Compatibility API for the companion tools."""

import time
import uuid
from datetime import datetime
from ..store import db, migrate_reminders
from ..context import session_id


def add(text, due):
    migrate_reminders()
    item = dict(
        id=uuid.uuid4().hex,
        text=text.strip(),
        due=due.isoformat(timespec="seconds"),
        created=datetime.now().isoformat(timespec="seconds"),
    )
    with db() as conn:
        conn.execute(
            "INSERT INTO reminders(id,session,text,due,created) VALUES(?,?,?,?,?)",
            (item["id"], session_id(), item["text"], item["due"], item["created"]),
        )
    return item


def pending():
    migrate_reminders()
    with db() as conn:
        return [
            dict(x)
            for x in conn.execute(
                "SELECT * FROM reminders WHERE session=? AND fired=0 AND done=0 ORDER BY due",
                (session_id(),),
            )
        ]


def due_now(now=None):
    migrate_reminders()
    with db() as conn:
        return [
            dict(x)
            for x in conn.execute(
                "SELECT * FROM reminders WHERE fired=0 AND done=0 AND due<=? AND lease<=? ORDER BY due",
                ((now or datetime.now()).isoformat(timespec="seconds"), time.time()),
            )
        ]


def claim(rid):
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        return bool(
            conn.execute(
                "UPDATE reminders SET lease=?,attempts=attempts+1 WHERE id=? AND fired=0 AND done=0 AND lease<=?",
                (time.time() + 120, rid, time.time()),
            ).rowcount
        )


def delivery(rid, channel, status):
    if channel not in ("qq", "pet") or status not in ("sent", "pending", "unknown"):
        raise ValueError("invalid delivery state")
    with db() as conn:
        conn.execute("UPDATE reminders SET " + channel + "=? WHERE id=?", (status, rid))


def release(rid):
    with db() as conn:
        conn.execute(
            "UPDATE reminders SET lease=?,fired=CASE WHEN qq='sent' AND pet='sent' THEN 1 ELSE 0 END,fired_at=CASE WHEN qq='sent' AND pet='sent' THEN ? ELSE fired_at END WHERE id=?",
            (time.time() + 30, datetime.now().isoformat(timespec="seconds"), rid),
        )


def mark_fired(ids):
    with db() as conn:
        conn.executemany(
            "UPDATE reminders SET fired=1,fired_at=? WHERE id=?",
            [(datetime.now().isoformat(timespec="seconds"), rid) for rid in ids],
        )


def remove(rid):
    with db() as conn:
        return bool(
            conn.execute(
                "UPDATE reminders SET done=1 WHERE id=? AND session=? AND lease<=?",
                (rid, session_id(), time.time()),
            ).rowcount
        )


def recent(limit=20):
    with db() as conn:
        return [
            dict(x)
            for x in conn.execute(
                "SELECT * FROM reminders WHERE session=? AND fired=1 ORDER BY fired_at DESC LIMIT ?",
                (session_id(), int(limit)),
            )
        ]


def clear_fired():
    with db() as conn:
        return conn.execute(
            "DELETE FROM reminders WHERE session=? AND fired=1", (session_id(),)
        ).rowcount
