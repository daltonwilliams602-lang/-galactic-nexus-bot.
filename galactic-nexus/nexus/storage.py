"""Transactional SQLite state, immutable audit history, and restart-safe work queue."""
from contextlib import closing, contextmanager
from pathlib import Path
import json
import os
import sqlite3
import time
import uuid


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path), isolation_level=None, timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            INSERT OR IGNORE INTO metadata VALUES('schema_version','1');
            CREATE TABLE IF NOT EXISTS objects(kind TEXT,id TEXT,data TEXT NOT NULL,
                PRIMARY KEY(kind,id));
            CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT,
                at REAL NOT NULL,actor TEXT NOT NULL,action TEXT NOT NULL,target TEXT NOT NULL,
                before_state TEXT NOT NULL,after_state TEXT NOT NULL,reason TEXT NOT NULL);
            CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
                BEGIN SELECT RAISE(ABORT,'Audit history is immutable'); END;
            CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
                BEGIN SELECT RAISE(ABORT,'Audit history must not be deleted'); END;
            CREATE TABLE IF NOT EXISTS receipts(key TEXT PRIMARY KEY,at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS outbox(id TEXT PRIMARY KEY,kind TEXT NOT NULL,
                payload TEXT NOT NULL,delivered INTEGER NOT NULL DEFAULT 0,
                attempts INTEGER NOT NULL DEFAULT 0,last_error TEXT NOT NULL DEFAULT '');
        """)
        if self.db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0] != '1':
            raise RuntimeError('Unknown database schema; refuse to alter it. Back up and migrate explicitly.')
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def get(self, kind, ident, default=None):
        row = self.db.execute("SELECT data FROM objects WHERE kind=? AND id=?", (kind, str(ident))).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, kind, ident, value):
        self.db.execute("INSERT INTO objects VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET data=excluded.data",
                        (kind, str(ident), encode(value)))

    def all(self, kind):
        return {r['id']: json.loads(r['data']) for r in self.db.execute("SELECT id,data FROM objects WHERE kind=?", (kind,))}

    def seen(self, key, now=None):
        """Atomically consume an idempotency key; true means it was already seen."""
        cursor = self.db.execute("INSERT OR IGNORE INTO receipts VALUES(?,?)", (key, time.time() if now is None else now))
        return cursor.rowcount == 0

    def log(self, actor, action, target, before, after, reason, now=None):
        self.db.execute("INSERT INTO audit(at,actor,action,target,before_state,after_state,reason) VALUES(?,?,?,?,?,?,?)",
            (time.time() if now is None else now, str(actor), action, str(target), encode(before), encode(after), reason))

    def enqueue(self, kind, payload, ident=None):
        ident = ident or uuid.uuid4().hex
        self.db.execute("INSERT OR IGNORE INTO outbox(id,kind,payload) VALUES(?,?,?)", (ident, kind, encode(payload)))
        return ident

    def backup(self, folder):
        target = Path(folder) / f"{self.path.stem}-{time.time_ns()}.sqlite3"
        target.parent.mkdir(parents=True, exist_ok=True)
        # A Connection's own context manager commits/rolls back; it does not
        # close the handle. Explicit closing is required for Windows file locks.
        with closing(sqlite3.connect(target)) as copy:
            self.db.backup(copy)
            if copy.execute("PRAGMA integrity_check").fetchone()[0] != 'ok':
                raise RuntimeError('Backup integrity check failed; retain the source and investigate.')
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
        return target

    def close(self):
        self.db.close()
