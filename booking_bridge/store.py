"""SQLite inbox, durable intents, tombstones and source snapshots; no network calls."""
import json
import sqlite3
import secrets
import time
from contextlib import closing, contextmanager
from pathlib import Path

from .model import Review, digest

SCHEMA = '''
CREATE TABLE IF NOT EXISTS events (
 id TEXT PRIMARY KEY, booking TEXT NOT NULL, created REAL NOT NULL, payload TEXT NOT NULL,
 hash TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'queued', reason TEXT,
 attempts INTEGER NOT NULL DEFAULT 0, due REAL NOT NULL DEFAULT 0, received REAL NOT NULL);
CREATE INDEX IF NOT EXISTS queue ON events(state,due,created);
CREATE TABLE IF NOT EXISTS booking_heads (
 booking TEXT PRIMARY KEY, created REAL NOT NULL, event TEXT NOT NULL,
 snapshot_hash TEXT NOT NULL, conflicted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS links (
 booking TEXT PRIMARY KEY, target INTEGER UNIQUE, version REAL NOT NULL DEFAULT 0,
 snapshot TEXT, state TEXT NOT NULL DEFAULT 'new');
CREATE TABLE IF NOT EXISTS intents (
 booking TEXT PRIMARY KEY, event TEXT NOT NULL, kind TEXT NOT NULL, target INTEGER,
 desired TEXT NOT NULL, baseline TEXT NOT NULL, state TEXT NOT NULL,
 result INTEGER, started REAL NOT NULL);
CREATE TABLE IF NOT EXISTS clients (source TEXT PRIMARY KEY, target INTEGER UNIQUE NOT NULL);
CREATE TABLE IF NOT EXISTS source_bindings (employee TEXT NOT NULL, uid TEXT NOT NULL, booking TEXT NOT NULL,
 PRIMARY KEY(employee,uid));
CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS issues (
 key TEXT PRIMARY KEY, reason TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
 resolved INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS rates (key TEXT NOT NULL, at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS rate_idx ON rates(key,at);
CREATE TABLE IF NOT EXISTS feed_health (
 employee TEXT PRIMARY KEY, failures INTEGER NOT NULL DEFAULT 0, due REAL NOT NULL DEFAULT 0,
 last_ok REAL, state TEXT NOT NULL DEFAULT 'new');
CREATE TABLE IF NOT EXISTS refresh (employee TEXT PRIMARY KEY, due REAL NOT NULL);
CREATE TABLE IF NOT EXISTS audit (at REAL NOT NULL, action TEXT NOT NULL, reference TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS availability_observations (
 id INTEGER PRIMARY KEY AUTOINCREMENT, employee TEXT NOT NULL, version TEXT NOT NULL,
 kind TEXT NOT NULL, ready REAL NOT NULL, scheduled REAL, fetched REAL);
CREATE INDEX IF NOT EXISTS availability_employee ON availability_observations(employee,id);
'''


