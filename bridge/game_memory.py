"""Bounded cross-process conversation memory; never grants game permissions."""

from contextlib import contextmanager
import json
from pathlib import Path
import secrets
import sqlite3
import time

from . import settings

HISTORY_SECONDS = 1800


class GameMemory:
    def __init__(self, root=None, clock=None):
        self.root = Path(root) if root else settings.DATA_DIR / 'games/sillytavern'
        self.path = self.root / 'conversation.sqlite3'
        self.clock = clock or time.time

    @contextmanager
    def database(self):
        self.root.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=3)
        try:
            connection.execute('CREATE TABLE IF NOT EXISTS room (id INTEGER PRIMARY KEY, data TEXT NOT NULL)')
            connection.execute('''CREATE TABLE IF NOT EXISTS exchanges (
                id TEXT PRIMARY KEY, chat_id TEXT, lineage TEXT, source TEXT,
                user_text TEXT, assistant_text TEXT, created REAL)''')
            connection.execute('BEGIN IMMEDIATE')
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def state(connection):
        row = connection.execute('SELECT data FROM room WHERE id=1').fetchone()
        return json.loads(row[0]) if row else None

    def publish(self, context, memory, mode, expires, synced_at):
        with self.database() as connection:
            previous = self.state(connection) or {}
            old = previous.get('context') or {}
            fingerprints = old.get('fingerprints') or []
            changed = (old.get('chat_id') != context['chat_id'] or
                       fingerprints != context['fingerprints'][:len(fingerprints)])
            if changed:
                connection.execute('DELETE FROM exchanges')
            state = {'context': context, 'memory': memory, 'mode': mode, 'expires': expires,
                     'synced_at': synced_at, 'updated_at': self.clock(),
                     'lineage': secrets.token_hex(12) if changed else previous.get('lineage', secrets.token_hex(12))}
            connection.execute('INSERT OR REPLACE INTO room VALUES (1,?)', (json.dumps(state, ensure_ascii=False),))

    def close(self, reason='closed'):
        if not self.path.exists():
            return
        with self.database() as connection:
            state = self.state(connection)
            if state:
                state.update(mode=reason, expires=0)
                connection.execute('UPDATE room SET data=? WHERE id=1', (json.dumps(state, ensure_ascii=False),))

    def clear(self, chat_id=None):
        if not self.path.exists():
            return
        with self.database() as connection:
            state = self.state(connection)
            if chat_id is not None and (not state or state['context']['chat_id'] != chat_id):
                return
            connection.execute('DELETE FROM exchanges')
            if state:
                state['lineage'] = secrets.token_hex(12)
                connection.execute('UPDATE room SET data=? WHERE id=1', (json.dumps(state, ensure_ascii=False),))

    def read(self):
        if not self.path.exists():
            return None
        try:
            with self.database() as connection:
                state = self.state(connection)
                if not state or (state.get('expires', 0) <= self.clock() and
                                 self.clock() - state['updated_at'] > HISTORY_SECONDS):
                    return None
                rows = connection.execute('''SELECT source,user_text,assistant_text,created,id
                    FROM exchanges WHERE lineage=? ORDER BY created DESC,rowid DESC LIMIT 12''',
                    (state['lineage'],)).fetchall()
                recent, budget = [], 4000
                for row in rows:
                    cost = len(row[1]) + len(row[2])
                    if cost > budget:
                        break
                    recent.append(dict(source=row[0], user=row[1], assistant=row[2], at=row[3], id=row[4]))
                    budget -= cost
                state['exchanges'] = list(reversed(recent))
                return state
        except (OSError, ValueError, KeyError, sqlite3.Error):
            return None

    def remember(self, snapshot, user, assistant, source, event_id=None):
        if not snapshot or not assistant or not self.path.exists():
            return
        try:
            with self.database() as connection:
                state = self.state(connection)
                if not state or state['lineage'] != snapshot.get('lineage'):
                    return  # A chat switch/history edit must not inherit a late response.
                connection.execute('INSERT OR IGNORE INTO exchanges VALUES (?,?,?,?,?,?,?)',
                                   (event_id or secrets.token_hex(16), state['context']['chat_id'],
                                    state['lineage'], source, str(user or '')[:800], str(assistant)[:1200], self.clock()))
                connection.execute('''DELETE FROM exchanges WHERE rowid NOT IN (
                    SELECT rowid FROM exchanges ORDER BY created DESC,rowid DESC LIMIT 12)''')
        except (OSError, ValueError, KeyError, sqlite3.Error):
            return  # Memory persistence cannot fail a normal conversation.
