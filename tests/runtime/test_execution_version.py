from datetime import timedelta, timezone

import pytest

from agent_trader.runtime.engine import EXECUTION_KERNEL, Engine, current_execution_verified
from tests.runtime.test_execution_check import runtime as runtime, start, fill_entry, fill_exit, fresh_smoke
from tests.runtime.session_fixtures import install


OLD_RECEIPT = "2026-11-02T14:35:37.790606+00:00"


def require_new_kernel(store):
    ready = store.get("readiness", {})
    ready.update(
        execution_verified=True,
        execution_verified_at=OLD_RECEIPT,
        required_execution_kernel=EXECUTION_KERNEL,
    )
    ready.pop("verified_execution_kernel", None)
    store.set("readiness", ready)


@pytest.mark.parametrize(
    "ready,expected",
    [
        ({"execution_verified": True}, True),
        ({"execution_verified": False}, False),
        ({"execution_verified": True, "required_execution_kernel": EXECUTION_KERNEL}, False),
        (
            {
                "execution_verified": True,
                "required_execution_kernel": EXECUTION_KERNEL,
                "verified_execution_kernel": "older",
            },
            False,
        ),
        (
            {
                "execution_verified": True,
                "required_execution_kernel": EXECUTION_KERNEL,
                "verified_execution_kernel": EXECUTION_KERNEL,
            },
            True,
        ),
        (
            {
                "execution_verified": False,
                "required_execution_kernel": EXECUTION_KERNEL,
                "verified_execution_kernel": EXECUTION_KERNEL,
            },
            False,
        ),
    ],
)
def test_current_verification_requires_explicit_version_match(ready, expected):
    assert current_execution_verified(ready) is expected


def test_historical_success_cannot_authorize_entry_for_required_kernel(
    store, broker, config, now, plan, quote
):
    engine = Engine(config, store, broker)
    assert engine.reconcile(now)
    store.set("market_open", True)
    install(store, now, closed=now + timedelta(hours=4))
    require_new_kernel(store)
    with pytest.raises(ValueError, match="Execution smoke check not verified"):
        engine.validate_entry(plan, quote, now, now + timedelta(hours=4))
    assert store.get("readiness")["execution_verified_at"] == OLD_RECEIPT
    assert broker.submissions == 0


@pytest.mark.parametrize("historical", [False, True])
def test_preflight_installs_current_requirement_without_erasing_prior_receipt(
    runtime, monkeypatch, historical
):
    from agent_trader.runtime import supervisor

    s, broker, now, _ = runtime
    if historical:
        s.store.set("readiness", {"execution_verified": True, "execution_verified_at": OLD_RECEIPT})

    class RPC:
        def __init__(self, config):
            self.config = config

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def rate_limits(self):
            return {
                "at": now.astimezone(timezone.utc).isoformat(),
                "ordinary_usage_allowed": True,
                "windows": [
                    {
                        "usedPercent": 2,
                        "windowDurationMins": 10080,
                        "resetsAt": int((now + timedelta(days=7)).timestamp()),
                    }
                ],
            }

        def models(self):
            return [
                {"id": model}
                for model in {
                    self.config.research_model,
                    self.config.decision_model,
                    self.config.light_model,
                    self.config.maintenance_model,
                }
            ]

    monkeypatch.setattr(supervisor, "CodexRPC", RPC)
    s.preflight()
    ready = s.store.get("readiness")
    assert ready["required_execution_kernel"] == EXECUTION_KERNEL
    assert ready["execution_verified"] is historical
    assert not current_execution_verified(ready)
    if historical:
        assert ready["execution_verified_at"] == OLD_RECEIPT
    assert broker.submissions == 0


