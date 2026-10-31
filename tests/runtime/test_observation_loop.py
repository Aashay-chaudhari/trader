"""Independent review, handoff and scheduler boundaries for observation-led learning."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from agent_trader.runtime.exploration import record_report, record_validation, exploration_prompt
from agent_trader.runtime.intelligence import capture_observations
from agent_trader.runtime.models import ExplorationReport, ResearchValidation
from agent_trader.runtime.quality import daily_audit


def observation_draft(store):
    now = datetime.now(timezone.utc)
    day = (now - timedelta(days=1)).date().isoformat()
    packet = {
        "observed_at": now.isoformat(),
        "daily_indicators": {
            "SPY": {"return_1d": 0.01, "asof": day},
            "AAPL": {"return_1d": 0.04, "return_3d": 0.03, "asof": day, "last_daily_close": 100},
        },
    }
    lead = capture_observations(store, packet, now=now)[0]
    contract = {
        "id": "observed-relative-v1",
        "hypothesis_id": "relative-response",
        "branch": "intraday",
        "symbols": ["AAPL", "MSFT"],
        "predicates": [{"field": "relative_gap_spy", "operator": "gte", "value": 0.01}],
        "hypothesis": "Relative strength may persist into the session under this scope.",
        "falsification": "The declared net and stressed observation means fail to beat both comparators.",
        "minimum_sessions": 20,
        "minimum_signals": 30,
    }
    draft = {
        "summary": "A local conjecture, not a claim of established causality.",
        "hypotheses": [
            {
                "id": "relative-response",
                "branch": "intraday",
                "family": "relative-response",
                "claim": contract["hypothesis"],
                "mechanism": "An explicitly conjectural information diffusion mechanism.",
                "falsification": contract["falsification"],
                "evidence_basis": "local_observation",
                "observation_ids": [lead["id"]],
                "alternative_explanations": ["Ordinary market exposure or chance"],
                "predicted_outcome": "Later declared observations show positive net and stressed conditional means.",
                "free_data_feasibility": "ready",
                "source_urls": [],
                "screen_trial_ids": [],
                "experiment_ids": [],
            }
        ],
        "experiments": [],
        "adaptive_contracts": [contract],
        "shadow_plans": [],
        "sources": [],
        "uncertainties": ["Only a conjecture"],
    }
    validation = {
        "summary": "The bounded method is testable; no edge demonstrated",
        "hypotheses": [
            {
                "id": "relative-response",
                "verdict": "accepted_for_testing",
                "reason": "Local observations support asking a prospective, falsifiable question.",
                "source_check_status": "not_applicable",
                "checked_source_urls": [],
                "method_check_status": "reviewed",
            }
        ],
    }
    return draft, validation


def test_local_conjecture_needs_real_observation_and_review_not_published_paper(store):
    draft, validation = observation_draft(store)
    draft = ExplorationReport.model_validate(draft).model_dump(mode="json")
    validation = ResearchValidation.model_validate(validation).model_dump(mode="json")
    record_report(store, draft, datetime.now().date().isoformat())
    assert not store.rows("SELECT name FROM sqlite_master WHERE name='adaptive_contracts'")
    record_validation(store, validation)
    assert len(store.rows("SELECT * FROM adaptive_contracts")) == 1
    assert not store.rows("SELECT * FROM plans") and not store.rows("SELECT * FROM orders")
    assert daily_audit(store, "2026-10-31")["reviewed_without_explicit_source_attestation"] == 0
    card = store.get("research_catalogue")[0]
    assert card["observation_provenance_verified"] and card["state"] == "reviewed_for_testing"


@pytest.mark.parametrize("broken", ["observation", "method", "future", "external"])
def test_missing_or_postdraft_evidence_cannot_register_adaptive_contract(store, broken):
    draft, validation = observation_draft(store)
    if broken == "observation":
        draft["hypotheses"][0]["observation_ids"] = ["invented"]
    if broken == "method":
        validation["hypotheses"][0]["method_check_status"] = "unreviewed"
    if broken == "external":
        draft["hypotheses"][0]["evidence_basis"] = "mixed"
        draft["hypotheses"][0]["source_urls"] = ["https://example.com/unchecked"]
    record_report(store, draft, datetime.now().date().isoformat())
    if broken == "future":
        d = store.get("exploration_draft")
        d["at"] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        store.set("exploration_draft", d)
    record_validation(store, validation)
    assert not store.rows("SELECT * FROM adaptive_contracts")
    assert store.get("research_catalogue")[0]["state"] == "needs_work"


def test_unrelated_reviewed_branch_does_not_admit_shadow_plan(store, plan):
    draft, validation = observation_draft(store)
    draft["shadow_plans"] = [{**plan, "hypothesis_id": "unrelated-old-card"}]
    record_report(store, draft, datetime.now().date().isoformat())
    record_validation(store, validation)
    assert store.get("exploration_shadow_plans") == []
    draft["shadow_plans"][0]["hypothesis_id"] = "relative-response"
    record_report(store, draft, datetime.now().date().isoformat())
    record_validation(store, validation)
    assert len(store.get("exploration_shadow_plans")) == 1


def test_exploration_context_stays_complete_and_keeps_instructions(store):
    draft, _ = observation_draft(store)
    store.set(
        "research_catalogue",
        [{**draft["hypotheses"][0], "claim": "x" * 3000, "id": str(i)} for i in range(50)],
    )
    prompt = exploration_prompt("2026-10-31", store, {"trials": []})
    assert len(prompt) < 28000
    context = json.loads(prompt.split("CONTEXT:\n", 1)[1])
    assert context["omitted_for_budget"] and context["observations"]["records"]
    assert "FUTURE sessions only" in prompt and "competing explanation" in prompt


def test_discovery_continues_after_sprint_on_new_observations(config, monkeypatch, broker):
    from agent_trader.runtime import supervisor
    from agent_trader.runtime.config import ET

    monkeypatch.setattr(supervisor, "Broker", lambda _: broker)
    s = supervisor.Supervisor(config)
    try:
        observation_draft(s.store)
        s.store.set("exploration_sessions", [str(i) for i in range(10)])
        now = datetime(2026, 11, 3, 8, 40, tzinfo=ET)
        calls = []
        s.launch = lambda *args: calls.append(args) or True
        assert s.launch_exploration(now, now.replace(hour=16))
        assert calls[0][1] == "exploration" and calls[0][2]["observation_ids"]
    finally:
        s.pool.shutdown(wait=False)
        s.publisher_pool.shutdown(wait=False)
        s.store.close()


def test_old_referenced_observation_is_in_validator_packet(store):
    from agent_trader.runtime.exploration import validation_prompt

    draft, _ = observation_draft(store)
    identity = draft["hypotheses"][0]["observation_ids"][0]
    for i in range(80):
        store.memory_put(
            f"newer:{i}", "market_observation_lead", {"id": f"newer:{i}", "values": {}}
        )
    record_report(store, draft, datetime.now().date().isoformat())
    prompt = validation_prompt(store)
    assert f'"id":"{identity}"' in prompt
    assert '"relative_return_1d"' in prompt and len(prompt) < 28000


def test_oversized_input_rejected_before_model_call(config, monkeypatch):
    from agent_trader.runtime import agent

    monkeypatch.setattr(
        agent, "CodexRPC", lambda *_: pytest.fail("No model call for a truncated packet")
    )
    with pytest.raises(agent.AgentUnavailable, match="Complete evidence"):
        agent.run_task(
            config,
            "exploration",
            "x" * (config.max_input_chars + 1),
            ExplorationReport,
            config.research_model,
            "high",
            "2026-10-31",
        )


def test_completed_fresh_open_job_allows_requested_refresh(config, monkeypatch, broker):
    from agent_trader.runtime import supervisor
    from agent_trader.runtime.config import ET

    monkeypatch.setattr(supervisor, "Broker", lambda _: broker)
    monkeypatch.setattr(supervisor, "notify", lambda *a, **k: True)
    s = supervisor.Supervisor(config)
    now = datetime.now(ET).replace(hour=9, minute=55, second=0, microsecond=0)
    day = now.date().isoformat()
    broker.clock = lambda: {"is_open": True, "timestamp": now.isoformat()}
    s.store.set("calendar:" + day, [{"open": "09:30", "close": "16:00"}])
    s.store.set("preflight_day", day)
    s.store.set("brief_day", day)
    s.store.set("needs_research", True)
    s.store.set("readiness", {"execution_verified": True, "funded": True, "models_available": True})
    s.maybe_publish = lambda: None
    calls = []
    s.launch = lambda key, *args: calls.append(key) or key.startswith("refresh:")
    try:
        s.tick(now)
        assert calls == ["fresh-open-research:" + day, "refresh:" + day + ":09"]
        assert not s.store.get("needs_research")
    finally:
        s.pool.shutdown(wait=False)
        s.publisher_pool.shutdown(wait=False)
        s.store.close()


def test_shadow_bad_dates_cannot_interrupt_observation_marking(config, monkeypatch, broker, plan):
    from agent_trader.runtime import supervisor
    from agent_trader.runtime.config import ET

    monkeypatch.setattr(supervisor, "Broker", lambda _: broker)
    s = supervisor.Supervisor(config)
    now = datetime.now(ET)
    p = {
        **plan,
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "evidence": [{**plan["evidence"][0], "observed_at": now.replace(tzinfo=None).isoformat()}],
    }
    s.store.set("exploration_shadow_plans", [p])
    s.store.set("calendar:" + now.date().isoformat(), [{"open": "09:30", "close": "16:00"}])
    marked = []
    s.cohorts.mark = lambda *args: marked.append(True)
    try:
        s.market_tick(now, now + timedelta(hours=4))
        assert marked and not s.store.rows("SELECT * FROM shadow")
        assert broker.submissions == 0
    finally:
        s.pool.shutdown(wait=False)
        s.publisher_pool.shutdown(wait=False)
        s.store.close()


def test_all_output_schema_properties_explicit_including_defaulted_nested_fields():
    from agent_trader.runtime.agent import response_schema

    schema = response_schema(ExplorationReport)
    assert "adaptive_contracts" in schema["required"]
    assert "evidence_basis" in schema["$defs"]["ResearchHypothesis"]["required"]
    assert "minimum_sessions" in schema["$defs"]["AdaptiveContract"]["required"]
    assert "default" not in schema["$defs"]["AdaptiveContract"]["properties"]["minimum_sessions"]
    assert (
        "method_check_status"
        in response_schema(ResearchValidation)["$defs"]["HypothesisValidation"]["required"]
    )


def test_tested_hypothesis_claim_cannot_be_rewritten_under_same_id(store):
    draft, validation = observation_draft(store)
    record_report(store, draft, datetime.now().date().isoformat())
    record_validation(store, validation)
    old = store.get("research_catalogue")[0]
    draft["hypotheses"][0]["claim"] = (
        "A different claim cannot inherit the original future observations."
    )
    record_report(store, draft, datetime.now().date().isoformat())
    record_validation(store, validation)
    assert store.get("research_catalogue")[0]["claim"] == old["claim"]
    assert len(store.rows("SELECT * FROM adaptive_contracts")) == 1


def test_semantically_rejected_model_reply_keeps_measured_usage_and_full_artifact(
    config, monkeypatch
):
    from agent_trader.runtime import agent
    from agent_trader.runtime.store import Store
    from agent_trader.runtime.models import Decision

    class RPC:
        def __init__(self, config):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def rate_limits(self):
            return {}

        def run(self, *args, **kwargs):
            return (
                "test-thread",
                {"summary": "Invalid schema output retained"},
                {"last": {"inputTokens": 120, "outputTokens": 40}},
                {"searches": 0, "cycles": 1},
            )

    monkeypatch.setattr(agent, "CodexRPC", RPC)
    monkeypatch.setattr(agent, "budget_check", lambda *a: (True, "test"))
    with pytest.raises(ValueError):
        agent.run_task(
            config,
            "research",
            "Read evidence",
            Decision,
            config.research_model,
            "low",
            "2026-10-31",
        )
    s = Store(config.state_dir / "trader.sqlite3")
    try:
        usage = s.rows("SELECT input_tokens,output_tokens,payload FROM usage")[0]
        assert usage["input_tokens"] == 120 and usage["output_tokens"] == 40
        assert json.loads(usage["payload"])["state"] == "failed"
        output = json.loads(
            s.rows("SELECT payload FROM memory WHERE layer='research_artifact'")[0]["payload"]
        )
        assert (
            output["outcome"] == "rejected"
            and output["result"]["summary"] == "Invalid schema output retained"
        )
    finally:
        s.close()


def test_supported_symbols_are_visible_in_transport_schema_and_designer_context(store):
    from agent_trader.runtime.agent import response_schema
    from agent_trader.runtime.config import RESEARCH_UNIVERSE

    schema = response_schema(ExplorationReport)
    symbols = schema["$defs"]["AdaptiveContract"]["properties"]["symbols"]["items"]["enum"]
    assert symbols == RESEARCH_UNIVERSE and "SMH" not in symbols
    context = json.loads(exploration_prompt("2026-10-31", store, {}).split("CONTEXT:\n", 1)[1])
    assert context["allowed_adaptive_symbols"] == RESEARCH_UNIVERSE
