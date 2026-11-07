import copy
import json
import sqlite3
from contextlib import closing
from datetime import timedelta

import pytest

from agent_trader.runtime.engine import EXECUTION_KERNEL, Engine, current_execution_verified
from agent_trader.runtime.store import Store, dumps


def bracket(*, take_filled=0, stop_filled=0, stop_qty=10):
    def order(name, side, filled, price, kind, qty=10):
        return {
            "id": name,
            "client_order_id": "client-" + name,
            "symbol": "AAPL",
            "side": side,
            "qty": str(qty),
            "filled_qty": str(filled),
            "filled_avg_price": str(price) if filled else None,
            "status": "filled" if filled == qty else "partially_filled" if filled else "new",
            "type": kind,
        }

    parent = order("entry", "buy", 10, 100, "limit")
    parent["order_class"] = "bracket"
    parent["legs"] = [
        order("take", "sell", take_filled, 110, "limit"),
        order("stop", "sell", stop_filled, 90, "stop", stop_qty),
    ]
    return parent


def ledger(store):
    return {
        table: store.rows("SELECT * FROM " + table + " ORDER BY 1")
        for table in ("orders", "holdings", "branches", "equity")
    }


def fill_events(store):
    return store.rows("SELECT * FROM events WHERE kind='fill'")


def reject_receipts(store):
    return store.rows("SELECT * FROM kv WHERE key LIKE 'broker-order-rejection:%'")


@pytest.mark.parametrize(
    "change",
    [
        lambda p: p["legs"][0].update(symbol="MSFT"),
        lambda p: p["legs"][0].update(side="buy"),
        lambda p: p["legs"][0].update(qty="11"),
        lambda p: p["legs"][0].update(qty=True),
        lambda p: p["legs"][0].update(filled_qty="nan"),
        lambda p: p["legs"][0].update(id="entry"),
        lambda p: p["legs"][0].update(client_order_id="client-entry"),
        lambda p: p["legs"].append(p),
        lambda p: p["legs"][0].update(legs=[p]),
        lambda p: p["legs"].append(copy.deepcopy(p["legs"][0])),
        lambda p: p["legs"][0].update(type="market"),
        lambda p: p["legs"][1].update(type="limit"),
        lambda p: p.update(order_class="oco"),
        lambda p: p.update(side="sell"),
        lambda p: p.update(legs={"unexpected": "shape"}),
    ],
    ids=[
        "foreign-symbol",
        "buy-child",
        "oversized-child",
        "boolean-quantity",
        "nonfinite-fill",
        "duplicate-broker-id",
        "duplicate-client-id",
        "parent-cycle",
        "nested-cycle",
        "third-child",
        "unsupported-child-type",
        "duplicate-role",
        "unsupported-parent-class",
        "sell-parent",
        "malformed-legs",
    ],
)
def test_entire_malformed_receipt_is_rejected_without_ledger_mutation(
    store, broker, config, change
):
    engine = Engine(config, store, broker)
    receipt = bracket()
    change(receipt)
    before = ledger(store)
    store.set("reconciled", True)
    for _ in range(2):
        with pytest.raises(ValueError):
            engine.ingest_order(receipt, "intraday", "plan")
        assert ledger(store) == before
        assert not fill_events(store)
    assert store.get("reconciled") is False
    assert len(reject_receipts(store)) == 1
    assert len(store.rows("SELECT * FROM events WHERE kind='order_receipt_rejected'")) == 1
    assert broker.submissions == 0


def test_partial_overfill_cannot_commit_parent_or_first_sibling(store, broker, config):
    engine = Engine(config, store, broker)
    before = ledger(store)
    with pytest.raises(ValueError, match="exceed confirmed parent"):
        engine.ingest_order(bracket(take_filled=4, stop_filled=7), "intraday", "plan")
    assert ledger(store) == before
    assert not fill_events(store)
    retained = json.loads(reject_receipts(store)[0]["value"])
    assert retained["order"]["legs"][1]["filled_qty"] == "7"
    assert retained["execution_kernel"] == EXECUTION_KERNEL


