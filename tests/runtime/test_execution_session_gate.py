"""Actual-use session proof and truthful local dispatch deferral."""

import json
from datetime import timedelta

import pytest

from agent_trader.runtime import engine
from agent_trader.runtime.engine import Engine
from tests.runtime.session_fixtures import approve, install


def ready(store, broker, config, now, plan):
    instance = Engine(config, store, broker)
    assert instance.reconcile(now)
    store.set("readiness", {"execution_verified": True})
    close = now.astimezone(engine.ET).replace(hour=16, minute=0, second=0, microsecond=0)
    install(store, now, closed=close)
    instance.add_plans([plan], now.date().isoformat())
    approve(store, plan, now)
    return instance, close


@pytest.mark.parametrize("age,latency", [(29, 2), (0, 31)])
def test_asset_latency_expires_clock_before_ninety_second_guards(store, broker, config, now, plan, quote, monkeypatch, age, latency):
    instance, close = ready(store, broker, config, now, plan)
    install(store, now, closed=close, clock_at=now - timedelta(seconds=age))
    elapsed = [0]
    monkeypatch.setattr(engine, "monotonic", lambda: elapsed[0])

    def asset(symbol):
        elapsed[0] = latency
        return {"tradable": True, "status": "active"}

    monkeypatch.setattr(broker, "asset", asset)
    with pytest.raises(ValueError, match="clock_timestamp_stale"):
        instance.enter(plan, quote, now, close)
    assert broker.submissions == 0 and store.rows("SELECT * FROM orders") == []


def test_boolean_or_cached_assessment_cannot_supply_missing_proof(store, broker, config, now, plan, quote):
    instance, close = ready(store, broker, config, now, plan)
    store.set("operational_session", {"assessment": {"state": "open"}})
    with pytest.raises(ValueError, match="session proof"):
        instance.enter(plan, quote, now, close)
    assert broker.submissions == 0


def test_supplied_close_cannot_extend_the_validated_deadline(store, broker, config, now, plan, quote):
    instance, close = ready(store, broker, config, now, plan)
    with pytest.raises(ValueError, match="Supplied close"):
        instance.enter(plan, quote, now, close + timedelta(hours=1))
    assert broker.submissions == 0


def test_post_commit_delay_records_exact_not_sent_and_fresh_retry_reuses_intent(
    store, broker, config, now, plan, quote, monkeypatch
):
    instance, close = ready(store, broker, config, now, plan)
    install(store, now, closed=close, clock_at=now - timedelta(seconds=29))
    elapsed, connection = [0], store.db
    monkeypatch.setattr(engine, "monotonic", lambda: elapsed[0])

    class SlowCommit:
        delayed = False

        def __getattr__(self, name):
            return getattr(connection, name)

        def execute(self, sql, *args):
            result = connection.execute(sql, *args)
            if sql == "COMMIT" and not self.delayed:
                self.delayed = True
                elapsed[0] += 2
            return result

    monkeypatch.setattr(store, "db", SlowCommit())
    with pytest.raises(ValueError, match="clock_timestamp_stale"):
        instance.enter(plan, quote, now, close)
    row = store.rows("SELECT * FROM orders")[0]
    assert broker.submissions == 0 and row["status"] == "not_sent"
    assert instance._proven_not_sent(row)
    event = json.loads(store.rows("SELECT payload FROM events WHERE kind='order_not_sent'")[0]["payload"])
    assert event["identity"]["payload"] == row["payload"]
    assert instance.reconcile(now + timedelta(seconds=2))
    assert instance._unconfirmed_entries() == []
    later = now + timedelta(seconds=3)
    install(store, later, closed=close)
    instance.enter(plan, quote, later, close)
    retried = store.rows("SELECT * FROM orders")[0]
    assert broker.submissions == 1
    assert retried["client_id"] == row["client_id"] and retried["status"] == "new"
    assert json.loads(retried["payload"])["limit_price"] == json.loads(row["payload"])["limit_price"]
    assert len(store.rows("SELECT * FROM events WHERE kind='order_not_sent'")) == 1


def test_not_sent_status_without_local_proof_never_removes_exposure_guard(store, broker, config, now):
    instance = Engine(config, store, broker)
    store.db.execute(
        "INSERT INTO orders(client_id,branch,symbol,side,qty,status,plan_id,payload,at) VALUES('unknown','intraday','AAPL','buy',1,'not_sent','plan','{}',?)",
        (now.isoformat(),),
    )
    assert len(instance._unconfirmed_entries()) == 1
    with pytest.raises(ValueError, match="Unresolved prepared order"):
        instance.reconcile(now)
    assert broker.submissions == 0


