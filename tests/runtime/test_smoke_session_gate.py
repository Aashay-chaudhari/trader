"""Actual-dispatch session admission and bounded never-sent smoke recovery."""

import copy
import json
from contextlib import contextmanager
from datetime import timedelta

import pytest

from agent_trader.runtime.engine import timestamp
from tests.runtime.session_fixtures import install
from tests.runtime.test_execution_check import fill_entry, fresh_smoke, runtime as runtime
from tests.runtime.test_smoke_dispatch_time import timed as timed


def delay_prepared_commit(s, elapsed, monkeypatch, seconds):
    original = s.store.transaction
    fired = []

    @contextmanager
    def delayed():
        with original():
            yield
        if not fired and s.store.rows("SELECT client_id FROM orders WHERE status='prepared'"):
            fired.append(True)
            elapsed[0] += seconds

    monkeypatch.setattr(s.store, "transaction", delayed)
    return original


def reject_at_commit(timed, monkeypatch):
    s, broker, now, close, elapsed = timed
    original = delay_prepared_commit(s, elapsed, monkeypatch, 31)
    with pytest.raises(ValueError, match="admission expired before dispatch"):
        fresh_smoke(s, now, now.replace(minute=30), close)
    row = s.store.rows("SELECT * FROM orders")[0]
    assert row["status"] == "not_sent" and s.engine._proven_not_sent(row)
    assert broker.submissions == 0 and not broker.items
    monkeypatch.setattr(s.store, "transaction", original)
    return row, copy.deepcopy(s.store.get("smoke:" + now.date().isoformat()))


@pytest.mark.parametrize("delay,submissions", [(30, 1), (30.001, 0), (35, 0)])
def test_quote_receipt_cannot_refresh_the_independent_clock(timed, monkeypatch, delay, submissions):
    s, broker, now, close, elapsed = timed

    def quote(_):
        elapsed[0] += delay
        return {"SPY": {"bp": 100, "ap": 100.01, "t": (now + timedelta(seconds=delay)).isoformat()}}

    monkeypatch.setattr(broker, "quotes", quote)
    assert not fresh_smoke(s, now, now.replace(minute=30), close)
    assert broker.submissions == submissions
    if not submissions:
        assert not s.store.rows("SELECT * FROM orders")
        assert not s.store.get("smoke:" + now.date().isoformat())


@pytest.mark.parametrize("bad", ["missing", "wrong_close", "untyped_boolean", "duplicate_calendar", "future_receipt"])
def test_new_check_needs_compatible_raw_evidence(timed, bad):
    s, broker, now, close, _ = timed
    proof = install(s.store, now)
    if bad == "missing":
        proof = None
    elif bad == "wrong_close":
        proof["clock_raw"]["next_close"] = (close - timedelta(hours=3)).isoformat()
    elif bad == "untyped_boolean":
        proof["clock_raw"]["is_open"] = "true"
    elif bad == "duplicate_calendar":
        proof["calendar_raw"] *= 2
    else:
        proof["clock_receipt"]["received_at"] = (now + timedelta(seconds=1)).isoformat()
    s.store.set("operational_session", proof)
    assert not s.smoke(now, now.replace(minute=30), close)
    assert broker.submissions == 0 and not s.store.rows("SELECT * FROM orders")


def test_prepare_commit_delay_is_locally_not_sent_with_original_bounded_intent(timed, monkeypatch):
    s, _, now, _, _ = timed
    row, stage = reject_at_commit(timed, monkeypatch)
    assert stage["at"] == now.isoformat()
    assert timestamp(stage["expires_at"]) == now + timedelta(minutes=2)
    payload = json.loads(row["payload"])
    assert payload["qty"] == "1" and payload["symbol"] == "SPY"
    assert payload["stop_loss"] == {"stop_price": "98.01"}
    assert s.store.get("order-not-sent:" + row["client_id"])["identity"]["payload"] == row["payload"]
    assert len(s.store.rows("SELECT * FROM events WHERE kind='order_not_sent'")) == 1


@pytest.mark.parametrize("account_age,delay", [(0, 31), (80, 11)])
def test_final_local_receipt_read_delay_cannot_refresh_clock_or_account(
    timed, monkeypatch, account_age, delay
):
    s, broker, now, close, elapsed = timed
    s.store.set("last_reconciled", (now - timedelta(seconds=account_age)).isoformat())
    original = s.store.get
    prepared_reads = []

    def delayed_get(key, *args, **kwargs):
        result = original(key, *args, **kwargs)
        if key == "last_reconciled" and s.store.rows("SELECT client_id FROM orders WHERE status='prepared'"):
            prepared_reads.append(key)
            if len(prepared_reads) == 2:  # Final receipt read after initial callback admission.
                elapsed[0] += delay
        return result

    monkeypatch.setattr(s.store, "get", delayed_get)
    with pytest.raises(ValueError, match="admission expired before dispatch"):
        fresh_smoke(s, now, now.replace(minute=30), close)
    assert len(prepared_reads) == 2
    assert broker.submissions == 0
    assert s.engine._proven_not_sent(s.store.rows("SELECT * FROM orders")[0])


