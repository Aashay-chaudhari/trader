from datetime import timedelta

import pytest

from agent_trader.runtime import supervisor
from agent_trader.runtime.engine import EXECUTION_KERNEL, current_execution_verified, timestamp
from tests.runtime.test_execution_check import (
    fresh_smoke,
    runtime as runtime,
    fill_entry,
    fill_exit,
)


@pytest.fixture
def timed(runtime, monkeypatch):
    s, broker, now, close = runtime
    elapsed = [0.0]
    monkeypatch.setattr(supervisor.time, "monotonic", lambda: elapsed[0])
    ready = s.store.get("readiness")
    ready.update(
        execution_verified=True,
        execution_verified_at="2026-11-02T14:35:37+00:00",
        verified_execution_kernel="prior-kernel",
        required_execution_kernel=EXECUTION_KERNEL,
    )
    s.store.set("readiness", ready)
    return s, broker, now, close, elapsed


def test_quote_that_expires_during_fetch_cannot_create_smoke_intent(timed, monkeypatch):
    s, broker, now, close, elapsed = timed

    def quotes(_):
        elapsed[0] += 10
        return {"SPY": {"bp": 100, "ap": 100.01, "t": (now - timedelta(seconds=89)).isoformat()}}

    monkeypatch.setattr(broker, "quotes", quotes)
    with pytest.raises(ValueError, match="stale"):
        fresh_smoke(s, now, now.replace(minute=30), close)
    assert broker.submissions == 0
    assert not s.store.rows("SELECT * FROM orders")
    assert not s.store.get("smoke:" + now.date().isoformat())


def test_fresh_quote_after_slow_request_does_not_refresh_stale_account(timed, monkeypatch):
    s, broker, now, close, elapsed = timed

    def quotes(_):
        elapsed[0] += 100
        return {"SPY": {"bp": 100, "ap": 100.01, "t": (now + timedelta(seconds=100)).isoformat()}}

    monkeypatch.setattr(broker, "quotes", quotes)
    assert not fresh_smoke(s, now, now.replace(minute=30), close)
    assert broker.submissions == 0
    assert s.store.get("last_reconciled") == now.isoformat()
    assert not s.store.get("smoke:" + now.date().isoformat())


@pytest.mark.parametrize("age,admitted", [(90, True), (91, False), (-5, True), (-6, False)])
def test_new_stage_uses_existing_account_freshness_boundaries(timed, age, admitted):
    s, broker, now, close, _ = timed
    s.store.set("last_reconciled", (now - timedelta(seconds=age)).isoformat())
    assert not fresh_smoke(s, now, now.replace(minute=30), close)
    assert broker.submissions == int(admitted)


@pytest.mark.parametrize("receipt", [None, "unknown", "2026-11-07T09:32:00"])
def test_new_stage_requires_a_valid_aware_reconciliation_receipt(timed, receipt):
    s, broker, now, close, _ = timed
    s.store.set("last_reconciled", receipt)
    assert not fresh_smoke(s, now, now.replace(minute=30), close)
    assert broker.submissions == 0


def test_fresh_delayed_quote_starts_two_minute_horizon_at_actual_receipt(timed, monkeypatch):
    s, broker, now, close, elapsed = timed
    original_orders = broker.orders

    def orders():
        elapsed[0] += 7
        return original_orders()

    def quotes(_):
        elapsed[0] += 13
        return {
            "SPY": {"bp": 100, "ap": 100.01, "t": (now + timedelta(seconds=elapsed[0])).isoformat()}
        }

    monkeypatch.setattr(broker, "orders", orders)
    monkeypatch.setattr(broker, "quotes", quotes)
    assert not fresh_smoke(s, now, now.replace(minute=30), close)
    stage = s.store.get("smoke:" + now.date().isoformat())
    submitted = now + timedelta(seconds=20)
    assert timestamp(stage["at"]) == submitted
    assert timestamp(stage["expires_at"]) == submitted + timedelta(minutes=2)
    row = s.store.rows("SELECT * FROM orders")[0]
    assert row["qty"] == 1
    s.engine.cancel_entries(submitted + timedelta(seconds=119), close)
    assert broker.items[row["broker_id"]]["status"] == "new"
    s.engine.cancel_entries(submitted + timedelta(minutes=2), close)
    assert broker.items[row["broker_id"]]["status"] == "canceled"
    assert s.engine.reconcile(submitted + timedelta(minutes=2, seconds=1))
    assert not fresh_smoke(s, submitted + timedelta(minutes=3), now.replace(minute=30), close)
    assert s.store.get("smoke:" + now.date().isoformat())["state"] == "unfilled"
    assert broker.submissions == 1


