"""Read-only, coherent reporting and explicit unknown valuation inputs."""

import json
import sqlite3
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from agent_trader.runtime import project
from agent_trader.runtime.config import ET
from agent_trader.runtime.publish import _number, snapshot


def reconciled(store, equity=30000):
    store.set("account", {"equity": str(equity), "cash": str(equity)})
    store.set("last_reconciled", datetime.now(timezone.utc).isoformat())
    store.set("reconciled", True)


def test_snapshot_is_one_wal_read_without_blocking_atomic_writer(config, store, monkeypatch):
    reconciled(store)
    writer = sqlite3.connect(store.path, isolation_level=None, timeout=0.1)
    read = store.rows
    changed = False

    def rows(sql, args=()):
        nonlocal changed
        result = read(sql, args)
        if sql == "SELECT * FROM branches" and not changed:
            changed = True
            writer.execute("BEGIN IMMEDIATE")
            writer.execute("UPDATE branches SET cash=9999 WHERE name='intraday'")
            writer.execute("UPDATE kv SET value=? WHERE key='account'", (json.dumps({"equity": "29999", "cash": "29999"}),))
            writer.execute("COMMIT")
        return result

    monkeypatch.setattr(store, "rows", rows)
    try:
        old = snapshot(config, store)
        new = snapshot(config, store)
    finally:
        writer.close()
    assert changed
    assert old["accounting"]["broker_equity"] == old["accounting"]["branch_ledger_equity"] == 30000
    assert new["accounting"]["broker_equity"] == new["accounting"]["branch_ledger_equity"] == 29999
    assert old["accounting"]["unattributed_equity_difference"] == new["accounting"]["unattributed_equity_difference"] == 0
    assert not store.db.in_transaction


@pytest.mark.parametrize("query_only", [0, 1])
def test_fresh_schema_snapshot_executes_no_ddl_or_writes(config, store, query_only):
    before = store.rows("SELECT name FROM sqlite_master ORDER BY name")
    changes = store.db.total_changes
    statements = []
    store.db.execute(f"PRAGMA query_only={query_only}")
    store.db.set_trace_callback(statements.append)
    try:
        result = snapshot(config, store)
    finally:
        store.db.set_trace_callback(None)
    assert result["adaptive_lab"]["trials"] == []
    assert result["adaptive_lab"]["trial_count"] == 0
    assert store.rows("SELECT name FROM sqlite_master ORDER BY name") == before
    assert store.db.total_changes == changes
    assert not any(sql.lstrip().upper().startswith(("CREATE", "INSERT", "UPDATE", "DELETE", "ALTER")) for sql in statements)
    assert store.db.execute("PRAGMA query_only").fetchone()[0] == query_only
    assert not store.db.in_transaction
    store.db.execute("PRAGMA query_only=OFF")


