"""Remaining local result roles publish only complete, owned applications."""
import json
from datetime import datetime, timezone

import pytest

from agent_trader.runtime import research_work
from agent_trader.runtime.models import Decision, PortfolioReview, ExplorationReport
from tests.runtime import test_atomic_applications as applications
from tests.runtime.test_atomic_applications import queue, FailExecute
from tests.runtime.test_exploration import draft
from tests.runtime.test_research_work import draft_for, review_for

runtime = applications.runtime


def failed(runtime):
    assert runtime.store.rows("SELECT state FROM jobs")[0]["state"] == "failed"
    assert json.loads(runtime.store.rows("SELECT payload FROM usage")[0]["payload"])["application_outcome"] == "rejected"
    assert runtime.qualities == ["rejected"]


def finish_with_fault(runtime, check):
    connection = runtime.store.db
    fault = FailExecute(connection, check)
    runtime.store.db = fault
    try:
        runtime.finish_task()
    finally:
        runtime.store.db = connection
    assert fault.fired
    failed(runtime)


def test_decision_late_event_failure_rolls_back_approval_and_can_retry(runtime, plan):
    runtime.engine.add_plans([plan], "2026-11-07")
    result = Decision.model_validate({
        "plan_id": plan["id"], "action": "approve", "reason": "The recorded checks support this bounded plan.",
        "contradictions": [], "evidence_fresh": True,
    }).model_dump(mode="json")
    queue(runtime, result, role="decision", context={"plan": plan})
    finish_with_fault(runtime, lambda sql, args: "INTO events" in sql and args[1] == "decision")
    assert runtime.store.rows("SELECT state FROM plans")[0]["state"] == "planned"
    assert runtime.store.get("approval:" + plan["id"]) is None
    assert runtime.store.get("entry_budget_blocked") is True
    assert runtime.store.rows("SELECT * FROM orders") == []
    queue(runtime, result, role="decision", context={"plan": plan})
    runtime.finish_task()
    assert runtime.store.rows("SELECT state FROM plans")[0]["state"] == "approved"
    assert runtime.store.get("approval:" + plan["id"])["decision"] == result


def test_changed_job_owner_cannot_apply_or_falsely_accept_decision(runtime, plan):
    runtime.engine.add_plans([plan], "2026-11-07")
    result = Decision.model_validate({
        "plan_id": plan["id"], "action": "approve", "reason": "The recorded checks support this bounded plan.",
        "contradictions": [], "evidence_fresh": True,
    }).model_dump(mode="json")
    queue(runtime, result, role="decision", context={"plan": plan})
    runtime.store.db.execute("UPDATE jobs SET owner=?", ('{"claim":"replacement-owner"}',))
    runtime.finish_task()
    assert runtime.store.rows("SELECT state FROM jobs")[0]["state"] == "running"
    assert runtime.store.rows("SELECT state FROM plans")[0]["state"] == "planned"
    assert runtime.store.get("approval:" + plan["id"]) is None
    assert json.loads(runtime.store.rows("SELECT payload FROM usage")[0]["payload"])["application_outcome"] == "rejected"
    assert runtime.qualities == ["rejected"] and runtime.incidents


def test_position_review_failure_leaves_no_actionable_exit_intent(runtime, monkeypatch):
    context = {"positions": [{"holding": {"symbol": symbol, "branch": "swing", "plan_id": "plan-" + symbol}}
                              for symbol in ("AAPL", "MSFT")]}
    for symbol in ("AAPL", "MSFT"):
        runtime.store.db.execute("INSERT INTO holdings VALUES(?,?,?,?,?)", (symbol, "swing", 1, 100, "plan-" + symbol))
    result = PortfolioReview.model_validate({"decisions": [
        {"symbol": symbol, "action": "exit", "reason": "The recorded invalidation has occurred.", "evidence_fresh": True, "invalidation_observed": True}
        for symbol in ("AAPL", "MSFT")
    ]}).model_dump(mode="json")
    queue(runtime, result, role="position_review", context=context)
    finish_with_fault(runtime, lambda sql, args: "INTO events" in sql and args[1] == "decision" and json.loads(args[3])["symbol"] == "MSFT")
    assert runtime.store.get("exit-intent:AAPL") is None
    assert runtime.store.get("exit-intent:MSFT") is None
    assert runtime.store.get("entry_budget_blocked") is True
    exits = []
    monkeypatch.setattr(runtime.engine, "exit_holding", lambda symbol, reason: exits.append(symbol) or True)
    runtime.apply_pending_exits(datetime.now(timezone.utc))
    assert exits == []
    assert runtime.broker.submissions == 0
    queue(runtime, result, role="position_review", context=context)
    runtime.finish_task()
    assert runtime.store.get("exit-intent:AAPL") and runtime.store.get("exit-intent:MSFT")


