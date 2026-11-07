import json
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from agent_trader.runtime.store import Store, dumps, owner_is_dead, process_owner


def test_live_job_claim_is_exclusive_across_connections(tmp_path):
    path = tmp_path / "jobs.sqlite3"

    def claim():
        store = Store(path)
        try:
            return store.job_start("research-probe:exclusive")
        finally:
            store.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: claim(), range(2)))
    assert sorted(results) == [False, True]
    store = Store(path)
    try:
        assert store.rows("SELECT attempts FROM jobs")[0]["attempts"] == 1
        assert store.recover_jobs() == 0
        assert not store.job_start("research-probe:exclusive")
    finally:
        store.close()


def test_recovery_is_scoped_to_dead_supervisor_and_live_probe_is_untouched(tmp_path):
    path = tmp_path / "jobs.sqlite3"
    code = """
import sys
from pathlib import Path
from agent_trader.runtime.store import Store, process_owner
s = Store(Path(sys.argv[1]))
s.job_owner = process_owner('supervisor')
assert s.job_start('research:orphan')
s.job_owner = process_owner('independent')
assert s.job_start('research-probe:orphan')
s.close()
"""
    subprocess.run([sys.executable, "-c", code, str(path)], check=True)
    probe = Store(path)
    daemon = Store(path)
    try:
        assert probe.job_start("research-probe:active")
        daemon.job_owner = process_owner("supervisor")
        assert daemon.recover_jobs() == 1
        states = {r["key"]: r["state"] for r in daemon.rows("SELECT key,state FROM jobs")}
        assert states == {
            "research:orphan": "failed",
            "research-probe:orphan": "running",
            "research-probe:active": "running",
        }
        assert daemon.job_start("research:orphan")
        # A retried probe may explicitly reclaim its own dead process's key.
        assert probe.job_start("research-probe:orphan")
        assert not daemon.job_start("research-probe:active")
        assert probe.job_end("research-probe:active", True, {"finished": True})
    finally:
        daemon.close()
        probe.close()


def test_pid_reuse_and_prior_boot_prove_old_owner_dead_without_age():
    owner = process_owner("supervisor")
    assert owner["boot_id"] and owner["start_ticks"]
    assert not owner_is_dead(owner)
    assert owner_is_dead({**owner, "start_ticks": str(int(owner["start_ticks"]) + 1)})
    assert owner_is_dead({**owner, "boot_id": "previous-boot"})
    for unknown in ({}, None, {"pid": owner["pid"]}, {"pid": -1}):
        assert not owner_is_dead(unknown)


def test_stale_claim_cannot_complete_reassigned_job(store):
    assert store.job_start("research:claim")
    owner = json.loads(store.rows("SELECT owner FROM jobs")[0]["owner"])
    store.db.execute("UPDATE jobs SET owner=? WHERE key=?", (
        dumps({**owner, "claim": "different-owner-claim"}), "research:claim",
    ))
    assert not store.job_end("research:claim", True, {"stale": True})
    row = store.rows("SELECT state,result FROM jobs")[0]
    assert row == {"state": "running", "result": None}


