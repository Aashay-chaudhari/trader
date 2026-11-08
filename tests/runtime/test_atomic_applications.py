"""Whole-result persistence, conservative plan refresh and truthful retry outcomes."""
import copy
import json
import sqlite3
from concurrent.futures import Future
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from agent_trader.runtime import supervisor
from agent_trader.runtime.engine import Engine
from agent_trader.runtime.experiments import Experiments
from agent_trader.runtime.exploration import record_report
from agent_trader.runtime.models import Brief, ExplorationReport, ResearchValidation, Review
from agent_trader.runtime.store import dumps
from tests.runtime.test_exploration import contract, draft, validation

@pytest.fixture
def runtime(store, config, broker, monkeypatch):
    instance = supervisor.Supervisor.__new__(supervisor.Supervisor)
    instance.store, instance.config, instance.broker = store, config, broker
    instance.engine = Engine(config, store, broker)
    instance.experiments = Experiments(store)
    instance.qualities, instance.incidents, instance.notifications = [], [], []
    instance.record_quality = lambda day, role, result, key, outcome: instance.qualities.append(outcome)
    instance.incident = lambda *args: instance.incidents.append(args)
    monkeypatch.setattr(supervisor, "notify", lambda *a, **k: instance.notifications.append(a[2:]))
    return instance


def queue(instance, result, role="research", key="batch-research", context=None, *, copy_result=True):
    store = instance.store
    assert store.job_start(key)
    store.db.execute(
        "INSERT INTO usage(at,day,role,model,payload) VALUES(?,?,?,?,?)",
        ("2026-11-07T12:00:00+00:00", "2026-11-07", role, "fake", dumps({
            "task_key": key, "state": "completed", "terminal_outcome": "validated",
            "application_outcome": "pending",
        })),
    )
    instance.task = (key, role, context or {}, "2026-11-07")
    instance.future = Future()
    instance.future.set_result(copy.deepcopy(result) if copy_result else result)


def apply(instance, result, role="research", key="batch-research", context=None):
    queue(instance, result, role, key, context)
    instance.finish_task()
    return instance.store.rows("SELECT state,result FROM jobs WHERE key=?", (key,))[0]


def brief(plan):
    now = datetime.now(timezone.utc)
    plan = copy.deepcopy(plan)
    plan["expires_at"] = (now + timedelta(hours=2)).isoformat()
    plan["evidence"][0]["observed_at"] = now.isoformat()
    plan["evidence"][0]["published_at"] = now.isoformat()
    return Brief.model_validate({
        "summary": "A bounded valid prospective plan batch.", "regime": "mixed",
        **{field: "Unknown" for field in ("rates_bonds", "fed_macro", "earnings", "market_conditions", "cross_market", "narratives")},
        "unknowns": [], "events": [], "sources": [], "plans": [plan],
    }).model_dump(mode="json")


class FailExecute:
    def __init__(self, connection, predicate):
        self.connection, self.predicate = connection, predicate
        self.fired = False

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def execute(self, sql, args=()):
        if not self.fired and self.predicate(sql, args):
            self.fired = True
            raise sqlite3.OperationalError("Injected second-item persistence failure")
        return self.connection.execute(sql, args)


def test_committed_job_replay_is_noop_but_new_brief_requires_new_decision(runtime, plan):
    result = brief(plan)
    assert apply(runtime, result)["state"] == "done"
    assert len(runtime.engine.plans()) == 1
    identity = runtime.engine.plans()[0]["id"]
    approval = {"at": datetime.now(timezone.utc).isoformat(), "decision": {"action": "approve"}}
    runtime.store.set("approval:" + identity, approval)
    runtime.store.db.execute("UPDATE plans SET state='approved' WHERE id=?", (identity,))
    saved = runtime.store.get("brief")
    events = runtime.store.rows("SELECT * FROM events")
    runtime.task = ("batch-research", "research", {}, "2026-11-07")
    runtime.future = Future()
    runtime.future.set_result({**result, "summary": "A stale replay must not replace the accepted brief"})
    runtime.finish_task()
    assert runtime.store.get("brief") == saved
    assert runtime.store.rows("SELECT * FROM events") == events
    assert runtime.store.rows("SELECT state FROM plans")[0]["state"] == "approved"
    assert runtime.qualities == ["applied"] and len(runtime.notifications) == 1
    refreshed = {**result, "regime": "risk_off", "summary": "Changed current context requires a new decision"}
    assert apply(runtime, refreshed, key="batch-fresh-open")["state"] == "done"
    assert [p["id"] for p in runtime.engine.plans()] == [identity]
    assert runtime.store.rows("SELECT state FROM plans")[0]["state"] == "planned"
    assert runtime.store.get("approval:" + identity) == approval
    assert runtime.store.get("brief")["regime"] == "risk_off"
    assert runtime.qualities == ["applied", "applied"]
    assert runtime.store.rows("SELECT * FROM orders") == []


