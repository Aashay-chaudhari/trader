import json
from datetime import timedelta

from agent_trader.runtime.experiments import Experiments
from agent_trader.runtime.exploration import exploration_prompt, seed_challengers
from agent_trader.runtime.research import research_prompt, review_prompt


def test_empty_plan_stream_is_diagnosed_without_inventing_samples(store, now):
    seed_challengers(store)
    lab = Experiments(store)
    before = lab.funnel()
    assert before["tracking"] == "not_yet_observed"
    assert before["latest_eligibility"] is None
    assert before["branches"]["intraday"]["current_bottleneck"] == "no_plan_inputs"
    lab.record_funnel([], [], {}, now)
    snapshot = lab.funnel()["latest_eligibility"]
    assert snapshot["branches"]["intraday"]["state"] == "no_valid_plan_stream"
    assert snapshot["branches"]["intraday"]["reasons"] == {}
    assert not store.rows("SELECT * FROM shadow")
    assert not store.rows("SELECT * FROM plans")
    assert not lab.evaluate()


def test_funnel_records_actual_blocks_and_only_one_snapshot_per_slot(store, plan, quote, now):
    lab = Experiments(store)
    seed_challengers(store)
    stale = {**quote, "t": (now - timedelta(minutes=5)).isoformat()}
    research_plan = {**plan, "id": "research-plan", "event_risk_known": False}
    first = lab.record_funnel([plan], [research_plan], {"AAPL": stale}, now)
    assert first["branches"]["intraday"]["reasons"] == {
        "invalid_or_stale_quote": 1,
        "event_risk_unknown": 1,
    }
    assert lab.record_funnel([plan], [], {"AAPL": quote}, now) == first
    later = now + timedelta(minutes=5)
    second = lab.record_funnel([plan], [], {"AAPL": {**quote, "t": later.isoformat()}}, later)
    assert second["branches"]["intraday"]["reasons"] == {"eligible_for_observation": 1}
    history = store.get("experiment-funnel:" + now.date().isoformat())
    assert len(history["slots"]) == 2
    assert not store.rows("SELECT * FROM shadow")  # eligibility is not a sample


def test_funnel_separates_missing_input_from_price_condition(store, plan, quote, now):
    lab = Experiments(store)
    assert lab.eligibility_reason(plan, None, now) == "missing_quote"
    assert lab.eligibility_reason(plan, {**quote, "bp": 103, "ap": 103.01}, now) == (
        "outside_entry_interval"
    )
    assert lab.eligibility_reason({**plan, "evidence": []}, quote, now) == ("evidence_not_fresh")
    assert (
        lab.eligibility_reason({**plan, "expires_at": now.isoformat()}, quote, now)
        == "expired_plan"
    )


def test_missed_intraday_exit_cannot_be_closed_with_next_session_price(store, plan, quote, now):
    seed_challengers(store)
    lab = Experiments(store)
    store.set("calendar:" + now.date().isoformat(), [{"open": "09:30", "close": "16:00"}])
    lab.consider(plan, quote, "mixed", now)
    tomorrow = now + timedelta(days=1)
    lab.mark({"AAPL": {"bp": 108, "ap": 108.01, "t": tomorrow.isoformat()}}, tomorrow)
    rows = store.rows("SELECT state,payload FROM shadow")
    assert len(rows) == 4
    assert all(r["state"] == "not_evaluable" for r in rows)
    assert all(json.loads(r["payload"])["incumbent_return"] is None for r in rows)
    assert all(p["samples"] == 0 for p in lab.progress().values())
    assert not lab.evaluate()


def test_early_close_missing_quote_expires_at_actual_close(store, plan, quote, now):
    from agent_trader.runtime.config import ET

    seed_challengers(store)
    lab = Experiments(store)
    local = now.astimezone(ET)
    store.set("calendar:" + local.date().isoformat(), [{"open": "09:30", "close": "13:00"}])
    lab.consider(plan, quote, "risk_on", now)
    exit_window = local.replace(hour=12, minute=48)
    lab.mark({}, exit_window)
    assert all(r["state"] == "open" for r in store.rows("SELECT state FROM shadow"))
    lab.mark({}, local.replace(hour=13, minute=0))
    assert all(r["state"] == "not_evaluable" for r in store.rows("SELECT state FROM shadow"))


def test_parent_change_cannot_mix_new_incumbent_with_old_experiment(store, plan, quote, now):
    seed_challengers(store)
    store.set("incumbent_filter:intraday", {"id": "new-parent", "filter": "avoid_risk_off"})
    lab = Experiments(store)
    lab.consider(plan, quote, "risk_on", now)
    assert not store.rows("SELECT * FROM shadow")
    assert not lab.evaluate()
    assert all(
        r["state"] == "stale_parent"
        for r in store.rows("SELECT state FROM experiments WHERE branch='intraday'")
    )