def test_legacy_schema_migrates_without_abandoning_unowned_running_jobs(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE jobs(key TEXT PRIMARY KEY,state TEXT,attempts INTEGER,at TEXT,result TEXT)")
    db.execute("INSERT INTO jobs VALUES('legacy-running','running',1,'2000-01-01',NULL)")
    db.execute("INSERT INTO jobs VALUES('legacy-failed','failed',1,'2000-01-01',NULL)")
    db.commit()
    db.close()
    store = Store(path)
    try:
        store.job_owner = process_owner("supervisor")
        assert "owner" in {r["name"] for r in store.rows("PRAGMA table_info(jobs)")}
        assert store.recover_jobs() == 0
        assert not store.job_start("legacy-running")
        assert store.job_start("legacy-failed")
        assert store.job_end("legacy-failed", True, {})
    finally:
        store.close()


def test_supervisor_backoff_cannot_reset_independent_retry_limits(store):
    store.job_owner = process_owner("independent")
    for _ in range(2):
        assert store.job_start("research-probe:bounded")
        assert store.job_end("research-probe:bounded", False, {})
    store.job_owner = process_owner("supervisor")
    for _ in range(2):
        assert store.job_start("research:retry")
        assert store.job_end("research:retry", False, {})
    store.db.execute("UPDATE jobs SET at='2000-01-01'")
    assert store.retry_failed_jobs("2026-01-01") == 1
    assert store.job_start("research:retry")
    assert not store.job_start("research-probe:bounded")


def test_supervisor_startup_preserves_an_active_independent_probe(config, broker, monkeypatch):
    from agent_trader.runtime import supervisor

    monkeypatch.setattr(supervisor, "Broker", lambda _: broker)
    monkeypatch.setattr(supervisor.signal, "signal", lambda *args: None)
    instance = supervisor.Supervisor(config)
    probe = Store(config.state_dir / "trader.sqlite3")
    try:
        assert probe.job_start("research-probe:active-at-daemon-start")
        original = probe.rows("SELECT owner FROM jobs")[0]["owner"]
        monkeypatch.setattr(instance, "tick", lambda: setattr(instance, "stopping", True))
        instance.run()
        assert instance.store.job_owner["kind"] == "supervisor"
        assert probe.rows("SELECT state,owner FROM jobs")[0] == {
            "state": "running", "owner": original,
        }
        assert probe.job_end("research-probe:active-at-daemon-start", True, {})
    finally:
        instance.pool.shutdown(wait=False)
        instance.publisher_pool.shutdown(wait=False)
        instance.store.close()
        probe.close()


def test_capped_owner_that_dies_after_startup_enters_scoped_backoff(store):
    store.job_owner = process_owner("supervisor")
    assert store.job_start("research:shutdown")
    assert store.job_end("research:shutdown", False, {})
    assert store.job_start("research:shutdown")
    assert store.recover_jobs() == 0  # Shutdown owner was still alive at daemon startup.
    assert not store.job_start("research:shutdown")
    row = store.rows("SELECT * FROM jobs")[0]
    prior_owner = json.loads(row["owner"])
    dead_owner = {**prior_owner, "start_ticks": str(int(prior_owner["start_ticks"]) + 1)}
    store.db.execute("UPDATE jobs SET owner=? WHERE key=?", (
        dumps(dead_owner), "research:shutdown",
    ))
    assert not store.job_start("research:shutdown")
    recovered = store.rows("SELECT * FROM jobs")[0]
    assert recovered["state"] == "failed" and recovered["attempts"] == 2
    assert json.loads(recovered["result"])["error_type"] == "OwnerInterrupted"
    now = datetime.now(timezone.utc)
    assert store.retry_failed_jobs((now - timedelta(minutes=30)).isoformat()) == 0
    assert store.retry_failed_jobs((now + timedelta(minutes=30)).isoformat()) == 1
    assert store.job_start("research:shutdown")


def test_daemon_cannot_recover_or_reset_dead_independent_job_caps(store):
    store.job_owner = process_owner("independent")
    assert store.job_start("research-probe:capped")
    assert store.job_end("research-probe:capped", False, {})
    assert store.job_start("research-probe:capped")
    row = store.rows("SELECT * FROM jobs")[0]
    owner = json.loads(row["owner"])
    store.db.execute("UPDATE jobs SET owner=?,at='2000-01-01'", (
        dumps({**owner, "boot_id": "prior-boot"}),
    ))
    store.job_owner = process_owner("supervisor")
    assert store.recover_jobs() == 0
    assert not store.job_start("research-probe:capped")
    assert store.retry_failed_jobs("2099-01-01") == 0
    unchanged = store.rows("SELECT state,attempts FROM jobs")[0]
    assert unchanged == {"state": "running", "attempts": 2}