@pytest.mark.parametrize("route", ["orders", "quotes"])
@pytest.mark.parametrize("delay", [10, 2500])
def test_slow_lookup_cannot_cross_new_smoke_cutoff(timed, monkeypatch, route, delay):
    s, broker, _, close, elapsed = timed
    now = close - timedelta(minutes=40, seconds=5)
    assert s.engine.reconcile(now)
    calls = []

    def orders():
        calls.append("orders")
        if route == "orders":
            elapsed[0] += delay
        return []

    def quotes(_):
        calls.append("quotes")
        elapsed[0] += delay
        return {
            "SPY": {"bp": 100, "ap": 100.01, "t": (now + timedelta(seconds=elapsed[0])).isoformat()}
        }

    monkeypatch.setattr(broker, "orders", orders)
    monkeypatch.setattr(broker, "quotes", quotes)
    assert not fresh_smoke(s, now, now.replace(hour=9, minute=30, second=0), close)
    assert calls == (["orders"] if route == "orders" else ["orders", "quotes"])
    assert broker.submissions == 0
    assert not s.store.get("smoke:" + now.date().isoformat())


@pytest.mark.parametrize("change", ["quota", "reconciliation", "models", "funded", "kernel"])
def test_admission_changed_during_quote_request_blocks_submission(timed, monkeypatch, change):
    s, broker, now, close, elapsed = timed

    def quotes(_):
        elapsed[0] += 1
        if change == "quota":
            s.store.set("entry_budget_blocked", True)
        elif change == "reconciliation":
            s.store.set("reconciled", False)
        else:
            ready = s.store.get("readiness")
            ready[
                {
                    "models": "models_available",
                    "funded": "funded",
                    "kernel": "required_execution_kernel",
                }[change]
            ] = "other-release" if change == "kernel" else False
            s.store.set("readiness", ready)
        return {"SPY": {"bp": 100, "ap": 100.01, "t": now.isoformat()}}

    monkeypatch.setattr(broker, "quotes", quotes)
    assert not fresh_smoke(s, now, now.replace(minute=30), close)
    assert broker.submissions == 0
    assert not s.store.get("smoke:" + now.date().isoformat())


def test_quota_block_prevents_new_smoke_without_any_quote_request(timed, monkeypatch):
    s, broker, now, close, _ = timed
    s.store.set("entry_budget_blocked", True)
    monkeypatch.setattr(broker, "quotes", lambda _: pytest.fail("Blocked before data request"))
    assert not fresh_smoke(s, now, now.replace(minute=30), close)
    assert broker.submissions == 0
    assert not current_execution_verified(s.store.get("readiness"))
    assert s.store.get("readiness")["execution_verified_at"] == "2026-11-02T14:35:37+00:00"


@pytest.mark.parametrize("qty,verified", [(1, True), (0.5, False)])
def test_existing_stage_unwinds_after_quota_block_without_new_entry(timed, qty, verified):
    s, broker, now, close, _ = timed
    assert not fresh_smoke(s, now, now.replace(minute=30), close)
    entry = s.store.rows("SELECT * FROM orders WHERE side='buy'")[0]
    s.store.set("entry_budget_blocked", True)
    fill_entry(s, broker, entry, qty)
    assert not fresh_smoke(s, now + timedelta(seconds=30), now.replace(minute=30), close)
    fill_exit(s, broker, qty)
    assert fresh_smoke(s, now + timedelta(minutes=1), now.replace(minute=30), close) is verified
    assert current_execution_verified(s.store.get("readiness")) is verified
    assert s.store.get("entry_budget_blocked") is True
    assert s.store.get("readiness")["execution_verified_at"] == "2026-11-02T14:35:37+00:00"
    assert not s.store.rows("SELECT * FROM holdings")
    fresh_smoke(s, now + timedelta(minutes=2), now.replace(minute=30), close)
    assert broker.submissions == 2


def test_reconciliation_latency_cannot_extend_existing_stage_deadline(timed, monkeypatch):
    s, broker, now, close, elapsed = timed
    assert not fresh_smoke(s, now, now.replace(minute=30), close)
    day = now.date().isoformat()
    key = "smoke:" + day
    stage = s.store.get(key)
    s.store.set("entry_budget_blocked", True)
    s.store.set("preflight_day", day)
    s.store.set("calendar:" + day, [{"date": day, "open": "09:30", "close": "16:00"}])
    s.store.set("last-week-session:" + day, False)
    s.store.set("last-session:" + day, False)
    tick_at = now + timedelta(seconds=119)
    original_order = broker.order

    def delayed_order(oid):
        elapsed[0] += 3
        return original_order(oid)

    monkeypatch.setattr(broker, "order", delayed_order)
    monkeypatch.setattr(
        broker,
        "clock",
        lambda: {
            "is_open": True,
            "timestamp": (tick_at + timedelta(seconds=elapsed[0])).isoformat(),
            "next_open": (now.replace(minute=30) + timedelta(days=1)).isoformat(),
            "next_close": close.isoformat(),
        },
        raising=False,
    )
    monkeypatch.setattr(
        broker, "calendar", lambda _: [{"date": day, "open": "09:30", "close": "16:00"}],
        raising=False,
    )
    monkeypatch.setattr(s, "market_tick", lambda *args: None)
    monkeypatch.setattr(s, "maybe_publish", lambda: None)
    monkeypatch.setattr(s, "launch", lambda *args: False)
    s.tick(tick_at)
    after = s.store.get(key)
    assert after["state"] == "cancel_requested"
    assert after["at"] == stage["at"]
    assert after["expires_at"] == stage["expires_at"]
    assert timestamp(after["cancel_requested_at"]) == now + timedelta(seconds=122)
    assert broker.submissions == 1
