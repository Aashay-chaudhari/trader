from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def dumps(value):
    return json.dumps(value, default=str, allow_nan=False)


def process_owner(kind="independent"):
    """Identify a process without treating a reused PID as the original owner."""
    owner = {"kind": kind, "pid": os.getpid()}
    try:
        owner["boot_id"] = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        owner["start_ticks"] = (
            Path(f"/proc/{owner['pid']}/stat").read_text().rsplit(")", 1)[1].split()[19]
        )
    except (OSError, IndexError):
        # Unsupported/hidden process metadata means unknown, never presumed dead.
        pass
    return owner


def owner_is_dead(owner):
    if not isinstance(owner, dict):
        return False
    pid = owner.get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    if not owner.get("boot_id") or not owner.get("start_ticks"):
        return False
    try:
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        if boot_id != owner["boot_id"]:
            return True
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return fields[19] != str(owner["start_ticks"]) or fields[0] == "Z"
    except FileNotFoundError:
        # A missing process proves death only after the current boot was read.
        return "boot_id" in locals()
    except (OSError, IndexError):
        return False


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.job_owner = process_owner()
        self._job_claims = {}
        self.db = sqlite3.connect(path, timeout=30, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        # Two first-time openers can contend while switching an empty database
        # to WAL; SQLite may reject this lock upgrade without invoking its busy
        # timeout. Retry only that bounded transient, never silently fall back.
        for attempt in range(6):
            try:
                mode = self.db.execute("PRAGMA journal_mode=WAL").fetchone()[0]
                if mode != "wal":
                    raise sqlite3.OperationalError("WAL journal mode is required")
                break
            except sqlite3.OperationalError as exc:
                if getattr(exc, "sqlite_errorcode", None) not in (
                    sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED
                ) or attempt == 5:
                    self.db.close()
                    raise
                time.sleep(0.01 * 2 ** attempt)
        self.db.executescript("""
        PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events(
          id INTEGER PRIMARY KEY, at TEXT NOT NULL, kind TEXT NOT NULL,
          branch TEXT, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS jobs(
          key TEXT PRIMARY KEY, state TEXT NOT NULL, attempts INTEGER DEFAULT 0,
          at TEXT NOT NULL, result TEXT, owner TEXT);
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
        # Additive migration under one write lock: other worker/probe connections
        # may open the same database while a release is starting.
        with self.transaction():
            columns = {r["name"] for r in self.db.execute("PRAGMA table_info(jobs)")}
            if "owner" not in columns:
                self.db.execute("ALTER TABLE jobs ADD COLUMN owner TEXT")
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
            if row and row["state"] == "done":
                return False
            if row and row["state"] == "running":
                try:
                    prior_owner = json.loads(row["owner"]) if row["owner"] else None
                except (TypeError, ValueError):
                    prior_owner = None
                if (
                    not owner_is_dead(prior_owner)
                    or prior_owner.get("kind") != self.job_owner.get("kind")
                ):
                    return False
                # Startup may have observed this owner alive while it was
                # finishing shutdown. Once it is proven dead, even a capped
                # attempt must leave running state so scoped backoff can act.
                self.db.execute(
                    "UPDATE jobs SET state='failed',result=?,at=? WHERE key=? AND owner=?",
                    (dumps({"error_type": "OwnerInterrupted", "recovery": "owner_process_absent"}),
                     utc_now(), key, row["owner"]),
                )
            if row and row["attempts"] >= retry_limit:
                return False
            owner = {**self.job_owner, "claim": str(uuid4())}
            encoded_owner = dumps(owner)
            self.db.execute(
                """INSERT INTO jobs(key,state,attempts,at,owner) VALUES(?,'running',1,?,?)
              ON CONFLICT(key) DO UPDATE SET state='running', attempts=attempts+1,
              at=excluded.at, owner=excluded.owner, result=NULL""",
                (key, utc_now(), encoded_owner),
            )
            self._job_claims[key] = encoded_owner
        return True

    def job_end(self, key, success, result):
        owner = self._job_claims.pop(key, None)
        if owner is None:
            return False
        cursor = self.db.execute(
            "UPDATE jobs SET state=?,result=?,at=? WHERE key=? AND state='running' AND owner=?",
            ("done" if success else "failed", dumps(result), utc_now(), key, owner),
        )
        return bool(cursor.rowcount)

    def recover_jobs(self, owner_kind="supervisor"):
        recovered = 0
        with self.transaction():
            for row in self.db.execute("SELECT key,owner FROM jobs WHERE state='running'"):
                try:
                    owner = json.loads(row["owner"]) if row["owner"] else None
                except (TypeError, ValueError):
                    owner = None
                if not isinstance(owner, dict) or owner.get("kind") != owner_kind:
                    continue
                if owner_is_dead(owner):
                    self.db.execute(
                        "UPDATE jobs SET state='failed',result=?,at=? WHERE key=? AND owner=?",
                        (dumps({"error_type": "OwnerInterrupted", "recovery": "owner_process_absent"}),
                         utc_now(), row["key"], row["owner"]),
                    )
                    recovered += 1
        return recovered

    def retry_failed_jobs(self, before):
        # Independent probes/audits own their explicit retry paths. The daemon
        # cannot reset their attempt limits just because its timer is running.
        scope = self.job_owner.get("kind")
        scope_sql = " AND json_extract(owner,'$.kind')=?" if scope == "supervisor" else ""
        cursor = self.db.execute(
            "UPDATE jobs SET state='retry',attempts=0 WHERE state='failed' AND attempts>=2 AND at<?"
            + scope_sql,
            (before, scope) if scope_sql else (before,),
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
