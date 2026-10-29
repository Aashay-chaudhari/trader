import json
from datetime import datetime, timedelta, timezone

import pytest

from agent_trader.runtime.experiments import Experiments
from agent_trader.runtime.exploration import (
    clean_bars,
    historical_screen,
    knowledge_context,
    record_report,
    record_validation,
    seed_challengers,
    sprint_active,
)
from agent_trader.runtime.research import research_prompt
from agent_trader.runtime.store import dumps


def contract(change, branch="intraday", eid=None):
    return {
        "id": eid or "trial-" + change,
        "branch": branch,
        "hypothesis": "Test a distinct opportunity filter",
        "exact_change": change,
        "parent_version": "pilot-v1",
        "minimum_sessions": 20,
        "minimum_samples": 30,
        "cost_model": "20bp + spread",
        "metrics": ["paired return"],
    }


def test_multiple_challengers_share_paired_observations(store, plan, quote, now):
    seed_challengers(store)
    seed_challengers(store)
    assert len(store.rows("SELECT * FROM experiments WHERE state='shadow'")) == 8
    e = Experiments(store)
    e.consider(plan, quote, "mixed", now)
    e.consider(plan, quote, "mixed", now)
    samples = store.rows("SELECT payload FROM shadow")
    assert len(samples) == 4
    values = [json.loads(s["payload"]) for s in samples]
    assert len({s["entry"] for s in values}) == 1
    assert {s["challenger_trades"] for s in values} == {True, False}
    e.mark(
        {"AAPL": {**quote, "bp": 108, "ap": 108.01, "t": (now + timedelta(minutes=1)).isoformat()}},
        now + timedelta(minutes=1),
    )
    assert len(store.rows("SELECT * FROM shadow WHERE state='closed'")) == 4
    assert not e.evaluate()
    assert not store.rows("SELECT * FROM orders")


def test_parallel_cap_and_duplicate_filters(store):
    e = Experiments(store)
    source = "def candidate_filter(plan, context):\n return True\n"
    for i in range(6):
        assert e.register({**contract("code:" + str(i)), "source": source})
    assert not e.register({**contract("code:seventh"), "source": source})


def test_no_profitable_promotion_from_abstention_or_repeated_peeking(store):
    e = Experiments(store)
    e.register(contract("require_risk_on"))
    for i in range(40):
        p = {"day": f"2026-09-{i // 2 + 1:02}", "incumbent_return": -0.01, "challenger_return": 0}
        store.db.execute(
            "INSERT INTO shadow VALUES(?,?,?,?,?,?)",
            (str(i), "trial-require_risk_on", "AAPL", "intraday", "closed", dumps(p)),
        )
    assert not e.evaluate()
    count = len(store.rows("SELECT * FROM events WHERE kind='experiment_review'"))
    assert count == 1
    assert not e.evaluate()
    assert len(store.rows("SELECT * FROM events WHERE kind='experiment_review'")) == count


def bars():
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(180):
        price = 100 + i * 0.3
        rows.append(
            {
                "t": (start + timedelta(days=i)).isoformat(),
                "o": price,
                "h": price + 2,
                "l": price - 1,
                "c": price + 1,
            }
        )
    return {"AAPL": rows, "SPY": rows}


def test_fixed_historical_screen_is_reproducible_and_excludes_today():
    data = bars()
    report = historical_screen(data, "2026-01-01")
    assert report["trial_count"] == 12
    assert all(t["holdout"]["sessions"] and t["development"]["sessions"] for t in report["trials"])
    assert all(t["state"] == "historical_screen_only" for t in report["trials"])
    assert report["dataset_sha256"] == historical_screen(data, "2026-01-01")["dataset_sha256"]
    data["AAPL"].append({"t": "2026-01-01T05:00:00Z", "o": 900, "h": 900, "l": 900, "c": 900})
    assert report["dataset_sha256"] == historical_screen(data, "2026-01-01")["dataset_sha256"]
    assert all(r["day"] < "2026-01-01" for r in clean_bars(data, "2026-01-01")["AAPL"])


