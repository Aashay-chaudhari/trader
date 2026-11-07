"""The bounded CLI check never cancels an unrelated broker receipt."""

import copy
from datetime import datetime

import pytest

from agent_trader.runtime import cli
from agent_trader.runtime.config import ET
from agent_trader.runtime.engine import Engine, order_id


def preflight_payload():
    return {
        "symbol": "SPY", "qty": "1", "side": "buy", "type": "limit",
        "limit_price": "1.00", "time_in_force": "day", "extended_hours": False,
        "client_order_id": order_id("preflight-submission", datetime.now(ET).date().isoformat()),
    }


@pytest.mark.parametrize("stage", ["initial", "poll", "cleanup"])
@pytest.mark.parametrize("field,value", [
    ("id", "unrelated-broker-order"),
    ("client_order_id", "unrelated-client"),
    ("symbol", "AAPL"),
    ("qty", "2"),
])
def test_mismatched_receipt_cannot_authorize_cancellation(
    config, store, broker, monkeypatch, stage, field, value
):
    payload = preflight_payload()
    original = Engine(config, store, broker).submit_intent(payload, "intraday", "submission-preflight")
    baseline = store.rows("SELECT * FROM orders")
    canceled, calls = [], {"by_client": 0}
    by_client, get_order, cancel = broker.by_client, broker.order, broker.cancel
    monkeypatch.setattr(cli, "Broker", lambda _: broker)
    # The flat-account check and a later lookup can observe different snapshots.
    monkeypatch.setattr(broker, "orders", lambda: [])

    def changed(receipt):
        return {**copy.deepcopy(receipt), field: value, "status": "new"}

    def lookup(cid):
        calls["by_client"] += 1
        receipt = by_client(cid)
        if (stage == "initial" and calls["by_client"] == 1) or (
            stage == "cleanup" and calls["by_client"] == 2
        ):
            return changed(receipt)
        return receipt

    def record_cancel(identity):
        canceled.append(identity)
        cancel(identity)

    monkeypatch.setattr(broker, "by_client", lookup)
    monkeypatch.setattr(broker, "cancel", record_cancel)
    if stage == "poll":
        monkeypatch.setattr(broker, "order", lambda oid: changed(get_order(oid)))
    with pytest.raises(ValueError):
        cli._smoke_submission(config, store)
    assert canceled == ([] if stage == "initial" else [original["id"]])
    assert broker.submissions == 1
    assert broker.closed
    assert store.get("reconciled") is False
    assert store.rows("SELECT * FROM holdings") == []
    current = store.rows("SELECT * FROM orders")
    assert len(current) == 1
    for name in ("client_id", "broker_id", "symbol", "side", "qty", "filled", "branch", "plan_id"):
        assert current[0][name] == baseline[0][name]
    assert store.rows("SELECT id FROM events WHERE kind='order_receipt_rejected'")


def test_unowned_by_client_receipt_is_rejected_before_cancel(config, store, broker, monkeypatch):
    receipt = broker.submit(preflight_payload())
    canceled = []
    monkeypatch.setattr(cli, "Broker", lambda _: broker)
    monkeypatch.setattr(broker, "orders", lambda: [])
    monkeypatch.setattr(broker, "cancel", canceled.append)
    with pytest.raises(ValueError, match="persisted owned intent"):
        cli._smoke_submission(config, store)
    assert canceled == [] and broker.closed
    assert broker.items[receipt["id"]]["status"] == "new"
    assert store.rows("SELECT * FROM orders") == []
    assert store.get("readiness") is None


def test_cancellation_polling_stays_bounded(config, store, broker, monkeypatch):
    calls = {"order": 0, "cancel": 0, "sleep": 0}
    get_order = broker.order
    monkeypatch.setattr(cli, "Broker", lambda _: broker)

    def pending(identity):
        calls["order"] += 1
        return get_order(identity)

    def cancel(_):
        calls["cancel"] += 1

    def sleep(seconds):
        assert seconds == 0.5
        calls["sleep"] += 1

    monkeypatch.setattr(broker, "order", pending)
    monkeypatch.setattr(broker, "cancel", cancel)
    monkeypatch.setattr(cli.time, "sleep", sleep)
    with pytest.raises(ValueError, match="cancellation not confirmed"):
        cli._smoke_submission(config, store)
    assert calls == {"order": 10, "cancel": 2, "sleep": 10}
    assert broker.submissions == 1 and broker.closed
    assert store.get("readiness") is None