def test_second_plan_failure_rolls_back_entire_batch_then_retry_keeps_both(runtime, plan):
    result = brief(plan)
    result["plans"].append({**result["plans"][0], "id": "second-plan", "symbol": "MSFT"})
    result = Brief.model_validate(result).model_dump(mode="json")
    store = runtime.store
    previous = {"id": "prior-plan", **{k: v for k, v in plan.items() if k != "id"}}
    runtime.engine.add_plans([previous], "2026-11-07")
    store.set("brief", {"summary": "Previously accepted brief"})
    old_plans = store.rows("SELECT * FROM plans")
    queue(runtime, result)
    connection = store.db
    store.db = FailExecute(connection, lambda sql, args: "INSERT OR IGNORE INTO plans" in sql and json.loads(args[-1])["symbol"] == "MSFT")
    try:
        runtime.finish_task()
    finally:
        store.db = connection
    assert store.rows("SELECT state FROM jobs")[0]["state"] == "failed"
    assert store.rows("SELECT * FROM plans") == old_plans
    assert json.loads(store.rows("SELECT payload FROM usage")[0]["payload"])["application_outcome"] == "rejected"
    assert store.get("brief") == {"summary": "Previously accepted brief"}
    assert not runtime.notifications
    assert apply(runtime, result)["state"] == "done"
    assert sorted(p["symbol"] for p in runtime.engine.plans()) == ["AAPL", "MSFT"]
    assert store.rows("SELECT state FROM plans WHERE id='prior-plan'")[0]["state"] == "superseded"
    assert runtime.qualities == ["rejected", "applied"]


def test_second_experiment_failure_rolls_back_validation_and_retry_does_not_duplicate_reviews(runtime):
    now = datetime.now(timezone.utc)
    source = draft(now)
    source["experiments"].append(contract("higher_confidence_075"))
    source["hypotheses"].append({**source["hypotheses"][0], "id": "hypothesis-two", "experiment_ids": [source["experiments"][1]["id"]]})
    source = ExplorationReport.model_validate(source).model_dump(mode="json")
    result = validation()
    result["hypotheses"].append({**result["hypotheses"][0], "id": "hypothesis-two"})
    result = ResearchValidation.model_validate(result).model_dump(mode="json")
    store = runtime.store
    record_report(store, source, "2026-11-07")
    context = {"revision": store.get("exploration_draft")["revision"]}
    queue(runtime, result, role="research_validation", context=context)
    connection = store.db
    store.db = FailExecute(connection, lambda sql, args: "INSERT INTO experiments" in sql and args[0] == "trial-higher_confidence_075")
    try:
        runtime.finish_task()
    finally:
        store.db = connection
    assert store.rows("SELECT state FROM jobs")[0]["state"] == "failed"
    assert store.rows("SELECT id FROM experiments") == []
    assert store.rows("SELECT id FROM memory WHERE layer='research_review'") == []
    assert store.get("research_catalogue") is None
    assert store.get("exploration_validated_draft") is None
    assert json.loads(store.rows("SELECT payload FROM usage")[0]["payload"])["application_outcome"] == "rejected"
    assert apply(runtime, result, role="research_validation", context=context)["state"] == "done"
    assert len(store.rows("SELECT id FROM experiments")) == 2
    assert len(store.rows("SELECT id FROM memory WHERE layer='research_review'")) == 2


def test_retrospective_failure_rolls_back_proposals_and_retry_registers_once(runtime):
    result = Review.model_validate({
        "summary": "Two separate forward contracts.", "observations": [], "proposed_lessons": ["Proposed only"],
        "experiments": [contract("require_risk_on"), contract("higher_confidence_075")],
        "code_changes": [], "no_change_reason": None,
    }).model_dump(mode="json")
    store, connection = runtime.store, runtime.store.db
    queue(runtime, result, role="retrospective")
    store.db = FailExecute(connection, lambda sql, args: "INSERT INTO experiments" in sql and args[0] == "trial-higher_confidence_075")
    try:
        runtime.finish_task()
    finally:
        store.db = connection
    assert store.rows("SELECT state FROM jobs")[0]["state"] == "failed"
    assert store.rows("SELECT id FROM experiments") == []
    assert store.get("review_day") is None
    assert store.rows("SELECT id FROM memory WHERE layer='lesson'") == []
    assert runtime.qualities == ["rejected"]
    assert apply(runtime, result, role="retrospective")["state"] == "done"
    assert len(store.rows("SELECT id FROM experiments")) == 2
    assert len(store.rows("SELECT id FROM memory WHERE layer='lesson'")) == 1