def test_historical_screen_missing_data_is_not_success():
    with pytest.raises(ValueError):
        historical_screen({}, "2026-01-01")


def draft(now):
    source = {
        "title": "Primary research",
        "url": "https://example.com/paper",
        "published_at": None,
        "observed_at": now.isoformat(),
        "takeaway": "A mechanism, not demonstrated profit.",
    }
    h = {
        "id": "hypothesis-one",
        "branch": "intraday",
        "family": "momentum",
        "claim": "Trend persistence is worth testing after costs.",
        "mechanism": "Information can diffuse into prices over time.",
        "falsification": "Reject when net paired forward return is not positive.",
        "free_data_feasibility": "ready",
        "source_urls": [source["url"]],
        "screen_trial_ids": [],
        "experiment_ids": ["trial-require_risk_on"],
    }
    return {
        "summary": "Research awaiting validation",
        "hypotheses": [h],
        "experiments": [contract("require_risk_on")],
        "shadow_plans": [],
        "sources": [source],
        "uncertainties": ["Not proven"],
    }


def validation(verdict="accepted_for_testing"):
    return {
        "summary": "Source and method reviewed; profitability unproven",
        "hypotheses": [
            {
                "id": "hypothesis-one",
                "verdict": verdict,
                "reason": "Mechanism and falsification are suitable for a forward test.",
            }
        ],
    }


def test_validation_gates_morning_reuse_and_keeps_rejected_work(store):
    now = datetime.now(timezone.utc)
    record_report(store, draft(now), now.date().isoformat())
    assert not knowledge_context(store)["reviewed_research"]
    assert not store.rows("SELECT * FROM experiments")
    record_validation(store, validation())
    context = knowledge_context(store)
    assert context["reviewed_research"][0]["evidence_level"] == "reviewed_hypothesis"
    prompt = research_prompt(now.date().isoformat(), {"market": {}}, store)
    assert "hypothesis-one" in prompt
    assert "not demonstrated profitability" not in prompt  # no invented evidence status
    assert "Never treat research review" in prompt
    assert store.rows("SELECT state FROM experiments")[0]["state"] == "shadow"
    record_report(store, draft(now), now.date().isoformat())
    record_validation(store, validation("rejected"))
    assert not knowledge_context(store)["reviewed_research"]
    assert len(knowledge_context(store)["rejected_or_incomplete"]) == 1
    assert len(store.rows("SELECT * FROM memory WHERE layer='research_review'")) == 2


def test_invented_citations_or_unknown_screen_cannot_be_accepted(store):
    now = datetime.now(timezone.utc)
    d = draft(now)
    d["hypotheses"][0]["source_urls"] = ["https://invented.example/paper"]
    record_report(store, d, now.date().isoformat())
    record_validation(store, validation())
    assert not knowledge_context(store)["reviewed_research"]
    assert not store.rows("SELECT * FROM experiments")


def test_incomplete_validation_cannot_partially_activate(store):
    now = datetime.now(timezone.utc)
    record_report(store, draft(now), now.date().isoformat())
    with pytest.raises(ValueError):
        record_validation(store, {"summary": "invalid", "hypotheses": []})
    assert not store.get("research_catalogue")


def test_forward_evidence_joins_reviewed_research_at_morning_retrieval(store):
    now = datetime.now(timezone.utc)
    record_report(store, draft(now), now.date().isoformat())
    record_validation(store, validation())
    store.db.execute("UPDATE experiments SET state='promoted'")
    assert (
        knowledge_context(store)["reviewed_research"][0]["evidence_level"]
        == "forward_validated_filter"
    )
    store.db.execute("UPDATE experiments SET state='rolled_back'")
    card = knowledge_context(store)["reviewed_research"][0]
    assert card["evidence_level"] == "reviewed_hypothesis" and "caution" in card


