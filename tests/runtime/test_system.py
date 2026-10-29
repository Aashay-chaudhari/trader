import json
from datetime import timedelta
from dataclasses import replace

import pytest

from agent_trader.runtime.agent import budget_check
from agent_trader.runtime.experiments import Experiments
from agent_trader.runtime.maintenance import validate_source
from agent_trader.runtime.publish import sanitize, snapshot
from agent_trader.runtime.supervisor import session_times


def quota(now, used=10):
    return {
        "ordinary_usage_allowed": True,
        "windows": [
            {
                "usedPercent": used,
                "windowDurationMins": 10080,
                "resetsAt": int((now + timedelta(days=5)).timestamp()),
            }
        ],
    }


def test_budget_preserves_twenty_percent_and_missing_limit_fails_closed(store, now):
    assert budget_check(store, quota(now, 10), "research", now)[0]
    assert not budget_check(store, quota(now, 80), "decision", now)[0]
    assert not budget_check(store, {"windows": []}, "research", now)[0]


def test_external_usage_reduces_daily_budget_and_reset_rebases(store, now):
    q = quota(now, 10)
    assert budget_check(store, q, "research", now)[0]
    assert not budget_check(store, quota(now, 40), "research", now)[0]
    assert budget_check(store, quota(now, 0), "research", now + timedelta(days=1))[0]


def test_short_window_quota_checked(store, now):
    q = quota(now)
    q["windows"].append(
        {"usedPercent": 95, "windowDurationMins": 300, "resetsAt": int(now.timestamp()) + 100}
    )
    assert not budget_check(store, q, "decision", now)[0]


def test_public_snapshot_redacts_secrets(config, store):
    store.set("brief", {"summary": f"{config.secret_key} ntfy.sh/{config.ntfy_topic}"})
    store.event(
        "incident", {"reason": config.api_key, "account_number": "12345", "secret_key": "never"}
    )
    out = json.dumps(snapshot(config, store))
    assert (
        config.api_key not in out and config.secret_key not in out and config.ntfy_topic not in out
    )
    assert "12345" not in out


def test_jobs_are_idempotent_and_recoverable(store):
    assert store.job_start("morning")
    store.job_end("morning", True, {})
    assert not store.job_start("morning")
    assert store.job_start("other")
    store.recover_jobs()
    assert store.job_start("other")
    store.job_end("other", False, {})
    assert not store.job_start("other")


@pytest.mark.parametrize(
    "path,code",
    [
        ("src/agent_trader/runtime/engine.py", "x=1"),
        (
            "src/agent_trader/strategies/adaptive.py",
            "import os\ndef candidate_filter(plan, context): return True",
        ),
        (
            "src/agent_trader/strategies/adaptive.py",
            'def candidate_filter(plan, context): return open(".env").read()',
        ),
        (
            "src/agent_trader/strategies/adaptive.py",
            "def candidate_filter(plan, context): return plan.__class__",
        ),
        (
            "src/agent_trader/strategies/adaptive.py",
            "def candidate_filter(plan, context):\n while True: pass",
        ),
    ],
)
def test_maintenance_cannot_modify_kernel_or_add_side_effects(path, code):
    with pytest.raises(ValueError):
        validate_source(path, code)


def test_pure_strategy_extension_allowed():
    assert validate_source(
        "src/agent_trader/strategies/adaptive.py",
        'VERSION="v2"\ndef candidate_filter(plan, context):\n return plan.get("confidence",0) >= .75\n',
    )


def proposal():
    return {
        "id": "test-filter",
        "branch": "intraday",
        "hypothesis": "Require risk-on regime",
        "exact_change": "require_risk_on",
        "parent_version": "pilot-v1",
        "minimum_sessions": 20,
        "minimum_samples": 30,
        "cost_model": "20bp + spread",
        "metrics": ["paired net return"],
    }


def test_experiment_contract_immutable_single_slot_and_no_day_one_promotion(
    store, plan, quote, now
):
    e = Experiments(store)
    assert e.register(proposal())
    assert not e.register({**proposal(), "id": "another"})
    e.consider(plan, quote, "mixed", now)
    assert len(store.rows("SELECT * FROM shadow")) == 1
    quote = {**quote, "bp": 108.0, "ap": 108.01, "t": (now + timedelta(minutes=1)).isoformat()}
    e.mark({"AAPL": quote}, now + timedelta(minutes=1))
    assert store.rows("SELECT state FROM shadow")[0]["state"] == "closed"
    assert not e.evaluate()
    assert store.rows("SELECT state FROM experiments")[0]["state"] == "shadow"


def test_unimplemented_experiment_cannot_be_auto_promoted(store):
    e = Experiments(store)
    assert e.register({**proposal(), "exact_change": "Invent complicated new indicator"})
    assert store.rows("SELECT state FROM experiments")[0]["state"] == "proposed"


def test_early_close_calendar():
    opened, closed = session_times([{"open": "09:30", "close": "13:00"}], "2026-11-27")
    assert closed.hour == 13 and opened.tzinfo is not None
    assert session_times([], "2026-12-25") is None


def test_code_filter_uses_isolated_pure_execution():
    from agent_trader.runtime.maintenance import evaluate_filter

    source = 'VERSION="test"\ndef candidate_filter(plan, context):\n return plan.get("confidence",0)>.75\n'
    assert evaluate_filter(source, {"confidence": 0.8}, {}) is True
    assert evaluate_filter(source, {"confidence": 0.5}, {}) is False


def test_strategy_filter_cannot_invoke_forbidden_builtin():
    from agent_trader.runtime.maintenance import evaluate_filter

    source = 'def candidate_filter(plan, context):\n return eval("True")\n'
    with pytest.raises(ValueError):
        evaluate_filter(source, {}, {})


def test_supported_challenger_promotes_only_after_contract_passes(store):
    from agent_trader.runtime.store import dumps

    e = Experiments(store)
    e.register(proposal())
    for i in range(40):
        p = {"day": f"2026-09-{i // 2 + 1:02d}", "incumbent_return": -0.01, "challenger_return": 0}
        store.db.execute(
            "INSERT INTO shadow VALUES(?,?,?,?,?,?)",
            (str(i), "test-filter", "AAPL", "intraday", "closed", dumps(p)),
        )
    assert e.evaluate() == ["test-filter"]
    assert store.get("incumbent_filter:intraday")["stage"] == "25% pilot risk"