def test_fresh_retry_sends_exact_original_intent_once_without_extending_expiry(timed, monkeypatch):
    s, broker, now, close, _ = timed
    row, stage = reject_at_commit(timed, monkeypatch)
    retry_at = now + timedelta(seconds=40)
    assert s.engine.reconcile(retry_at)
    monkeypatch.setattr(broker, "quotes", lambda _: {"SPY": {"bp": 100, "ap": 100.01, "t": retry_at.isoformat()}})
    assert not fresh_smoke(s, retry_at, now.replace(minute=30), close)
    assert broker.submissions == 1
    saved = s.store.rows("SELECT * FROM orders")[0]
    assert saved["client_id"] == row["client_id"]
    assert s.store.get("smoke:" + now.date().isoformat()) == stage
    sent = broker.items[saved["broker_id"]]
    for key, value in json.loads(row["payload"]).items():
        assert sent[key] == value
    assert not fresh_smoke(s, retry_at + timedelta(seconds=1), now.replace(minute=30), close)
    assert broker.submissions == 1


@pytest.mark.parametrize("change", ["price", "quota", "expiry", "unproven", "cancel_requested"])
def test_local_retry_cannot_change_price_expand_deadline_or_bypass_admission(timed, monkeypatch, change):
    s, broker, now, close, _ = timed
    row, stage = reject_at_commit(timed, monkeypatch)
    retry_at = now + timedelta(seconds=120 if change == "expiry" else 40)
    assert s.engine.reconcile(retry_at)
    if change == "quota":
        s.store.set("entry_budget_blocked", True)
    elif change == "unproven":
        s.store.set("order-not-sent:" + row["client_id"], {})
    elif change == "cancel_requested":
        stage["state"] = "cancel_requested"
        s.store.set("smoke:" + now.date().isoformat(), stage)
    ask = 100.02 if change == "price" else 100.01
    monkeypatch.setattr(broker, "quotes", lambda _: {"SPY": {"bp": 100, "ap": ask, "t": retry_at.isoformat()}})
    assert not fresh_smoke(s, retry_at, now.replace(minute=30), close)
    assert broker.submissions == 0
    assert s.store.get("smoke:" + now.date().isoformat()) == stage
    assert s.store.rows("SELECT payload FROM orders")[0]["payload"] == row["payload"]


def test_retry_commit_delay_cannot_shift_the_original_two_minute_deadline(timed, monkeypatch):
    s, broker, now, close, elapsed = timed
    _, stage = reject_at_commit(timed, monkeypatch)
    retry_at = now + timedelta(seconds=119)
    assert s.engine.reconcile(retry_at)
    monkeypatch.setattr(broker, "quotes", lambda _: {"SPY": {"bp": 100, "ap": 100.01, "t": retry_at.isoformat()}})
    delay_prepared_commit(s, elapsed, monkeypatch, 2)
    with pytest.raises(ValueError, match="admission expired before dispatch"):
        fresh_smoke(s, retry_at, now.replace(minute=30), close)
    assert broker.submissions == 0
    assert s.store.get("smoke:" + now.date().isoformat()) == stage
    assert s.engine._proven_not_sent(s.store.rows("SELECT * FROM orders")[0])
    assert len(s.store.rows("SELECT * FROM events WHERE kind='order_not_sent'")) == 2


def test_unknown_session_retains_existing_position_and_protection(timed, monkeypatch):
    s, broker, now, close, _ = timed
    assert not fresh_smoke(s, now, now.replace(minute=30), close)
    row = s.store.rows("SELECT * FROM orders")[0]
    fill_entry(s, broker, row, 1)
    s.store.set("operational_session", None)
    monkeypatch.setattr(s.engine, "close_intraday", lambda **kwargs: pytest.fail("Cannot remove protection with unknown timing"))
    before = copy.deepcopy(broker.items)
    assert not s.smoke(now + timedelta(seconds=10), now.replace(minute=30), close)
    assert broker.items == before and broker.submissions == 1
    assert s.store.rows("SELECT qty FROM holdings")[0]["qty"] == 1


def test_unknown_session_does_not_erase_exact_expired_buy_cancellation(timed):
    s, broker, now, close, _ = timed
    assert not fresh_smoke(s, now, now.replace(minute=30), close)
    row = s.store.rows("SELECT * FROM orders")[0]
    s.store.set("operational_session", None)
    assert not s.smoke(now + timedelta(minutes=2), now.replace(minute=30), close)
    assert broker.items[row["broker_id"]]["status"] == "canceled"
    assert s.store.get("smoke:" + now.date().isoformat())["state"] == "cancel_requested"
    assert broker.submissions == 1


def test_expired_smoke_entry_does_not_duplicate_durable_pulse_cancellation(timed, monkeypatch):
    from agent_trader.runtime.observation_audit import content_hash

    s, broker, now, close, _ = timed
    assert not fresh_smoke(s, now, now.replace(minute=30), close)
    row = s.store.rows("SELECT * FROM orders")[0]
    identity = {key: row[key] for key in (
        "client_id", "broker_id", "branch", "symbol", "side", "plan_id", "qty",
    )}
    key = "pulse-cancellation:" + content_hash(identity)
    intent = {"identity": identity, "state": "pending"}
    s.store.set(key, intent)
    s.store.set("operational_session", None)
    monkeypatch.setattr(broker, "cancel", lambda _: pytest.fail("The durable dispatcher owns this cancellation"))
    assert not s.smoke(now + timedelta(minutes=2), now.replace(minute=30), close)
    assert s.store.get(key) == intent
    assert s.store.get("smoke:" + now.date().isoformat())["state"] == "submitted"
    assert broker.submissions == 1