class Store:
    def __init__(self, path: Path, timeout=2.0):
        self.path = Path(path)
        self.timeout = timeout
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            # executescript commits its previous transaction; migrate atomically.
            conn.execute('BEGIN IMMEDIATE')
            version = conn.execute('PRAGMA user_version').fetchone()[0]
            if version > 1:
                raise Review('unsupported_database_version')
            if version < 1:
                for row in conn.execute('SELECT id,booking,created,payload FROM events ORDER BY created,received').fetchall():
                    event = json.loads(row['payload'])
                    if not event.get('test', False):
                        self._head(conn, event, row['created'])
                conn.execute('PRAGMA user_version=1')

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=self.timeout, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute('PRAGMA busy_timeout=' + str(int(self.timeout * 1000)))
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA synchronous=FULL')
            conn.execute('BEGIN IMMEDIATE')
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def rows(self, sql, args=()):
        with self.connect() as c:
            return [dict(row) for row in c.execute(sql, args).fetchall()]

    def execute(self, sql, args=()):
        with self.connect() as c:
            c.execute(sql, args)

    def is_ready(self, now=None, max_age=120):
        """Read health, heartbeat and current incidents in one transaction."""
        now = time.time() if now is None else now
        marker = Path(str(self.path) + '.recovery.json')
        if marker.exists() or marker.is_symlink():
            return False
        with self.connect() as conn:
            if conn.execute("SELECT 1 FROM cache WHERE key='recovery-hold'").fetchone():
                return False
            rows = {row['key']: row for row in conn.execute(
                "SELECT key,value,updated FROM cache WHERE key IN ('health','heartbeat')")}
            if set(rows) != {'health', 'heartbeat'}:
                return False
            try:
                if any(not 0 <= now - row['updated'] <= max_age for row in rows.values()):
                    return False
                health = json.loads(rows['health']['value'])
                heartbeat = json.loads(rows['heartbeat']['value'])
                if heartbeat is not True or not isinstance(health, dict):
                    return False
                if any(type(health.get(key)) is not int or health[key] != 0
                       for key in ('open_issues', 'old_queued')):
                    return False
            except (ValueError, TypeError):
                return False
            return conn.execute('SELECT COUNT(*) FROM issues WHERE resolved=0').fetchone()[0] == 0

    def ingest(self, event, now=None):
        now = time.time() if now is None else now
        from .model import stamp
        with self.connect() as c:
            old = c.execute('SELECT hash FROM events WHERE id=?', (event['id'],)).fetchone()
            if old:
                if old['hash'] != digest(event):
                    raise Review('event_id_payload_collision')
                return False
            c.execute('INSERT INTO events(id,booking,created,payload,hash,received) VALUES(?,?,?,?,?,?)',
                      (event['id'], event['data']['id'], stamp(event['created_at']).timestamp(),
                       json.dumps(event), digest(event), now))
            if not event.get('test', False):
                self._head(c, event, stamp(event['created_at']).timestamp())
        return True

    @staticmethod
    def _head(conn, event, created):
        booking = event['data']['id']
        snapshot = digest({'data': event['data'], 'deleted': event['type'] == 'booking.deleted'})
        old = conn.execute('SELECT * FROM booking_heads WHERE booking=?', (booking,)).fetchone()
        if old is None or created > old['created']:
            conn.execute('INSERT OR REPLACE INTO booking_heads VALUES(?,?,?,?,0)',
                         (booking, created, event['id'], snapshot))
        elif created == old['created'] and snapshot != old['snapshot_hash']:
            conn.execute('UPDATE booking_heads SET conflicted=1 WHERE booking=?', (booking,))

    def claim(self, now):
        with self.connect() as c:
            # A single OS-locked worker owns all booking mutations, including intents.
            row = c.execute("SELECT * FROM events WHERE state='queued' AND due<=? ORDER BY created,received LIMIT 1", (now,)).fetchone()
            if row:
                c.execute("UPDATE events SET state='working',attempts=attempts+1 WHERE id=?", (row['id'],))
                result = dict(row)
                result['attempts'] += 1
                return result

    def finish(self, event, state, reason=None, due=0):
        self.execute('UPDATE events SET state=?,reason=?,due=? WHERE id=?', (state, reason, due, event))

    def issue(self, key, reason, now=None, *, scope=None):
        now = time.time() if now is None else now
        with self.connect() as conn:
            conn.execute('INSERT INTO issues VALUES(?,?,?,?,0) ON CONFLICT(key) DO UPDATE SET reason=excluded.reason,updated=excluded.updated,resolved=0',
                         (key, reason, now, now))
            if key.startswith(('drift:', 'scope:')):
                conn.execute('INSERT OR REPLACE INTO cache VALUES(?,?,?)',
                             ('feed-scope:' + key, json.dumps(scope), now))

    def put(self, key, value, now=None):
        self.execute('INSERT INTO cache VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated=excluded.updated',
                     (key, json.dumps(value), time.time() if now is None else now))

    def get(self, key):
        rows = self.rows('SELECT * FROM cache WHERE key=?', (key,))
        return (json.loads(rows[0]['value']), rows[0]['updated']) if rows else (None, 0)

    def rate(self, key, limit, window=3600, now=None):
        now = time.time() if now is None else now
        with self.connect() as c:
            c.execute('DELETE FROM rates WHERE at<?', (now - 86400,))
            if c.execute('SELECT COUNT(*) FROM rates WHERE key=? AND at>?', (key, now-window)).fetchone()[0] >= limit:
                return False
            c.execute('INSERT INTO rates VALUES(?,?)', (key, now))
            return True

    def rate_available_at(self, key, limit, window=3600, now=None):
        now = time.time() if now is None else now
        rows = self.rows('SELECT at FROM rates WHERE key=? AND at>? ORDER BY at DESC LIMIT 1 OFFSET ?',
                         (key, now-window, limit-1))
        return rows[0]['at'] + window if rows else now

    def check_drift(self, expected_link, expected_applied, drifted, scope, now):
        """Do not publish or clear drift using evidence from before a yielded write."""
        booking = expected_link['booking']
        key = 'drift:' + booking
        with self.connect() as conn:
            link = conn.execute('SELECT * FROM links WHERE booking=?', (booking,)).fetchone()
            applied = conn.execute('SELECT value FROM cache WHERE key=?', ('applied:' + booking,)).fetchone()
            if (not link or dict(link) != expected_link or not applied or
                    json.loads(applied['value']) != expected_applied):
                return False
            if drifted:
                conn.execute('INSERT INTO issues VALUES(?,?,?,?,0) ON CONFLICT(key) DO UPDATE SET reason=excluded.reason,updated=excluded.updated,resolved=0',
                             (key, 'source_booking_changed_in_simplybook', now, now))
                conn.execute('INSERT OR REPLACE INTO cache VALUES(?,?,?)',
                             ('feed-scope:' + key, json.dumps(scope), now))
            else:
                conn.execute('UPDATE issues SET resolved=1 WHERE key=?', (key,))
            return True

    def refresh(self, employee, now=None):
        now = time.time() if now is None else now
        with self.connect() as conn:
            self._refresh(conn, employee, now)

    @staticmethod
    def _refresh(conn, employee, now):
        # Scheduler owns the short coalescing interval and rolling-hour quota.
        inserted = conn.execute('INSERT INTO refresh VALUES(?,?) ON CONFLICT(employee) DO NOTHING', (employee, now))
        if inserted.rowcount:
            conn.execute('INSERT OR REPLACE INTO cache VALUES(?,?,?)',
                         ('refresh-pending-since:' + employee, 'true', now))
        conn.execute('INSERT OR REPLACE INTO cache VALUES(?,?,?)',
                     ('refresh-generation:' + employee, json.dumps(secrets.token_hex(16)), now))

    def complete_refresh(self, employee, generation, now, coalesce_seconds=5):
        # A change arriving during HTTP must not be deleted with the completed batch.
        with self.connect() as conn:
            current = conn.execute('SELECT value FROM cache WHERE key=?',
                                   ('refresh-generation:' + employee,)).fetchone()
            if (json.loads(current['value']) if current else None) == generation:
                conn.execute('DELETE FROM refresh WHERE employee=?', (employee,))
                conn.execute('DELETE FROM cache WHERE key=?', ('refresh-pending-since:' + employee,))
            else:
                conn.execute('UPDATE refresh SET due=MAX(due,?) WHERE employee=?', (now + coalesce_seconds, employee))

    def publish_feed(self, employee, version, count, now):
        """Atomically publish metadata, record observation and queue notification."""
        with self.connect() as conn:
            return self._publish_feed(conn, employee, version, count, now)

    def _publish_feed(self, conn, employee, version, count, now, *, scoped_retention=False):
        """Existing-transaction form, used by atomic availability packet import."""
        old = conn.execute('SELECT value FROM cache WHERE key=?', ('feed-hash:' + employee,)).fetchone()
        latest = conn.execute('SELECT id FROM availability_observations WHERE employee=? ORDER BY id DESC LIMIT 1', (employee,)).fetchone()
        changed = not old or json.loads(old['value']) != version
        if not changed and latest:
            return False
        kind = 'change' if old and latest else 'baseline'
        conn.execute('INSERT INTO availability_observations(employee,version,kind,ready) VALUES(?,?,?,?)',
                     (employee, version, kind, now))
        for key, value in [('feed-hash:' + employee, version),
                           ('feed-ready:' + employee, {'version': version, 'events': count})]:
            conn.execute('INSERT OR REPLACE INTO cache VALUES(?,?,?)', (key, json.dumps(value), now))
        self._refresh(conn, employee, now)
        # Packet import must not prune another employee's history.
        clause, params = ('employee=? AND ', (employee,)) if scoped_retention else ('', ())
        conn.execute('DELETE FROM availability_observations WHERE ' + clause + 'ready<? AND id NOT IN '
                     '(SELECT MAX(id) FROM availability_observations GROUP BY employee)', (*params, now-7*86400))
        return True

    def observe_feed_fetch(self, employee, version, count, now=None):
        now = time.time() if now is None else now
        with self.connect() as conn:
            conn.execute('INSERT OR REPLACE INTO cache VALUES(?,?,?)',
                         ('feed-last-served:' + employee, json.dumps({'events': count, 'version': version}), now))
            conn.execute('UPDATE availability_observations SET fetched=COALESCE(fetched,?) WHERE id='
                         '(SELECT MAX(id) FROM availability_observations WHERE employee=? AND version=? AND ready<=?)',
                         (now, employee, version, now))

    def latest_feed_observation(self, employee, version):
        rows = self.rows('SELECT id FROM availability_observations WHERE employee=? AND version=? ORDER BY id DESC LIMIT 1',
                         (employee, version))
        return rows[0]['id'] if rows else None

    def retry(self, event):
        with self.connect() as c:
            row = c.execute("SELECT * FROM events WHERE id=? AND state IN ('review','dead')", (event,)).fetchone()
            if not row:
                raise Review('event_not_retryable')
            intent = c.execute("SELECT state FROM intents WHERE booking=?", (row['booking'],)).fetchone()
            if intent and intent['state'] != 'done':
                raise Review('reconcile_intent_before_retry')
            c.execute("UPDATE events SET state='queued',attempts=0,due=0,reason=NULL WHERE id=?", (event,))
            c.execute('INSERT INTO audit VALUES(?,?,?)', (time.time(), 'retry', event))

    def recover(self):
        self.execute("UPDATE events SET state='queued' WHERE state='working'")

    def backup(self, destination):
        # SQLite online backup includes WAL; copying only bridge.sqlite is unsafe.
        # Connection's context manager commits/rolls back; it does not close.
        # Close both handles now so WAL/SHM lifetime never depends on Python GC.
        with closing(sqlite3.connect(self.path)) as source, closing(sqlite3.connect(destination)) as dest:
            with source, dest:
                source.backup(dest)