def test_preexisting_uncertain_prepared_intent_is_never_reclassified_not_sent(store, broker, config, monkeypatch):
    instance = Engine(config, store, broker)
    payload = {"client_order_id": "uncertain", "symbol": "AAPL", "side": "buy", "qty": "1", "type": "limit", "limit_price": "100"}

    def uncertain(_):
        raise TimeoutError("The original request may have reached the broker")

    monkeypatch.setattr(broker, "submit", uncertain)
    with pytest.raises(TimeoutError):
        instance.submit_intent(payload, "intraday", "plan")
    with pytest.raises(ValueError):
        instance.submit_intent(payload, "intraday", "plan", pre_dispatch=lambda: pytest.fail("Recovery must not submit again"))
    assert store.rows("SELECT status FROM orders") == [{"status": "prepared"}]
    assert store.rows("SELECT * FROM events WHERE kind='order_not_sent'") == []


def test_callback_rejection_requires_unchanged_payload_and_fresh_callback_for_retry(store, broker, config):
    instance = Engine(config, store, broker)
    payload = {"client_order_id": "deferred", "symbol": "AAPL", "side": "buy", "qty": "1", "type": "limit", "limit_price": "100"}

    def reject():
        raise ValueError("Local admission rejected")

    with pytest.raises(ValueError, match="Local admission"):
        instance.submit_intent(payload, "intraday", "plan", pre_dispatch=reject)
    with pytest.raises(ValueError, match="unchanged intent"):
        instance.submit_intent(payload, "intraday", "plan")
    with pytest.raises(ValueError, match="unchanged intent"):
        instance.submit_intent({**payload, "qty": "2"}, "intraday", "plan", pre_dispatch=lambda: None)
    assert broker.submissions == 0
    instance.submit_intent(payload, "intraday", "plan", pre_dispatch=lambda: None)
    assert broker.submissions == 1


@pytest.mark.parametrize("operation", ["close", "exit", "protect"])
def test_unknown_session_cannot_remove_owned_protection(store, broker, config, now, operation):
    instance = Engine(config, store, broker)
    buy = instance.submit_intent({"client_order_id": "entry", "symbol": "AAPL", "qty": "1", "side": "buy", "type": "limit", "limit_price": "100"}, "intraday", "plan")
    broker.items[buy["id"]].update(status="filled", filled_qty="1", filled_avg_price="100")
    instance.ingest_order(broker.order(buy["id"]), "intraday", "plan")
    stop = instance.submit_intent({"client_order_id": "stop", "symbol": "AAPL", "qty": "1", "side": "sell", "type": "stop", "stop_price": "95"}, "intraday", "plan")
    broker.cash = 29900
    broker.pos = [{"symbol": "AAPL", "qty": "1", "market_value": "100"}]
    assert instance.reconcile(now)
    call = {"close": lambda: instance.close_intraday(now=now), "exit": lambda: instance.exit_holding("AAPL", "authorized", now=now), "protect": lambda: instance.ensure_protection(now=now)}[operation]
    with pytest.raises(ValueError, match="session proof"):
        call()
    assert broker.items[stop["id"]]["status"] == "new"
    assert broker.submissions == 2


def test_unknown_close_allows_missing_plan_buy_cancel_without_guessing_cutoff(store, broker, config, now, plan):
    instance, close = ready(store, broker, config, now, plan)
    live = instance.submit_intent({"client_order_id": "entry", "symbol": "AAPL", "qty": "1", "side": "buy", "type": "limit", "limit_price": "100"}, "intraday", plan["id"])
    stale = instance.submit_intent({"client_order_id": "orphan", "symbol": "MSFT", "qty": "1", "side": "buy", "type": "limit", "limit_price": "100"}, "intraday", "missing-plan")
    instance.cancel_entries(now, close=None)
    assert broker.items[live["id"]]["status"] == "new"
    assert broker.items[stale["id"]]["status"] == "canceled"