def test_new_round_trip_certifies_kernel_and_preserves_historical_timestamp(runtime):
    s, broker, now, close = runtime
    require_new_kernel(s.store)
    row = start(runtime)
    assert s.store.get("smoke:" + now.date().isoformat())["execution_kernel"] == EXECUTION_KERNEL
    assert not fresh_smoke(s, now + timedelta(seconds=20), now.replace(minute=30), close)
    assert broker.submissions == 1
    assert not current_execution_verified(s.store.get("readiness"))
    fill_entry(s, broker, row, 1)
    assert not fresh_smoke(s, now + timedelta(seconds=30), now.replace(minute=30), close)
    fill_exit(s, broker, 1)
    assert fresh_smoke(s, now + timedelta(minutes=1), now.replace(minute=30), close)
    ready = s.store.get("readiness")
    assert current_execution_verified(ready)
    assert ready["execution_verified_at"] == OLD_RECEIPT
    assert ready["verified_execution_kernel"] == EXECUTION_KERNEL
    assert ready["verified_execution_kernel_at"]
    history = s.store.get("execution_verification_history")
    assert history[0]["verified_at"] == OLD_RECEIPT
    assert history[-1]["kernel"] == EXECUTION_KERNEL
    assert fresh_smoke(s, now + timedelta(minutes=2), now.replace(minute=30), close)
    assert len(s.store.get("execution_verification_history")) == 2
    assert broker.submissions == 2


def test_old_kernel_receipt_cannot_be_relabelled_and_does_not_create_second_daily_entry(runtime):
    s, broker, now, close = runtime
    row = start(runtime)
    fill_entry(s, broker, row, 1)
    fresh_smoke(s, now + timedelta(seconds=30), now.replace(minute=30), close)
    fill_exit(s, broker, 1)
    key = "smoke:" + now.date().isoformat()
    s.store.set(key, {**s.store.get(key), "execution_kernel": "older"})
    require_new_kernel(s.store)
    for minutes in (1, 2, 3):
        assert not fresh_smoke(s, now + timedelta(minutes=minutes), now.replace(minute=30), close)
    assert not current_execution_verified(s.store.get("readiness"))
    assert s.store.get("readiness")["execution_verified_at"] == OLD_RECEIPT
    assert broker.submissions == 2
    assert len(s.store.rows("SELECT * FROM orders WHERE side='buy'")) == 1


def test_required_reverification_never_submits_outside_session(runtime):
    s, broker, now, close = runtime
    require_new_kernel(s.store)
    opened = now.replace(minute=30)
    assert not fresh_smoke(s, opened - timedelta(minutes=1), opened, close)
    assert not fresh_smoke(s, close, opened, close)
    assert not fresh_smoke(s, close + timedelta(hours=2), opened, close)
    assert broker.submissions == 0
    assert not s.store.get("smoke:" + now.date().isoformat())


def test_older_binary_cannot_certify_a_different_required_release(runtime):
    s, broker, now, close = runtime
    require_new_kernel(s.store)
    s.store.set(
        "readiness", {**s.store.get("readiness"), "required_execution_kernel": "future-kernel"}
    )
    assert not fresh_smoke(s, now, now.replace(minute=30), close)
    assert broker.submissions == 0


def test_cli_submission_smoke_preserves_history_but_requires_current_kernel_round_trip(
    config, store, broker, monkeypatch
):
    from agent_trader.runtime import cli

    monkeypatch.setattr(cli, "Broker", lambda _: broker)
    store.set("readiness", {
        "execution_verified": True,
        "execution_verified_at": OLD_RECEIPT,
        "verified_execution_kernel": "historically-verified-kernel",
        "verified_execution_kernel_at": OLD_RECEIPT,
    })
    result = cli.smoke_submission(config, store)
    ready = store.get("readiness")
    assert result["cancellation"] == "confirmed" and result["fills"] == 0
    assert ready["execution_verified"] is True
    assert ready["execution_verified_at"] == OLD_RECEIPT
    assert ready["verified_execution_kernel_at"] == OLD_RECEIPT
    assert ready["required_execution_kernel"] == EXECUTION_KERNEL
    assert ready["verified_execution_kernel"] is None
    assert not current_execution_verified(ready)
    assert ready["order_submission_verified"] is True
    assert store.rows("SELECT * FROM holdings") == []
    order = store.rows("SELECT status,qty,payload FROM orders")[0]
    assert order["status"] == "canceled" and order["qty"] == 1
    assert broker.submissions == 1
    cli.smoke_submission(config, store)
    assert broker.submissions == 1
    assert store.get("readiness")["execution_verified_at"] == OLD_RECEIPT
    assert not current_execution_verified(store.get("readiness"))