@pytest.mark.parametrize("failure", ["brief_memory", "completion_event", "job_done", "usage_acceptance", "commit"])
def test_late_persistence_failure_cannot_commit_any_batch_effect(runtime, plan, failure):
    result = brief(plan)
    store = runtime.store
    queue(runtime, result)
    checks = {
        "brief_memory": lambda sql, args: "INTO memory" in sql and args[0].startswith("brief:"),
        "completion_event": lambda sql, args: "INTO events" in sql and args[1] == "research_completed",
        "job_done": lambda sql, args: "UPDATE jobs SET state=" in sql and args[0] == "done",
        "usage_acceptance": lambda sql, args: "UPDATE usage SET payload=" in sql and json.loads(args[0]).get("application_outcome") == "accepted",
        "commit": lambda sql, args: sql == "COMMIT",
    }
    connection = store.db
    fault = FailExecute(connection, checks[failure])
    store.db = fault
    try:
        runtime.finish_task()
    finally:
        store.db = connection
    assert fault.fired
    assert store.rows("SELECT * FROM plans") == []
    assert store.get("brief") is None
    assert store.rows("SELECT id FROM memory WHERE layer='observation'") == []
    assert store.rows("SELECT id FROM events WHERE kind='research_completed'") == []
    assert store.rows("SELECT state FROM jobs")[0]["state"] == "failed"
    assert json.loads(store.rows("SELECT payload FROM usage")[0]["payload"])["application_outcome"] == "rejected"
    assert not runtime.notifications
    assert apply(runtime, result)["state"] == "done"
    assert len(runtime.engine.plans()) == 1


def test_conditional_job_completion_failure_rolls_back_local_changes(runtime, plan, monkeypatch):
    original = runtime.store.job_end
    monkeypatch.setattr(runtime.store, "job_end", lambda key, success, result: False if success else original(key, success, result))
    assert apply(runtime, brief(plan))["state"] == "failed"
    assert runtime.store.rows("SELECT * FROM plans") == []
    assert runtime.store.get("brief") is None
    assert runtime.notifications == []


def test_same_future_result_object_remains_unchanged_across_failure_and_retry(runtime, plan):
    result = brief(plan)
    original = copy.deepcopy(result)
    queue(runtime, result, copy_result=False)
    connection = runtime.store.db
    runtime.store.db = FailExecute(connection, lambda sql, args: "INTO events" in sql and args[1] == "research_completed")
    try:
        runtime.finish_task()
    finally:
        runtime.store.db = connection
    assert result == original
    queue(runtime, result, copy_result=False)
    runtime.finish_task()
    assert result == original
    identity = runtime.engine.plans()[0]["id"]
    assert identity.startswith(original["plans"][0]["id"] + "-")
    assert len(identity) == len(original["plans"][0]["id"]) + 9
    assert runtime.store.get("brief")["plans"][0]["id"] == identity


@pytest.mark.parametrize("state", ["submitted", "invalidated", "superseded", "expired"])
def test_new_brief_does_not_revive_terminal_plan_identity(runtime, plan, state):
    result = brief(plan)
    apply(runtime, result)
    identity = runtime.engine.plans()[0]["id"]
    runtime.store.db.execute("UPDATE plans SET state=? WHERE id=?", (state, identity))
    assert apply(runtime, result, key="later-brief")["state"] == "done"
    assert runtime.store.rows("SELECT state FROM plans")[0]["state"] == state
    assert runtime.engine.plans() == []


@pytest.mark.parametrize("refresh_required", [False, True])
def test_suspended_plan_requires_explicit_research_refresh_context(runtime, plan, refresh_required):
    result = brief(plan)
    apply(runtime, result)
    identity = runtime.engine.plans()[0]["id"]
    runtime.store.db.execute("UPDATE plans SET state='suspended' WHERE id=?", (identity,))
    runtime.store.set("research_refresh_required", refresh_required)
    assert apply(runtime, result, key="later-brief")["state"] == "done"
    assert runtime.store.rows("SELECT state FROM plans")[0]["state"] == ("planned" if refresh_required else "suspended")