def test_invalid_child_preserves_prepared_parent_intent(store, broker, config):
    receipt = bracket()
    store.db.execute(
        "INSERT INTO orders(client_id,branch,symbol,side,qty,status,plan_id,payload,at) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        ("client-entry", "intraday", "AAPL", "buy", 10, "prepared", "plan", "{}", "before"),
    )
    before = ledger(store)
    receipt["legs"][0]["symbol"] = "MSFT"
    with pytest.raises(ValueError):
        Engine(config, store, broker).ingest_order(receipt, "intraday", "plan")
    assert ledger(store) == before
    assert store.rows("SELECT broker_id,status FROM orders") == [
        {"broker_id": None, "status": "prepared"}
    ]


def test_partial_exit_and_broker_stop_resize_replay_after_restart(store, broker, config, tmp_path):
    receipt = bracket(take_filled=4, stop_qty=6)
    engine = Engine(config, store, broker)
    engine.ingest_order(bracket(), "intraday", "plan")
    engine.ingest_order(receipt, "intraday", "plan")
    assert store.rows("SELECT qty,cost FROM holdings") == [{"qty": 6.0, "cost": 600.0}]
    assert store.rows("SELECT cash FROM branches WHERE name='intraday'")[0]["cash"] == 9440
    before = ledger(store)
    with closing(Store(tmp_path / "state.sqlite3")) as restarted:
        Engine(config, restarted, broker).ingest_order(receipt, "intraday", "plan")
        assert ledger(restarted) == before
        assert len(fill_events(restarted)) == 2


def test_later_child_correction_rejects_other_new_fills_in_same_receipt(store, broker, config):
    engine = Engine(config, store, broker)
    initial = bracket(stop_filled=1)
    engine.ingest_order(initial, "intraday", "plan")
    before = ledger(store)
    changed = bracket(take_filled=4, stop_filled=1)
    changed["legs"][1]["filled_avg_price"] = "91"
    with pytest.raises(ValueError, match="corrected fill notional"):
        engine.ingest_order(changed, "intraday", "plan")
    assert ledger(store) == before
    assert len(fill_events(store)) == 2


def test_late_child_write_failure_rolls_back_whole_receipt_then_retry_applies_once(
    store, broker, config
):
    engine = Engine(config, store, broker)
    receipt = bracket(take_filled=4, stop_qty=6)
    before = ledger(store)
    store.db.execute(
        "CREATE TEMP TRIGGER fail_stop BEFORE INSERT ON orders "
        "WHEN NEW.broker_id='stop' BEGIN SELECT RAISE(ABORT,'injected child write failure'); END"
    )
    with pytest.raises(sqlite3.IntegrityError, match="injected child"):
        engine.ingest_order(receipt, "intraday", "plan")
    assert ledger(store) == before
    assert not fill_events(store)
    original_rejection = reject_receipts(store)
    assert len(original_rejection) == 1
    store.db.execute("DROP TRIGGER fail_stop")
    engine.ingest_order(receipt, "intraday", "plan")
    engine.ingest_order(receipt, "intraday", "plan")
    assert len(fill_events(store)) == 2
    assert store.rows("SELECT qty,cost FROM holdings") == [{"qty": 6.0, "cost": 600.0}]
    assert reject_receipts(store) == original_rejection
    assert broker.submissions == 0


def test_resolved_client_identity_collision_is_rejected(store, broker, config):
    receipt = bracket()
    receipt["client_order_id"] = "broker-take"
    del receipt["legs"][0]["client_order_id"]
    with pytest.raises(ValueError, match="resolved broker client"):
        Engine(config, store, broker).ingest_order(receipt, "intraday", "plan")
    assert not store.rows("SELECT * FROM orders")
    assert not fill_events(store)


