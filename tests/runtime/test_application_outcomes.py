import json
from concurrent.futures import Future
from datetime import datetime, timezone

import pytest

from agent_trader.runtime import agent, research_work, supervisor
from agent_trader.runtime.publish import snapshot
from agent_trader.runtime.store import dumps
from tests.runtime.test_agent_diagnostics import FakeRPC


@pytest.mark.parametrize("valid_reference", [True, False])
def test_validated_inference_keeps_tokens_when_application_accepts_or_rejects(
    config, broker, monkeypatch, valid_reference
):
    evidence = {
        "records": [{"id": "ev:supplied", "kind": "research", "value": {"gap": "unknown"}}],
        "omitted_records": 0,
    }
    context = research_work._context("event_coverage", evidence)
    report = {
        "work_id": context["work_id"], "topic": context["topic"],
        "summary": "The evidence does not resolve the named event coverage gap.",
        "findings": [{
            "claim": "Coverage remains unknown.", "kind": "unknown",
            "evidence_refs": ["ev:supplied" if valid_reference else "PRIVATE-RAW-REFERENCE"],
            "qualification": "No comprehensive event clearance is established.",
        }],
        "sources": [], "proposals": [], "unresolved": ["Need authoritative receipt"],
    }

    class ReportRPC(FakeRPC):
        payload = report

    monkeypatch.setattr(agent, "CodexRPC", ReportRPC)
    monkeypatch.setattr(supervisor, "Broker", lambda _: broker)
    monkeypatch.setattr(supervisor, "notify", lambda *a, **k: False)
    s = supervisor.Supervisor(config)
    day = datetime.now(timezone.utc).date().isoformat()
    key = "internal-task-key-DO-NOT-PUBLISH"
    try:
        assert s.store.job_start(key)
        parsed = agent.run_task(
            config, "deep_research", "Review supplied evidence", research_work.ResearchWorkReport,
            config.research_model, "high", day, task_key=key,
        )
        before = s.store.rows("SELECT * FROM usage")[0]
        assert json.loads(before["payload"])["application_outcome"] == "pending"
        s.task = (key, "deep_research", context, day)
        s.future = Future()
        s.future.set_result(parsed)
        s.finish_task()
        after = s.store.rows("SELECT * FROM usage")[0]
        receipt = json.loads(after["payload"])
        assert receipt["state"] == "completed"
        assert receipt["terminal_outcome"] == "validated"
        assert receipt["application_outcome"] == ("accepted" if valid_reference else "rejected")
        assert receipt["application_validation_code"] == (
            None if valid_reference else "unknown_evidence_reference"
        )
        assert receipt["application_at"]
        for column in ("input_tokens", "cached_tokens", "output_tokens", "quota_delta", "at"):
            assert after[column] == before[column]
        assert after["input_tokens"] == 120 and after["output_tokens"] == 40
        private = s.store.rows("SELECT payload FROM memory WHERE layer='research_artifact'")
        assert len(private) == 1
        assert json.loads(private[0]["payload"])["outcome"] == (
            "applied" if valid_reference else "rejected"
        )
        public = snapshot(config, s.store)
        assert public["usage"][0]["application_outcome"] == receipt["application_outcome"]
        assert key not in json.dumps(public)
        assert "PRIVATE-RAW-REFERENCE" not in json.dumps(public)
        assert broker.submissions == 0
    finally:
        s.pool.shutdown(wait=False)
        s.publisher_pool.shutdown(wait=False)
        s.store.close()


def test_application_link_is_idempotent_sanitized_and_does_not_relabel_inference_failures(store):
    store.db.execute(
        "INSERT INTO usage(at,day,role,model,input_tokens,output_tokens,payload) VALUES(?,?,?,?,?,?,?)",
        ("original-at", "2026-11-07", "deep_research", "test", 123, 45, dumps({
            "task_key": "job-one", "state": "completed", "terminal_outcome": "validated",
            "application_outcome": "pending",
        })),
    )
    identity = agent.record_application_outcome(
        store, "job-one", "rejected", "PRIVATE arbitrary exception message"
    )
    original = store.rows("SELECT * FROM usage")[0]
    payload = json.loads(original["payload"])
    assert payload["application_validation_code"] == "application_error"
    assert agent.record_application_outcome(store, "job-one", "rejected") == identity
    assert agent.record_application_outcome(store, "job-one", "accepted") is None
    assert store.rows("SELECT * FROM usage")[0] == original
    assert agent.record_application_outcome(store, "quota-refresh:no-inference", "accepted") is None
    store.db.execute(
        "INSERT INTO usage(at,day,role,model,payload) VALUES(?,?,?,?,?)",
        ("later-at", "2026-11-07", "deep_research", "test", dumps({
            "task_key": "job-one", "state": "failed", "terminal_outcome": "inference_failed",
        })),
    )
    assert agent.record_application_outcome(store, "job-one", "accepted") is None
    assert store.rows("SELECT * FROM usage ORDER BY id")[0] == original
    assert "application_outcome" not in json.loads(store.rows("SELECT payload FROM usage ORDER BY id DESC")[0]["payload"])