def test_postcommit_notification_failure_does_not_reject_the_application(runtime, plan, monkeypatch):
    def fail(*args):
        assert not runtime.store.db.in_transaction
        assert runtime.store.rows("SELECT state FROM jobs")[0]["state"] == "done"
        raise OSError("Injected delivery failure after commit")

    monkeypatch.setattr(supervisor, "notify", fail)
    assert apply(runtime, brief(plan))["state"] == "done"
    assert len(runtime.engine.plans()) == 1
    assert runtime.qualities == ["applied"]
    assert not runtime.incidents
    assert json.loads(runtime.store.rows("SELECT payload FROM usage")[0]["payload"])["application_outcome"] == "accepted"


def test_postcommit_quality_failure_does_not_reject_result_or_prevent_notification(runtime, plan, monkeypatch):
    def fail(*args):
        assert not runtime.store.db.in_transaction
        assert runtime.store.rows("SELECT state FROM jobs")[0]["state"] == "done"
        raise ImportError("Injected quality capture import failure")

    monkeypatch.setattr(runtime, "record_quality", fail)
    assert apply(runtime, brief(plan))["state"] == "done"
    assert len(runtime.engine.plans()) == 1
    assert len(runtime.notifications) == 1
    assert not runtime.incidents
    assert json.loads(runtime.store.rows("SELECT payload FROM usage")[0]["payload"])["application_outcome"] == "accepted"


@pytest.mark.parametrize("approval_age,permitted", [(180, True), (181, False)])
def test_replayed_plan_approval_still_expires_after_180_seconds(runtime, plan, monkeypatch, approval_age, permitted, now):
    result = brief(plan)
    apply(runtime, result)
    identity = runtime.engine.plans()[0]["id"]
    from tests.runtime.session_fixtures import install

    proof = install(runtime.store, now)
    runtime.store.set("calendar:" + proof["day"], proof["calendar_raw"])
    close = now.astimezone(supervisor.ET).replace(hour=16, minute=0)
    runtime.store.db.execute("UPDATE plans SET state='approved' WHERE id=?", (identity,))
    runtime.store.set("approval:" + identity, {"at": (now - timedelta(seconds=approval_age)).isoformat()})
    runtime.task = ("batch-research", "research", {}, "2026-11-07")
    runtime.future = Future()
    runtime.future.set_result(result)
    runtime.finish_task()
    entered = []
    monkeypatch.setattr(runtime.engine, "enter", lambda *args: entered.append(args[0]["id"]))
    monkeypatch.setattr(runtime.experiments, "consider", lambda *args: None)
    monkeypatch.setattr(runtime.experiments, "mark", lambda *args: None)
    monkeypatch.setattr(runtime.experiments, "permits", lambda *args: True)
    monkeypatch.setattr(runtime, "benchmarks", lambda *args: None)
    monkeypatch.setattr(runtime, "cohort_check", lambda label, action, default=None: default)
    runtime.adaptive = SimpleNamespace(symbols=lambda: set())
    monkeypatch.setattr(supervisor.time, "monotonic", lambda: 1)
    runtime.market_tick(now, close)
    assert entered == ([identity] if permitted else [])
    assert runtime.store.rows("SELECT state FROM plans")[0]["state"] == ("approved" if permitted else "planned")
    assert runtime.broker.submissions == 0


def test_domain_rejection_remains_per_proposal_and_names_rejected_item(runtime):
    good = contract("require_risk_on")
    bad = {**contract("higher_confidence_075"), "parent_version": "obsolete-parent"}
    result = Review.model_validate({
        "summary": "Independent prospective proposals", "observations": [], "proposed_lessons": [],
        "experiments": [good, bad], "code_changes": [], "no_change_reason": None,
    }).model_dump(mode="json")
    assert apply(runtime, result, role="retrospective")["state"] == "done"
    assert [r["id"] for r in runtime.store.rows("SELECT id FROM experiments")] == [good["id"]]
    rejected = runtime.store.rows("SELECT payload FROM events WHERE kind='experiment_rejected'")
    assert len(rejected) == 1 and json.loads(rejected[0]["payload"])["id"] == bad["id"]


def test_duplicate_plan_ids_reject_batch_without_superseding_prior_plan(runtime, plan):
    result = brief(plan)
    apply(runtime, result)
    saved = runtime.store.rows("SELECT * FROM plans")
    result["plans"] *= 2
    assert apply(runtime, result, key="duplicate-plan-batch")["state"] == "failed"
    assert runtime.store.rows("SELECT * FROM plans") == saved