def test_final_reconcile_failure_rolls_back_all_marks_and_success_then_retries(
    store, broker, config, now
):
    engine = Engine(config, store, broker)
    previous = now - timedelta(days=1)
    assert engine.reconcile(previous)
    store.set("sod:" + now.date().isoformat() + ":intraday", 10300)
    before = ledger(store)
    before_kv = store.rows("SELECT * FROM kv WHERE key != 'reconciled' ORDER BY key")
    store.db.execute(
        "CREATE TEMP TRIGGER fail_equity BEFORE INSERT ON equity "
        "WHEN NEW.branch='swing' BEGIN SELECT RAISE(ABORT,'injected equity failure'); END"
    )
    with pytest.raises(sqlite3.IntegrityError, match="injected equity"):
        engine.reconcile(now)
    assert store.get("reconciled") is False
    assert store.get("last_reconciled") == previous.isoformat()
    assert ledger(store) == before
    assert store.rows("SELECT * FROM kv WHERE key != 'reconciled' ORDER BY key") == before_kv
    store.db.execute("DROP TRIGGER fail_equity")
    assert engine.reconcile(now)
    assert store.get("reconciled") is True
    assert store.get("last_reconciled") == now.isoformat()
    assert len(store.rows("SELECT * FROM equity WHERE at=?", (now.isoformat(),))) == 3
    assert store.rows("SELECT paused FROM branches WHERE name='intraday'")[0]["paused"] == 1


def test_completed_truthful_receipt_survives_later_network_failure_without_double_count(
    store, broker, config, now, monkeypatch
):
    engine = Engine(config, store, broker)
    receipt = bracket()
    receipt.pop("legs")
    pending = {**receipt, "status": "new", "filled_qty": "0", "filled_avg_price": None}
    engine.ingest_order(pending, "intraday", "plan")
    broker.items[receipt["id"]] = receipt
    broker.cash = 29000
    broker.pos = [{"symbol": "AAPL", "qty": "10", "market_value": "1000"}]
    original = broker.account

    def failed_account():
        assert not store.db.in_transaction
        raise TimeoutError("injected late broker failure")

    monkeypatch.setattr(broker, "account", failed_account)
    with pytest.raises(TimeoutError):
        engine.reconcile(now)
    assert store.get("reconciled") is False
    assert store.rows("SELECT qty,cost FROM holdings") == [{"qty": 10.0, "cost": 1000.0}]
    assert len(fill_events(store)) == 1
    assert not store.rows("SELECT * FROM equity")
    monkeypatch.setattr(broker, "account", original)
    assert engine.reconcile(now)
    assert len(fill_events(store)) == 1


def test_prior_kernel_receipt_does_not_certify_atomic_execution_kernel():
    ready = {
        "execution_verified": True,
        "execution_verified_at": "2026-11-02T14:35:37+00:00",
        "required_execution_kernel": EXECUTION_KERNEL,
        "verified_execution_kernel": "paper-execution-20261107-r2",
    }
    original = dumps(ready)
    assert EXECUTION_KERNEL == "paper-execution-20261107-r3"
    assert current_execution_verified(ready) is False
    assert dumps(ready) == original


def unrelated_receipt():
    return {
        "id": "unrelated-root",
        "client_order_id": "unrelated-client",
        "symbol": "MSFT",
        "side": "buy",
        "qty": "100",
        "filled_qty": "100",
        "filled_avg_price": "100",
        "status": "filled",
        "type": "limit",
    }


def intended_entry():
    return {
        "symbol": "AAPL",
        "side": "buy",
        "qty": "1",
        "type": "limit",
        "limit_price": "100",
        "client_order_id": "expected-client",
    }


