import json
from datetime import timedelta

import pytest

from agent_trader.runtime.agent import budget_check
from agent_trader.runtime.experiments import Experiments
from agent_trader.runtime.maintenance import validate_source
from agent_trader.runtime.publish import snapshot
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


def test_experiment_contract_immutable_duplicate_and_no_day_one_promotion(store, plan, quote, now):
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
        p = {
            "day": f"2026-09-{i // 2 + 1:02d}",
            "incumbent_return": 0.005,
            "challenger_return": 0.01,
        }
        store.db.execute(
            "INSERT INTO shadow VALUES(?,?,?,?,?,?)",
            (str(i), "test-filter", "AAPL", "intraday", "closed", dumps(p)),
        )
    assert e.evaluate() == ["test-filter"]
    assert store.get("incumbent_filter:intraday")["stage"] == "25% pilot risk"


def test_cli_outage_does_not_abort_broker_preflight_or_python_protection(
    config, broker, monkeypatch
):
    import agent_trader.runtime.supervisor as module

    monkeypatch.setattr(module, "Broker", lambda _: broker)
    monkeypatch.setattr(
        module, "CodexRPC", lambda _: (_ for _ in ()).throw(RuntimeError("CLI offline"))
    )
    s = module.Supervisor(config)
    try:
        assert s.preflight() is False
        assert s.store.get("reconciled") is True
        assert s.store.get("entry_budget_blocked") is True
        assert s.store.get("readiness")["models_available"] is False
    finally:
        s.pool.shutdown(wait=False)
        s.publisher_pool.shutdown(wait=False)
        s.store.close()


def test_paired_shadow_uses_actual_incumbent_filter(store, plan, quote, now):
    store.set(
        "incumbent_filter:intraday", {"id": "prior-filter", "filter": "higher_confidence_075"}
    )
    e = Experiments(store)
    e.register({**proposal(), "parent_version": "prior-filter"})
    plan["confidence"] = 0.7
    e.consider(plan, quote, "risk_on", now)
    sample = json.loads(store.rows("SELECT payload FROM shadow")[0]["payload"])
    assert sample["incumbent_trades"] is False
    assert sample["challenger_trades"] is True
    quote = {**quote, "bp": 108, "ap": 108.01, "t": (now + timedelta(minutes=1)).isoformat()}
    e.mark({"AAPL": quote}, now + timedelta(minutes=1))
    sample = json.loads(store.rows("SELECT payload FROM shadow")[0]["payload"])
    assert sample["incumbent_return"] == 0
    assert sample["challenger_return"] > 0


def test_new_filter_rolls_back_to_previous_incumbent_on_fixed_loss_limit(store):
    from agent_trader.runtime.store import dumps

    previous = {"id": "previous", "filter": "higher_confidence_075", "equity_at_promotion": 10000}
    store.set(
        "incumbent_filter:intraday",
        {
            "id": "new",
            "filter": "require_risk_on",
            "equity_at_promotion": 10000,
            "previous_incumbent": previous,
        },
    )
    store.db.execute(
        "INSERT INTO experiments VALUES(?,?,?,?,?)",
        ("new", "intraday", "promoted", dumps(proposal()), "2026-10-29"),
    )
    store.db.execute(
        "INSERT INTO equity(at,day,branch,value) VALUES(?,?,?,?)",
        ("2026-10-29", "2026-10-29", "intraday", 9700),
    )
    Experiments(store).evaluate()
    assert store.get("incumbent_filter:intraday")["id"] == "previous"
    assert store.rows("SELECT state FROM experiments WHERE id='new'")[0]["state"] == "rolled_back"


def test_call_budget_reserves_four_slots_for_after_close_reviews(store, now):
    for _ in range(20):
        store.db.execute(
            "INSERT INTO usage(at,day,role,model,input_tokens,cached_tokens,output_tokens,quota_delta,payload) VALUES(?,?,?,?,0,0,0,0,?)",
            (now.isoformat(), now.date().isoformat(), "decision", "test", "{}"),
        )
    assert budget_check(store, quota(now), "decision", now)[0] is False
    assert budget_check(store, quota(now), "retrospective", now)[0] is True