@pytest.mark.parametrize("operation", ["protect", "close"])
@pytest.mark.parametrize("changed_quantity", [False, True])
def test_local_unsent_exit_or_stop_reuses_only_unchanged_confirmed_payload(
    store, broker, config, now, plan, monkeypatch, operation, changed_quantity
):
    from tests.runtime.test_execution_refinement import own_position

    instance, _ = own_position(store, broker, config, now, plan)
    monkeypatch.setattr(broker, "quotes", lambda symbols: {
        symbol: {"bp": 100, "ap": 100.01, "t": now.isoformat()} for symbol in symbols
    })
    elapsed, connection = [0], store.db
    monkeypatch.setattr(engine, "monotonic", lambda: elapsed[0])

    class SlowIntentCommit:
        pending = False
        delayed = False

        def __getattr__(self, name):
            return getattr(connection, name)

        def execute(self, sql, *args):
            result = connection.execute(sql, *args)
            if "INSERT INTO orders" in sql:
                self.pending = True
            if sql == "COMMIT" and self.pending and not self.delayed:
                self.delayed = True
                elapsed[0] += 2
            return result

    monkeypatch.setattr(store, "db", SlowIntentCommit())
    install(store, now, clock_at=now - timedelta(seconds=29))
    call = instance.ensure_protection if operation == "protect" else instance.close_intraday
    with pytest.raises(engine.SessionProofUnavailable):
        call(now=now)
    unsent = store.rows("SELECT * FROM orders WHERE status='not_sent'")[0]
    assert broker.submissions == 0 and instance._proven_not_sent(unsent)
    later = now + timedelta(seconds=3)
    if changed_quantity:
        # An independently confirmed fill changes the owned quantity; the old
        # unsent ten-share payload must never be dispatched against six shares.
        reduction = {"id": "confirmed-reduction", "client_order_id": "confirmed-reduction",
                     "symbol": "AAPL", "side": "sell", "type": "market", "qty": "4",
                     "filled_qty": "4", "filled_avg_price": "100", "status": "filled"}
        broker.items[reduction["id"]] = reduction
        instance.ingest_order(reduction, "intraday", plan["id"])
        broker.cash, broker.pos = 29400, [{"symbol": "AAPL", "qty": "6", "market_value": "600"}]
    assert instance.reconcile(later)
    install(store, later)
    call(now=later)
    sent = next(order for order in broker.items.values() if order["status"] == "new")
    assert broker.submissions == 1 and float(sent["qty"]) == (6 if changed_quantity else 10)
    assert (sent["client_order_id"] != unsent["client_id"]) is changed_quantity
    saved = store.rows("SELECT * FROM orders WHERE client_id=?", (unsent["client_id"],))[0]
    if changed_quantity:
        assert saved["payload"] == unsent["payload"]
    else:
        assert all(json.loads(saved["payload"])[key] == value for key, value in json.loads(unsent["payload"]).items())
    history = json.loads(store.rows("SELECT payload FROM events WHERE kind='order_not_sent'")[0]["payload"])
    assert history["identity"]["payload"] == unsent["payload"]
    assert saved["status"] == ("not_sent" if changed_quantity else "new")


@pytest.mark.parametrize("where", ["asset", "commit"])
def test_approval_age_is_rechecked_after_latency_even_when_session_remains_fresh(
    store, broker, config, now, plan, quote, monkeypatch, where
):
    instance, close = ready(store, broker, config, now, plan)
    approve(store, plan, now - timedelta(seconds=175))
    elapsed, connection = [0], store.db
    monkeypatch.setattr(engine, "monotonic", lambda: elapsed[0])
    if where == "asset":
        def asset(symbol):
            elapsed[0] += 10
            return {"tradable": True, "status": "active"}
        monkeypatch.setattr(broker, "asset", asset)
    else:
        class SlowCommit:
            delayed = False

            def __getattr__(self, name):
                return getattr(connection, name)

            def execute(self, sql, *args):
                result = connection.execute(sql, *args)
                if sql == "COMMIT" and not self.delayed:
                    self.delayed = True
                    elapsed[0] += 10
                return result
        monkeypatch.setattr(store, "db", SlowCommit())
    with pytest.raises(ValueError, match="approval expired"):
        instance.enter(plan, quote, now, close)
    assert broker.submissions == 0
    rows = store.rows("SELECT * FROM orders")
    assert (len(rows) == 1 and instance._proven_not_sent(rows[0])) if where == "commit" else rows == []


def test_final_local_proof_read_wait_is_included_in_actual_dispatch_age(
    store, broker, config, now, plan, quote, monkeypatch
):
    instance, close = ready(store, broker, config, now, plan)
    install(store, now, clock_at=now - timedelta(seconds=29))
    elapsed, original = [0], store.get
    monkeypatch.setattr(engine, "monotonic", lambda: elapsed[0])

    def slow_get(key, *args):
        result = original(key, *args)
        if key == "operational_session" and store.rows("SELECT * FROM orders WHERE status='prepared'"):
            elapsed[0] += 2
        return result

    monkeypatch.setattr(store, "get", slow_get)
    with pytest.raises(engine.SessionProofUnavailable, match="clock_timestamp_stale"):
        instance.enter(plan, quote, now, close)
    row = store.rows("SELECT * FROM orders")[0]
    assert broker.submissions == 0 and instance._proven_not_sent(row)


def test_ambiguous_stop_absent_from_open_list_never_gets_a_new_competing_id(
    store, broker, config, now, plan, monkeypatch
):
    from tests.runtime.test_execution_refinement import own_position

    instance, _ = own_position(store, broker, config, now, plan)
    calls = []

    def uncertain(payload):
        calls.append(payload)
        raise TimeoutError("Receipt unavailable; the broker may have accepted the stop")

    monkeypatch.setattr(broker, "submit", uncertain)
    with pytest.raises(TimeoutError):
        instance.ensure_protection(now=now)
    instance.ensure_protection(now=now)
    assert len(calls) == 1
    assert store.rows("SELECT status FROM orders WHERE side='sell'") == [{"status": "prepared"}]