@pytest.mark.parametrize("route", ["submit", "timeout-recovery", "existing-recovery"])
def test_submit_binds_returned_root_to_persisted_intent(store, broker, config, monkeypatch, route):
    engine = Engine(config, store, broker)
    payload = intended_entry()
    if route == "existing-recovery":
        engine.submit_intent(payload, "intraday", "plan")
        before = ledger(store)
    if route == "submit":
        monkeypatch.setattr(broker, "submit", lambda _: unrelated_receipt())
    elif route == "timeout-recovery":

        def timeout(_):
            raise TimeoutError("uncertain submission")

        monkeypatch.setattr(broker, "submit", timeout)
    monkeypatch.setattr(broker, "by_client", lambda _: unrelated_receipt())
    with pytest.raises(ValueError, match="requested .* identity"):
        engine.submit_intent(payload, "intraday", "plan")
    assert not store.rows("SELECT * FROM holdings")
    assert not fill_events(store)
    assert store.rows("SELECT cash FROM branches WHERE name='intraday'")[0]["cash"] == 10000
    if route == "existing-recovery":
        assert ledger(store) == before
    else:
        assert store.rows("SELECT client_id,broker_id,status FROM orders") == [
            {"client_id": "expected-client", "broker_id": None, "status": "prepared"}
        ]
    assert store.get("reconciled") is False
    evidence = json.loads(reject_receipts(store)[0]["value"])
    assert evidence["expected_root"]["client_id"] == "expected-client"
    assert evidence["order"]["symbol"] == "MSFT"


@pytest.mark.parametrize("route", ["by-client", "by-id", "filled-parent"])
def test_reconcile_binds_each_root_lookup_before_any_ledger_change(
    store, broker, config, now, monkeypatch, route
):
    engine = Engine(config, store, broker)
    payload = intended_entry()
    initial = engine.submit_intent(payload, "intraday", "plan")
    if route == "by-client":
        store.db.execute("UPDATE orders SET broker_id=NULL,status='prepared'")
    elif route == "filled-parent":
        engine.ingest_order(
            {**initial, "status": "filled", "filled_qty": "1", "filled_avg_price": "100"},
            "intraday",
            "plan",
        )
    before = ledger(store)
    monkeypatch.setattr(broker, "by_client", lambda _: unrelated_receipt())
    monkeypatch.setattr(broker, "order", lambda _: unrelated_receipt())
    with pytest.raises(ValueError, match="requested .* identity"):
        engine.reconcile(now)
    assert ledger(store) == before
    assert store.get("reconciled") is False
    assert len(reject_receipts(store)) == 1


def test_existing_root_cannot_switch_broker_id_even_with_matching_client(
    store, broker, config, monkeypatch
):
    engine = Engine(config, store, broker)
    payload = intended_entry()
    initial = engine.submit_intent(payload, "intraday", "plan")
    before = ledger(store)
    monkeypatch.setattr(broker, "by_client", lambda _: {**initial, "id": "replacement-id"})
    with pytest.raises(ValueError, match="requested order identity"):
        engine.submit_intent(payload, "intraday", "plan")
    assert ledger(store) == before


def test_expected_client_identity_does_not_create_ownership_without_saved_intent(
    store, broker, config
):
    receipt = unrelated_receipt()
    with pytest.raises(ValueError, match="no persisted owned intent"):
        Engine(config, store, broker).ingest_order(
            receipt, "intraday", "plan", expected_client_id=receipt["client_order_id"]
        )
    assert not store.rows("SELECT * FROM orders")
    assert not store.rows("SELECT * FROM holdings")
    assert not fill_events(store)


def test_final_success_marker_failure_rolls_back_account_risk_and_all_equity(
    store, broker, config, now
):
    before = ledger(store)
    store.db.execute(
        "CREATE TEMP TRIGGER fail_success BEFORE INSERT ON kv "
        "WHEN NEW.key='reconciled' AND NEW.value='true' "
        "BEGIN SELECT RAISE(ABORT,'injected success failure'); END"
    )
    with pytest.raises(sqlite3.IntegrityError, match="injected success"):
        Engine(config, store, broker).reconcile(now)
    assert ledger(store) == before
    assert store.get("reconciled") is False
    assert store.get("account") is None
    assert store.get("last_reconciled") is None
    assert not store.rows("SELECT * FROM kv WHERE key LIKE 'sod:%'")