def test_incomplete_portfolio_review_cannot_apply_partial_exit_intents(config, broker, monkeypatch):
    import concurrent.futures
    import agent_trader.runtime.supervisor as module

    monkeypatch.setattr(module, "Broker", lambda _: broker)
    s = module.Supervisor(config)
    errors = []
    s.incident = lambda code, reason: errors.append(code)
    try:
        s.future = concurrent.futures.Future()
        s.future.set_result(
            {
                "decisions": [
                    {
                        "symbol": "AAPL",
                        "action": "exit",
                        "reason": "A real invalidation",
                        "evidence_fresh": True,
                        "invalidation_observed": True,
                    }
                ]
            }
        )
        s.task = (
            "position-test",
            "position_review",
            {
                "positions": [
                    {"holding": {"symbol": "AAPL", "branch": "swing"}},
                    {"holding": {"symbol": "MSFT", "branch": "swing"}},
                ]
            },
            "2026-10-29",
        )
        s.finish_task()
        assert errors
        assert s.store.get("exit-intent:AAPL") is None
    finally:
        s.pool.shutdown(wait=False)
        s.publisher_pool.shutdown(wait=False)
        s.store.close()


def test_exhausted_jobs_can_recover_after_backoff_without_replaying_completed_jobs(store):
    assert store.job_start("research")
    store.job_end("research", False, {})
    assert store.job_start("research")
    store.job_end("research", False, {})
    store.db.execute("UPDATE jobs SET at='2026-01-01T00:00:00+00:00' WHERE key='research'")
    assert store.job_start("completed")
    store.job_end("completed", True, {})
    assert store.retry_failed_jobs("2026-01-01T01:00:00+00:00") == 1
    assert store.job_start("research") is True
    assert store.job_start("completed") is False


def test_free_macro_parser_handles_fred_mixed_calendar_zip():
    import io
    import zipfile
    from datetime import date
    from agent_trader.runtime.research import parse_macro_download

    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as z:
        z.writestr("README.txt", "Mixed calendars")
        z.writestr(
            "daily.csv",
            "observation_date,DGS2,DGS10\n2026-10-27,3.5,4.1\n2026-10-28,.,4.2\n2026-10-30,9,9\n",
        )
        z.writestr("seven_day.csv", "DATE,VIXCLS\n2026-10-28,18.5\n")
    result = parse_macro_download(data.getvalue(), ["DGS2", "DGS10", "VIXCLS"], date(2026, 10, 29))
    assert result["DGS2"] == {"value": 3.5, "observation_date": "2026-10-27"}
    assert result["DGS10"]["value"] == 4.2
    assert result["VIXCLS"]["value"] == 18.5


def test_free_macro_parser_does_not_treat_html_or_future_rows_as_data():
    from datetime import date
    from agent_trader.runtime.research import parse_macro_download

    assert parse_macro_download(b"<html>Unavailable</html>", ["DGS10"], date(2026, 10, 29)) == {}
    assert (
        parse_macro_download(
            b"observation_date,DGS10\n2026-10-30,99\n", ["DGS10"], date(2026, 10, 29)
        )
        == {}
    )


def test_material_news_suspends_plans_and_cancels_only_pending_entries(
    config, broker, plan, monkeypatch
):
    import concurrent.futures
    import agent_trader.runtime.supervisor as module

    monkeypatch.setattr(module, "Broker", lambda _: broker)
    s = module.Supervisor(config)
    try:
        s.engine.add_plans([plan], "2026-10-30")
        order = s.engine.submit_intent(
            {
                "client_order_id": "pending-news",
                "symbol": "AAPL",
                "side": "buy",
                "qty": "1",
                "type": "limit",
                "limit_price": "100",
            },
            "intraday",
            plan["id"],
        )
        s.future = concurrent.futures.Future()
        s.future.set_result(
            {
                "summary": "A material verified event changed the context.",
                "material_change": True,
                "affected_symbols": ["AAPL"],
                "events": [],
                "sources": [],
                "unknowns": [],
            }
        )
        s.task = ("pulse-test", "pulse", {}, "2026-10-30")
        s.finish_task()
        assert s.store.get("research_refresh_required") is True
        assert s.store.rows("SELECT state FROM plans")[0]["state"] == "suspended"
        assert broker.order(order["id"])["status"] == "canceled"
    finally:
        s.pool.shutdown(wait=False)
        s.publisher_pool.shutdown(wait=False)
        s.store.close()