def test_snapshot_works_with_a_read_only_database_adapter(config, store):
    connection = sqlite3.connect("file:" + str(store.path) + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row

    def get(key, default=None):
        row = connection.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    reader = SimpleNamespace(db=connection, get=get, rows=lambda sql, args=(): [dict(r) for r in connection.execute(sql, args)])
    try:
        result = snapshot(config, reader)
        assert result["adaptive_lab"]["trials"] == []
        assert result["account_activity"]["observed_at"] is None
        assert not connection.in_transaction
    finally:
        connection.close()


@pytest.mark.parametrize("failure", [False, True])
def test_snapshot_never_finishes_caller_transaction(config, store, monkeypatch, failure):
    original = project.project_snapshot

    def project_result(*args):
        if failure:
            raise ValueError("Injected reporting failure")
        return original(*args)

    monkeypatch.setattr(project, "project_snapshot", project_result)
    store.db.execute("BEGIN IMMEDIATE")
    store.set("caller-owned", True)
    try:
        if failure:
            with pytest.raises(ValueError, match="reporting failure"):
                snapshot(config, store)
        else:
            snapshot(config, store)
        assert store.db.in_transaction
        assert store.get("caller-owned") is True
        assert store.db.execute("PRAGMA query_only").fetchone()[0] == 0
        store.set("caller-continues", True)
    finally:
        store.db.execute("ROLLBACK")
    assert store.get("caller-owned") is None and store.get("caller-continues") is None


def test_own_read_scope_rolls_back_after_exception_and_restores_write_mode(config, store, monkeypatch):
    def fail(*args):
        raise ValueError("Injected snapshot failure")

    monkeypatch.setattr(project, "project_snapshot", fail)
    with pytest.raises(ValueError, match="snapshot failure"):
        snapshot(config, store)
    assert not store.db.in_transaction
    store.set("can-write-after-read", True)
    assert store.get("can-write-after-read") is True


@pytest.mark.parametrize("failed_statement", ["ROLLBACK", "PRAGMA query_only=0"])
def test_snapshot_cleanup_failure_preserves_original_error(config, store, monkeypatch, failed_statement):
    connection = store.db

    class FailingCleanup:
        def __getattr__(self, name):
            return getattr(connection, name)

        def execute(self, sql, *args):
            if sql == failed_statement:
                raise sqlite3.OperationalError("Injected read cleanup failure")
            return connection.execute(sql, *args)

    def fail(*args):
        raise ValueError("Original reporting failure")

    monkeypatch.setattr(store, "db", FailingCleanup())
    monkeypatch.setattr(project, "project_snapshot", fail)
    try:
        with pytest.raises(ValueError, match="Original reporting failure") as caught:
            snapshot(config, store)
        assert any("Snapshot cleanup failed" in note for note in caught.value.__notes__)
    finally:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        connection.execute("PRAGMA query_only=OFF")


def test_overflowed_aggregate_mark_is_unknown_and_snapshot_stays_json_safe(config, store):
    assert _number(10 ** 1000) is None
    reconciled(store)
    for symbol in ("FIRST", "SECOND"):
        store.db.execute("INSERT INTO holdings VALUES(?,'intraday',1,100,'example')", (symbol,))
    store.set("broker_positions", [
        {"symbol": symbol, "qty": "1", "market_value": "1e308"}
        for symbol in ("FIRST", "SECOND")
    ])
    result = snapshot(config, store)
    assert all(position["market_value"] == 1e308 for position in result["positions"])
    assert result["branches"][0]["equity"] is None
    assert result["accounting"]["branch_ledger_equity"] is None
    assert result["accounting"]["unattributed_equity_difference"] is None
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("mark", [None, {}, {"market_value": None, "qty": "1"}, {"market_value": "nan", "qty": "1"}, {"market_value": "120", "qty": "2"}])
def test_unknown_or_mismatched_position_mark_propagates_to_branch_totals(config, store, mark):
    reconciled(store)
    store.db.execute("UPDATE branches SET cash=9900 WHERE name='intraday'")
    store.db.execute("INSERT INTO holdings VALUES('FAKE','intraday',1,100,'example')")
    store.set("broker_positions", [] if mark is None else [{"symbol": "FAKE", **mark}])
    result = snapshot(config, store)
    position, branch = result["positions"][0], result["branches"][0]
    assert position["market_value"] is None and position["unrealized_pnl"] is None
    assert position["cost"] == 100
    assert all(branch[field] is None for field in ("equity", "daily_pnl", "total_pnl", "drawdown"))
    assert result["accounting"]["branch_ledger_equity"] is None
    assert result["accounting"]["unattributed_equity_difference"] is None


def test_unreconciled_marks_do_not_become_current_valuations(config, store):
    reconciled(store, 29900)
    store.set("reconciled", False)
    store.db.execute("INSERT INTO holdings VALUES('FAKE','intraday',1,100,'example')")
    store.set("broker_positions", [{"symbol": "FAKE", "qty": "1", "market_value": "120"}])
    result = snapshot(config, store)
    assert result["positions"][0]["market_value"] is None
    assert result["objective_scorecard"]["portfolio"]["equity"] is None
    assert result["accounting"]["broker_equity"] == 29900  # Retained receipt, explicitly unreconciled.
    assert result["accounting"]["reconciled"] is False
    assert result["execution_quality"]["illustrative_equity_after_allowance"] is None


def test_valid_marks_and_zero_unrealized_return_remain_measured(config, store):
    reconciled(store)
    store.db.execute("UPDATE branches SET cash=9900 WHERE name='intraday'")
    store.db.execute("INSERT INTO holdings VALUES('FAKE','intraday',1,100,'example')")
    store.set("broker_positions", [{"symbol": "FAKE", "qty": "1", "market_value": "100"}])
    result = snapshot(config, store)
    assert result["positions"][0]["market_value"] == 100
    assert result["positions"][0]["unrealized_pnl"] == 0
    assert result["branches"][0]["equity"] == 10000


def test_missing_today_baseline_is_not_replaced_by_initial_capital(config, store):
    reconciled(store, 29900)
    store.db.execute("UPDATE branches SET cash=9900 WHERE name='intraday'")
    branch = snapshot(config, store)["branches"][0]
    assert branch["total_pnl"] == -100
    assert branch["start_of_day_equity"] is None and branch["daily_pnl"] is None
    day = datetime.now(ET).date().isoformat()
    store.set(f"sod:{day}:intraday", 9890)
    branch = snapshot(config, store)["branches"][0]
    assert branch["daily_pnl"] == 10 and branch["start_of_day_equity"] == 9890
