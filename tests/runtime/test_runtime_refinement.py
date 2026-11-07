import json
from concurrent.futures import Future
from datetime import datetime, timedelta

import httpx
import pytest

from agent_trader.runtime.budget import budget_check, account_limit_reason
from agent_trader.runtime.operations import operational_evidence
from agent_trader.runtime.store import dumps


def quota(now, used=2):
    return {
        "at": now.isoformat(), "ordinary_usage_allowed": True,
        "windows": [{"usedPercent": used, "windowDurationMins": 10080,
                     "resetsAt": int((now + timedelta(days=3)).timestamp())}],
    }


def test_background_attempts_preserve_core_review_slots_and_all_buckets_limit(store, now):
    for _ in range(96):
        store.db.execute(
            "INSERT INTO usage(at,day,role,model,payload) VALUES(?,?,?,?,?)",
            (now.isoformat(), now.date().isoformat(), "deep_research", "test", dumps({"state": "failed"})),
        )
    assert not budget_check(store, quota(now), "deep_research_review", now)[0]
    assert budget_check(store, quota(now), "retrospective", now)[0]
    assert budget_check(store, quota(now), "decision", now)[0]
    q = quota(now)
    q["windows"].append({**q["windows"][0], "bucket": "other", "usedPercent": 80})
    assert account_limit_reason(q, now) == "20% account reserve reached"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1, 101, None, "bad"])
def test_invalid_quota_fails_closed(now, bad):
    q = quota(now)
    q["windows"][0]["usedPercent"] = bad
    assert account_limit_reason(q, now)


def test_expired_quota_and_target_do_not_authorize_work(store, now):
    q = quota(now, 1)
    q["windows"][0]["resetsAt"] = int(now.timestamp()) - 1
    assert not budget_check(store, q, "deep_research", now)[0]
    assert not budget_check(store, quota(now, 80), "deep_research", now)[0]


@pytest.mark.parametrize("reconciles,expected", [(True, "market_closed"), (False, "halted")])
def test_weekend_mode_reflects_reconciliation(config, broker, monkeypatch, reconciles, expected):
    from agent_trader.runtime import supervisor

    monkeypatch.setattr(supervisor, "Broker", lambda _: broker)
    s = supervisor.Supervisor(config)
    now = datetime(2026, 11, 7, 12, tzinfo=supervisor.ET)
    day = now.date().isoformat()
    s.store.set("calendar:" + day, [])
    s.store.set("preflight_day", day)
    s.store.set("mode", "halted")
    monkeypatch.setattr(s.engine, "reconcile", lambda: reconciles)
    monkeypatch.setattr(s.engine, "cancel_entries", lambda *_: None)
    monkeypatch.setattr(s, "maybe_publish", lambda: None)
    launched = []
    monkeypatch.setattr(s, "launch_deep_research", lambda now: launched.append(now))
    try:
        s.tick(now)
        assert s.store.get("mode") == expected
        assert s.store.get("market_open") is False
        assert launched == [now]
        assert broker.submissions == 0
    finally:
        s.pool.shutdown(wait=False)
        s.publisher_pool.shutdown(wait=False)
        s.store.close()


def test_transport_diagnostic_retains_safe_route_only(config):
    from agent_trader.runtime.broker import Broker

    b = Broker(config)
    b.client.close()
    b.client = httpx.Client(transport=httpx.MockTransport(
        lambda req: (_ for _ in ()).throw(httpx.RemoteProtocolError("private body secret"))
    ))
    try:
        with pytest.raises(httpx.RemoteProtocolError) as caught:
            b.order("private-order-id")
        details = caught.value.operation_details
        assert details["route"] == "/v2/orders/:item"
        assert details["method"] == "GET"
        assert details["attempt_id"]
        assert "private" not in json.dumps(details)
        assert config.secret_key not in json.dumps(details)
    finally:
        b.client.close()


def test_historical_execution_success_is_visible_without_inventing_today_fills(store):
    store.set("smoke:2026-11-02", {
        "state": "passed", "verified_at": "2026-11-02T14:35:37+00:00",
        "entry_filled_qty": 1, "exit_filled_qty": 1, "entry_client_id": "private-id",
    })
    result = operational_evidence("2026-11-06", store)
    assert result["latest_verified_execution_check"]["day"] == "2026-11-02"
    assert result["execution_checks"] == []
    assert "private-id" not in json.dumps(result)


def test_snapshot_separates_broker_cash_from_branch_residual(config, store):
    from agent_trader.runtime.publish import snapshot

    store.set("account", {"cash": "29999.97", "equity": "29999.97"})
    store.set("reconciled", True)
    result = snapshot(config, store)
    assert result["accounting"]["broker_equity"] == 29999.97
    assert result["accounting"]["broker_cash"] == 29999.97
    assert result["accounting"]["unattributed_equity_difference"] == -0.03
    assert result["positions"] == []