def test_executable_and_research_inputs_both_need_fresh_evidence(store, plan, quote, now):
    seed_challengers(store)
    lab = Experiments(store)
    lab.consider({**plan, "event_risk_known": False}, quote, "risk_on", now)
    stale_evidence = [{**plan["evidence"][0], "observed_at": (now - timedelta(days=2)).isoformat()}]
    lab.consider({**plan, "evidence": stale_evidence}, quote, "risk_on", now)
    lab.consider({**plan, "evidence": []}, quote, "risk_on", now)
    assert not store.rows("SELECT * FROM shadow")
    lab.consider(plan, quote, "risk_on", now)
    assert len(store.rows("SELECT * FROM shadow")) == 4
    payload = json.loads(store.rows("SELECT payload FROM shadow LIMIT 1")[0]["payload"])
    assert payload["eligibility_version"] == "plan-evidence-v2"
    lab.mark({"AAPL": {"bp": 108, "ap": 108.01}}, now)
    assert all(r["state"] == "open" for r in store.rows("SELECT state FROM shadow"))


def test_mixed_eligibility_scopes_cannot_be_pooled_for_promotion(store):
    from agent_trader.runtime.store import dumps

    seed_challengers(store)
    experiment_id = "explore-intraday-require_risk_on"
    for i in range(40):
        payload = {
            "day": f"2026-10-{i // 2 + 1:02d}",
            "incumbent_return": 0.005,
            "challenger_return": 0.01,
        }
        if i >= 20:
            payload["eligibility_version"] = "plan-evidence-v2"
        store.db.execute(
            "INSERT INTO shadow VALUES(?,?,?,?,?,?)",
            (str(i), experiment_id, "AAPL", "intraday", "closed", dumps(payload)),
        )
    lab = Experiments(store)
    assert not lab.evaluate()
    assert not lab.evaluate()
    assert len(store.rows("SELECT * FROM events WHERE kind='experiment_review'")) == 1
    assert lab.progress()[experiment_id]["samples"] == 40
    assert lab.progress()[experiment_id]["eligibility_versions"] == [
        "legacy_unversioned",
        "plan-evidence-v2",
    ]
    assert not store.get("incumbent_filter:intraday")


def test_sampling_bottleneck_reaches_research_and_review_without_history_backfill(store, now):
    seed_challengers(store)
    day = now.date().isoformat()
    prompt = exploration_prompt(day, store, {})
    context = json.loads(prompt.split("CONTEXT:\n", 1)[1])
    assert context["filter_sampling"]["branches"]["swing"]["current_bottleneck"] == "no_plan_inputs"
    prompt = review_prompt(day, store)
    context = json.loads(prompt.split("ROLE: retrospective and experiment designer.\n", 1)[1])
    assert context["filter_sampling"]["tracking"] == "not_yet_observed"
    assert "FILTER SAMPLING:" in research_prompt(day, {}, store)
    assert len(prompt) < 28000


def test_complete_prompt_budget_preserves_current_prices_before_background(store, now, monkeypatch):
    monkeypatch.setattr(
        "agent_trader.runtime.exploration.knowledge_context",
        lambda *a, **k: {
            "reviewed_research": [{"id": str(i), "claim": "background " * 200} for i in range(30)]
        },
    )
    packet = {
        "focus_symbols": ["AAPL"],
        "market": {
            "AAPL": {
                "latestQuote": {"bp": 99.99, "ap": 100, "t": now.isoformat()},
                "dailyBar": {"c": 100, "t": now.isoformat()},
                "prevDailyBar": {"c": 98, "t": (now - timedelta(days=1)).isoformat()},
            }
        },
        "daily_indicators": {"AAPL": {"return_3d": 0.01}},
    }
    prompt = research_prompt(now.date().isoformat(), packet, store)
    context = json.loads(prompt.split("CONTEXT:\n", 1)[1])
    assert len(prompt) <= 27500
    assert context["omitted_for_context_budget"]["reviewed_cards"] > 0
    assert context["structured_observations"]["market"]["AAPL"]["quote"]["ap"] == 100
    market = context["structured_observations"]["market"]["AAPL"]
    assert "daily_close" not in market
    assert market["current_session_bar_close"] == 100
    assert market["current_session_bar_at"] == now.isoformat()
    assert market["prior_close"] == 98
    assert context["structured_observations"]["daily_indicators"]["AAPL"]["return_3d"] == 0.01