def test_sprint_ends_after_ten_unique_mornings(store):
    assert sprint_active(store)
    store.set("exploration_sessions", [str(i) for i in range(10)])
    assert not sprint_active(store)


def test_research_shadow_plans_never_enter_broker_order_path(config, broker, monkeypatch, plan):
    from agent_trader.runtime import supervisor
    from agent_trader.runtime.config import ET

    monkeypatch.setattr(supervisor, "Broker", lambda _: broker)
    s = supervisor.Supervisor(config)
    try:
        now = datetime.now(ET)
        p = {
            **plan,
            "expires_at": (now + timedelta(hours=1)).isoformat(),
            "evidence": [{**plan["evidence"][0], "observed_at": now.isoformat()}],
        }
        seed_challengers(s.store)
        s.store.set("exploration_shadow_plans", [p])
        s.store.set("brief", {"regime": "mixed"})
        s.market_tick(now, now + timedelta(hours=4))
        assert len(s.store.rows("SELECT * FROM shadow")) == 4
        assert not s.store.rows("SELECT * FROM plans")
        assert broker.submissions == 0
    finally:
        s.pool.shutdown(wait=False)
        s.publisher_pool.shutdown(wait=False)
        s.store.close()


def test_morning_prompt_keeps_reviewed_research_and_market_data_in_budget(store):
    now = datetime.now(timezone.utc)
    record_report(store, draft(now), now.date().isoformat())
    record_validation(store, validation())
    for i in range(8):
        store.memory_put(str(i), "observation", {"obsolete_brief": "x" * 20000})
    prompt = research_prompt(
        now.date().isoformat(),
        {"market": {"AAPL": {"latestQuote": {"bp": 101, "ap": 102, "t": now.isoformat()}}}},
        store,
    )
    assert "hypothesis-one" in prompt and '"AAPL"' in prompt and len(prompt) < 28000
    assert "obsolete_brief" not in prompt


def test_research_validator_uses_its_own_persistent_thread(config, monkeypatch):
    from agent_trader.runtime import agent
    from agent_trader.runtime.models import ResearchValidation
    from agent_trader.runtime.store import Store

    day = (
        datetime.now(timezone.utc)
        .astimezone(__import__("zoneinfo").ZoneInfo("America/New_York"))
        .date()
        .isoformat()
    )
    s = Store(config.state_dir / "trader.sqlite3")
    s.set("thread:" + day, "researcher-thread")
    seen = []

    class RPC:
        def __init__(self, config):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def rate_limits(self):
            return {
                "ordinary_usage_allowed": True,
                "windows": [
                    {
                        "usedPercent": 10,
                        "windowDurationMins": 10080,
                        "resetsAt": int(
                            (datetime.now(timezone.utc) + timedelta(days=5)).timestamp()
                        ),
                    }
                ],
            }

        def run(self, thread_id, *args, **kwargs):
            seen.append(thread_id)
            return "reviewer-thread", {"summary": "Independent check", "hypotheses": []}, {}, {}

        def models(self):
            return [{"id": model} for model in (config.research_model, config.light_model)]

    monkeypatch.setattr(agent, "CodexRPC", RPC)
    agent.run_task(
        config,
        "research_validation",
        "Review the supplied evidence",
        ResearchValidation,
        config.research_model,
        "medium",
        day,
    )
    assert seen == [None]
    assert s.get("thread:" + day) == "researcher-thread"
    assert s.get("thread:research_validation:" + day) == "reviewer-thread"
    s.close()


def test_validator_receives_actual_screen_metrics_not_only_trial_names(store):
    from agent_trader.runtime.exploration import validation_prompt

    store.set(
        "historical_screen",
        {"trials": [{"id": "swing-reversal", "holdout": {"mean_daily_net": 0.00123}}]},
    )
    prompt = validation_prompt(store)
    assert "0.00123" in prompt
    assert "five-session swing returns are NOT daily portfolio returns" in prompt