@pytest.fixture
def controlled_supervisor(config, broker, monkeypatch):
    from agent_trader.runtime import supervisor

    monkeypatch.setattr(supervisor, "Broker", lambda _: broker)
    monkeypatch.setattr(supervisor, "notify", lambda *a, **k: False)
    instance = supervisor.Supervisor(config)
    monkeypatch.setattr(instance, "maybe_publish", lambda: None)
    yield instance
    instance.pool.shutdown(wait=False)
    instance.publisher_pool.shutdown(wait=False)
    instance.store.close()


def test_supervisor_deep_failures_advance_other_work_and_survive_retry_reset(
    controlled_supervisor, broker, monkeypatch
):
    from agent_trader.runtime import research_work, supervisor

    s = controlled_supervisor
    now = datetime.now(supervisor.ET)
    evidence = {"records": [{"id": "ev:fixture", "kind": "research", "value": {}}], "omitted_records": 0}
    monkeypatch.setattr(research_work, "evidence_packets", lambda _: {
        "event_coverage": evidence, "source_verification": evidence,
    })
    s.store.set("entry_budget_blocked", False)
    first = research_work.next_work(s.store, now)

    def fail(work):
        assert s.store.job_start(work["key"])
        s.task = (work["key"], work["role"], work["context"], now.date().isoformat())
        s.future = Future()
        s.future.set_exception(TimeoutError("private transport details"))
        s.finish_task()
        assert s.future is None and s.task is None

    fail(first)
    failure = s.store.get("research-work-failure:" + first["key"])
    assert failure["attempts"] == 1
    assert research_work.next_work(s.store, now)["context"]["topic"] == "source_verification"
    after_cooldown = datetime.fromisoformat(failure["retry_at"]) + timedelta(seconds=1)
    retry = research_work.next_work(s.store, after_cooldown)
    assert retry["key"] == first["key"]
    fail(retry)
    assert s.store.get("research-work-failure:" + first["key"])["attempts"] == 2
    s.store.db.execute("UPDATE jobs SET at=? WHERE key=?", (
        (now - timedelta(hours=1)).isoformat(), first["key"],
    ))
    assert s.store.retry_failed_jobs(now.isoformat()) == 1
    next_job = research_work.next_work(s.store, after_cooldown + timedelta(hours=1))
    assert next_job["context"]["topic"] == "source_verification"
    assert broker.submissions == 0
    assert s.store.get("entry_budget_blocked") is False
    assert "private transport details" not in json.dumps(s.store.rows("SELECT payload FROM events"))


def test_weekend_scheduler_refreshes_stale_quota_before_selecting_model_work(
    controlled_supervisor, broker, monkeypatch
):
    from agent_trader.runtime import research_work, supervisor

    s = controlled_supervisor
    now = datetime(2026, 11, 7, 12, tzinfo=supervisor.ET)
    day = now.date().isoformat()
    s.store.set("calendar:" + day, [])
    s.store.set("preflight_day", day)
    s.store.set("quota", quota(now - timedelta(hours=1)))
    launched = []
    monkeypatch.setattr(s, "launch", lambda *args: launched.append(args) or True)
    monkeypatch.setattr(research_work, "next_work", lambda *_: pytest.fail("Refresh quota first"))
    s.tick(now)
    assert len(launched) == 1 and launched[0][1] == "quota_refresh"
    assert s.store.get("mode") == "market_closed"
    assert broker.submissions == 0


def test_quota_refresh_failure_blocks_entries_without_stopping_weekend_reconciliation(
    controlled_supervisor, broker, monkeypatch
):
    from agent_trader.runtime import supervisor

    s = controlled_supervisor
    now = datetime(2026, 11, 7, 12, tzinfo=supervisor.ET)
    day = now.date().isoformat()
    key = "quota-refresh:test-failure"
    assert s.store.job_start(key)
    s.task = (key, "quota_refresh", {}, day)
    s.future = Future()
    s.future.set_exception(TimeoutError("private quota failure"))
    s.finish_task()
    assert s.store.get("entry_budget_blocked") is True
    assert s.store.get("quota")["ordinary_usage_allowed"] is False
    s.store.set("calendar:" + day, [])
    s.store.set("preflight_day", day)
    monkeypatch.setattr(s, "launch", lambda *args: False)
    s.tick(now)
    assert s.store.get("reconciled") is True
    assert s.store.get("mode") == "market_closed"
    assert broker.submissions == 0
