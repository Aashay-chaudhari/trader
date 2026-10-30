from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def dumps(value):
    return json.dumps(value, default=str, allow_nan=False)


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.db = sqlite3.connect(path, timeout=30, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        PRAGMA journal_mode=WAL;
        PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events(
          id INTEGER PRIMARY KEY, at TEXT NOT NULL, kind TEXT NOT NULL,
          branch TEXT, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS jobs(
          key TEXT PRIMARY KEY, state TEXT NOT NULL, attempts INTEGER DEFAULT 0,
          at TEXT NOT NULL, result TEXT);
        CREATE TABLE IF NOT EXISTS plans(
          id TEXT PRIMARY KEY, day TEXT, branch TEXT, state TEXT, payload TEXT);
        CREATE TABLE IF NOT EXISTS orders(
          client_id TEXT PRIMARY KEY, broker_id TEXT UNIQUE, branch TEXT NOT NULL,
          symbol TEXT NOT NULL, side TEXT NOT NULL, qty REAL NOT NULL,
          status TEXT NOT NULL, filled REAL DEFAULT 0, notional REAL DEFAULT 0,
          plan_id TEXT, payload TEXT NOT NULL, at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS holdings(
          symbol TEXT PRIMARY KEY, branch TEXT NOT NULL, qty REAL NOT NULL,
          cost REAL NOT NULL, plan_id TEXT);
        CREATE TABLE IF NOT EXISTS branches(
          name TEXT PRIMARY KEY, cash REAL NOT NULL, high_water REAL NOT NULL,
          paused INTEGER DEFAULT 0, pause_reason TEXT DEFAULT '');
        CREATE TABLE IF NOT EXISTS equity(
          id INTEGER PRIMARY KEY, at TEXT, day TEXT, branch TEXT, value REAL,
          UNIQUE(day,branch,at));
        CREATE TABLE IF NOT EXISTS experiments(
          id TEXT PRIMARY KEY, branch TEXT, state TEXT, payload TEXT, at TEXT);
        CREATE TABLE IF NOT EXISTS shadow(
          id TEXT PRIMARY KEY, experiment TEXT, symbol TEXT, branch TEXT,
          state TEXT, payload TEXT);
        CREATE TABLE IF NOT EXISTS memory(
          id TEXT PRIMARY KEY, layer TEXT, expires TEXT, payload TEXT, at TEXT);
        CREATE TABLE IF NOT EXISTS usage(
          id INTEGER PRIMARY KEY, at TEXT, day TEXT, role TEXT, model TEXT,
          input_tokens INTEGER, cached_tokens INTEGER, output_tokens INTEGER,
          quota_delta REAL, payload TEXT);
        CREATE TABLE IF NOT EXISTS cohort_observations(
          id TEXT PRIMARY KEY, day TEXT, branch TEXT, rule TEXT, symbol TEXT,
          state TEXT, payload TEXT);
        CREATE INDEX IF NOT EXISTS cohort_open ON cohort_observations(state,branch,rule,symbol);
        CREATE TABLE IF NOT EXISTS cohort_expected(
          id TEXT PRIMARY KEY, day TEXT, branch TEXT, rule TEXT, symbol TEXT, payload TEXT);
        CREATE TABLE IF NOT EXISTS session_health(
          day TEXT, slot INTEGER, at TEXT, broker_confirmed INTEGER,
          research_ready INTEGER, PRIMARY KEY(day,slot));
        """)
        for name in ("intraday", "swing", "options"):
            self.db.execute(
                "INSERT OR IGNORE INTO branches(name,cash,high_water) VALUES(?,10000,10000)",
                (name,),
            )

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def rows(self, sql, args=()):
        return [dict(r) for r in self.db.execute(sql, args)]

    def get(self, key, default=None):
        row = self.db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO kv VALUES(?,?)", (key, dumps(value)))

    def event(self, kind, payload, branch=None):
        self.db.execute(
            "INSERT INTO events(at,kind,branch,payload) VALUES(?,?,?,?)",
            (utc_now(), kind, branch, dumps(payload)),
        )

    def job_start(self, key, retry_limit=2):
        with self.transaction():
            row = self.db.execute("SELECT * FROM jobs WHERE key=?", (key,)).fetchone()
            if row and (row["state"] == "done" or row["attempts"] >= retry_limit):
                return False
            self.db.execute(
                """INSERT INTO jobs(key,state,attempts,at) VALUES(?,'running',1,?)
              ON CONFLICT(key) DO UPDATE SET state='running', attempts=attempts+1, at=excluded.at""",
                (key, utc_now()),
            )
        return True

    def job_end(self, key, success, result):
        self.db.execute(
            "UPDATE jobs SET state=?,result=?,at=? WHERE key=?",
            ("done" if success else "failed", dumps(result), utc_now(), key),
        )

    def recover_jobs(self):
        self.db.execute("UPDATE jobs SET state='failed' WHERE state='running'")

    def retry_failed_jobs(self, before):
        cursor = self.db.execute(
            "UPDATE jobs SET state='retry',attempts=0 WHERE state='failed' AND attempts>=2 AND at<?",
            (before,),
        )
        return cursor.rowcount

    def memory_put(self, key, layer, payload, expires=None):
        if expires:
            stamp = datetime.fromisoformat(expires.replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                raise ValueError("Memory expiry requires a timezone")
            expires = stamp.astimezone(timezone.utc).isoformat()
        self.db.execute(
            "INSERT OR REPLACE INTO memory VALUES(?,?,?,?,?)",
            (key, layer, expires, dumps(payload), utc_now()),
        )

    def close(self):
        self.db.close()