@pytest.mark.parametrize("role", ["weekly", "monthly"])
def test_period_review_second_lesson_failure_rolls_back_report_and_all_lessons(runtime, role):
    result = {"summary": "A bounded period review", "proposed_lessons": ["First proposed lesson", "Second proposed lesson"]}
    queue(runtime, result, role=role)
    finish_with_fault(runtime, lambda sql, args: "INTO memory" in sql and args[0].endswith(":lesson:1"))
    assert runtime.store.get(role + ":2026-11-07") is None
    lessons = runtime.store.rows("SELECT payload FROM memory WHERE layer='lesson'")
    assert lessons == []
    assert runtime.store.rows("SELECT * FROM plans") == []
    queue(runtime, result, role=role)
    runtime.finish_task()
    assert runtime.store.get(role + ":2026-11-07") == result
    assert len(runtime.store.rows("SELECT id FROM memory WHERE layer='lesson'")) == 2


def test_exploration_marker_failure_rolls_back_new_draft_and_preserves_old_cursor(runtime):
    runtime.store.set("exploration_observation_ids", ["previous-observation"])
    result = ExplorationReport.model_validate(draft(datetime.now(timezone.utc))).model_dump(mode="json")
    queue(runtime, result, role="exploration", context={"observation_ids": ["current-observation"]})
    finish_with_fault(runtime, lambda sql, args: "INTO kv" in sql and args[0] == "exploration_observation_ids")
    assert runtime.store.get("exploration_draft") is None
    assert runtime.store.get("exploration_day") is None
    assert runtime.store.get("exploration_observation_ids") == ["previous-observation"]
    assert runtime.store.get("exploration_validated_draft") is None
    queue(runtime, result, role="exploration", context={"observation_ids": ["current-observation"]})
    runtime.finish_task()
    assert runtime.store.get("exploration_draft")["summary"] == result["summary"]
    assert runtime.store.get("exploration_observation_ids") == ["current-observation"]


@pytest.mark.parametrize("review", [False, True])
def test_deep_stage_completion_failure_rolls_back_only_current_stage_and_retries(runtime, review):
    context = research_work._context("event_coverage", {
        "records": [{"id": "ev:scratch", "kind": "research", "value": {"gap": "unknown"}}],
        "omitted_records": 0,
    })
    report = draft_for(context)
    if review:
        research_work.record_analysis(runtime.store, context, report, "2026-11-07")
    result = review_for(context, report) if review else report
    role = "deep_research_review" if review else "deep_research"
    queue(runtime, result, role=role, context=context)
    finish_with_fault(runtime, lambda sql, args: "UPDATE jobs SET state=" in sql and args[0] == "done")
    stage = "review" if review else "analysis"
    key = "research-work:" + context["work_id"] + ":" + stage
    assert runtime.store.rows("SELECT id FROM memory WHERE id=?", (key,)) == []
    assert runtime.store.get("research-work-failure:batch-research")["attempts"] == 1
    proposals = runtime.store.rows("SELECT id FROM memory WHERE layer='improvement_proposal'")
    assert proposals == []
    assert runtime.store.rows("SELECT * FROM plans") == []
    queue(runtime, result, role=role, context=context)
    runtime.finish_task()
    assert runtime.store.rows("SELECT state FROM jobs")[0]["state"] == "done"
    assert len(runtime.store.rows("SELECT id FROM memory WHERE id=?", (key,))) == 1
    assert len(runtime.store.rows("SELECT id FROM memory WHERE layer='improvement_proposal'")) == (1 if review else 0)