def test_stale_exit_intent_cannot_close_a_new_position_of_same_symbol(config, broker, monkeypatch):
    from datetime import datetime
    from agent_trader.runtime.config import ET
    import agent_trader.runtime.supervisor as module

    monkeypatch.setattr(module, "Broker", lambda _: broker)
    s = module.Supervisor(config)
    calls = []
    s.engine.exit_holding = lambda *args: calls.append(args)
    try:
        now = datetime.now(ET)
        s.store.db.execute(
            "INSERT INTO holdings VALUES(?,?,?,?,?)", ("AAPL", "swing", 1, 100, "new-position")
        )
        s.store.set(
            "exit-intent:AAPL",
            {
                "at": now.isoformat(),
                "reason": "Old thesis invalidated",
                "plan_id": "old-position",
                "branch": "intraday",
            },
        )
        s.market_tick(now, now + timedelta(hours=4))
        assert not calls
        assert s.store.get("exit-intent:AAPL") is None
    finally:
        s.pool.shutdown(wait=False)
        s.publisher_pool.shutdown(wait=False)
        s.store.close()


def test_memory_expiration_uses_utc_across_eastern_standard_time(store):
    store.memory_put("brief", "observation", {}, "2026-11-02T23:59:59-05:00")
    assert store.rows("SELECT id FROM memory WHERE expires>'2026-11-03T01:00:00+00:00'")
    assert not store.rows("SELECT id FROM memory WHERE expires>'2026-11-03T05:00:00+00:00'")


def test_position_review_worker_requests_batched_schema(config, monkeypatch):
    from agent_trader.runtime import supervisor
    from agent_trader.runtime.models import PortfolioReview

    captured = {}

    def infer(config, role, prompt, schema, model, effort, day, **kwargs):
        captured["schema"] = schema
        return {"decisions": []}

    monkeypatch.setattr(supervisor, "run_task", infer)
    result = supervisor.worker(config, "position_review", {"positions": []}, "2026-10-29")
    assert captured["schema"] is PortfolioReview
    assert result == {"decisions": []}


def test_watchdog_heartbeat_written_before_broker_preflight_and_independent_of_export(
    config, broker, monkeypatch, now
):
    import json
    import os
    from agent_trader.runtime import supervisor

    monkeypatch.setattr(supervisor, "Broker", lambda _: broker)
    s = supervisor.Supervisor(config)
    try:
        s.preflight = lambda: (_ for _ in ()).throw(RuntimeError("simulated broker outage"))
        s.store.set(
            "calendar:" + now.astimezone(supervisor.ET).date().isoformat(),
            [{"open": "09:30", "close": "16:00"}],
        )
        with pytest.raises(RuntimeError, match="simulated broker outage"):
            s.tick(now)
        heartbeat = json.loads((config.state_dir / "heartbeat.json").read_text())
        assert heartbeat["pid"] == os.getpid()
        assert heartbeat["schema"] == 1
        assert heartbeat["at"] == now.astimezone(supervisor.ET).isoformat()
        assert not (config.root / "docs/data/lab.json").exists()
    finally:
        s.pool.shutdown(wait=False)
        s.publisher_pool.shutdown(wait=False)
        s.store.close()


def test_windows_push_and_authentication_use_hidden_gui_launcher(config, store, monkeypatch):
    from dataclasses import replace
    from pathlib import Path
    from types import SimpleNamespace
    from agent_trader.runtime import publish as module

    c = replace(config, root=Path("/mnt/c/Users/test/trader"), publish=True)
    calls = []
    git_calls = []
    monkeypatch.setattr(module, "export", lambda *args: None)
    monkeypatch.setattr(module.os.path, "exists", lambda path: True)
    monkeypatch.setattr(
        module,
        "git_run",
        lambda config, args: (
            git_calls.append(args)
            or SimpleNamespace(
                returncode=0,
                stdout="revision" if args[0] == "rev-parse" else "",
            )
        ),
    )
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda args, **kwargs: calls.append(args) or SimpleNamespace(returncode=0),
    )
    assert module.publish(c, store)["status"] == "pushed"
    assert not any(args[0] == "push" for args in git_calls)
    assert calls == [
        [
            "/mnt/c/Windows/System32/wscript.exe",
            "//B",
            "//NoLogo",
            r"C:\Users\test\trader\scripts\runtime\hidden-launch.vbs",
            "publish",
        ]
    ]
