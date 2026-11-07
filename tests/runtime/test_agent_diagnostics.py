import json
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from agent_trader.runtime import agent
from agent_trader.runtime.models import Decision
from agent_trader.runtime.store import Store


def quota(used=10):
    return {
        "ordinary_usage_allowed": True,
        "windows": [{
            "bucket": "codex", "kind": "primary", "usedPercent": used,
            "windowDurationMins": 10080,
            "resetsAt": int((datetime.now(timezone.utc) + timedelta(days=3)).timestamp()),
        }],
    }


class FakeRPC:
    payload = {
        "plan_id": "plan-1", "action": "wait", "reason": "Insufficient current evidence",
        "contradictions": [], "evidence_fresh": False,
    }
    calls = 0

    def __init__(self, config):
        self.config = config
        self.quota_reads = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def rate_limits(self):
        self.quota_reads += 1
        return quota()

    def models(self):
        return [{"id": name} for name in (self.config.research_model, self.config.light_model)]

    def run(self, *args, **kwargs):
        type(self).calls += 1
        return (
            "private-thread", self.payload,
            {"last": {"inputTokens": 120, "cachedInputTokens": 30, "outputTokens": 40}},
            {"searches": 1, "cycles": 3},
        )


def run(config, **kwargs):
    return agent.run_task(
        config, "research", "Use supplied evidence only", Decision,
        config.research_model, "low", datetime.now(timezone.utc).date().isoformat(),
        task_key="research:same-job", **kwargs,
    )


def test_rejected_attempts_link_fields_without_echoing_inputs(config, monkeypatch):
    class InvalidRPC(FakeRPC):
        payload = {
            "action": "PRIVATE-BAD-VALUE",
            "reason": "Missing required fields",
            "PRIVATE-UNRECOGNIZED-KEY": "PRIVATE-VALUE",
        }

    monkeypatch.setattr(agent, "CodexRPC", InvalidRPC)
    for _ in range(2):
        with pytest.raises(ValidationError):
            run(config)
    store = Store(config.state_dir / "trader.sqlite3")
    try:
        attempts = [json.loads(r["payload"]) for r in store.rows("SELECT payload FROM usage")]
        assert attempts[1]["previous_attempt_id"] == attempts[0]["attempt_id"]
        assert attempts[1]["request_id"] == attempts[0]["request_id"]
        assert attempts[0]["phase"] == "schema_validation"
        assert attempts[0]["terminal_outcome"] == "schema_rejected"
        paths = [x["path"] for x in attempts[0]["validation_errors"]]
        assert ["action"] in paths and ["<unrecognized-field>"] in paths
        public = json.dumps(store.rows("SELECT payload FROM events"))
        assert "PRIVATE" not in public
        assert "private-thread" not in public
        artifacts = store.rows("SELECT payload FROM memory WHERE layer='agent_attempt_artifact'")
        assert len(artifacts) == 2 and "PRIVATE-BAD-VALUE" in artifacts[0]["payload"]
        assert store.rows("SELECT input_tokens FROM usage")[0]["input_tokens"] == 120
    finally:
        store.close()


@pytest.mark.parametrize("failed_metadata", ["models", "quota"])
def test_valid_reply_survives_metadata_failure_without_second_inference(
    config, monkeypatch, failed_metadata
):
    class MetadataFailureRPC(FakeRPC):
        calls = 0

        def models(self):
            if failed_metadata == "models":
                raise TimeoutError("PRIVATE-CALLER-DATA")
            return super().models()

        def rate_limits(self):
            result = super().rate_limits()
            if failed_metadata == "quota" and self.quota_reads > 1:
                raise TimeoutError("PRIVATE-CALLER-DATA")
            return result

    monkeypatch.setattr(agent, "CodexRPC", MetadataFailureRPC)
    result = run(config)
    assert result == FakeRPC.payload
    assert MetadataFailureRPC.calls == 1
    store = Store(config.state_dir / "trader.sqlite3")
    try:
        attempt = json.loads(store.rows("SELECT payload FROM usage")[0]["payload"])
        assert attempt["terminal_outcome"] == "validated"
        assert attempt["state"] == "completed"
        assert attempt["metadata_errors"][0]["error_type"] == "TimeoutError"
        assert store.get("entry_budget_blocked") is True
        assert "PRIVATE" not in json.dumps(store.rows("SELECT payload FROM events"))
    finally:
        store.close()


def test_failed_inference_retains_reported_partial_tokens(config, monkeypatch):
    class InterruptedRPC(FakeRPC):
        def run(self, *args, **kwargs):
            self.last_attempt = {
                "phase": "turn_stream", "thread_id": "private-thread", "turn_id": "private-turn",
                "usage": {"last": {"inputTokens": 85, "outputTokens": 7}},
                "counters": {"searches": 2, "cycles": 4},
            }
            raise agent.AgentUnavailable("private stream detail")

    monkeypatch.setattr(agent, "CodexRPC", InterruptedRPC)
    with pytest.raises(agent.AgentUnavailable):
        run(config)
    store = Store(config.state_dir / "trader.sqlite3")
    try:
        row = store.rows("SELECT * FROM usage")[0]
        attempt = json.loads(row["payload"])
        assert row["input_tokens"] == 85 and row["output_tokens"] == 7
        assert attempt["terminal_outcome"] == "inference_failed"
        assert attempt["reply_usage_reported"] is True
        assert attempt["searches"] == 2
        assert "private" not in json.dumps(store.rows("SELECT payload FROM events"))
    finally:
        store.close()


def test_missing_configured_model_preserves_reply_but_blocks_entries(config, monkeypatch):
    class MissingModelRPC(FakeRPC):
        def models(self):
            return [{"id": self.config.research_model}]

    monkeypatch.setattr(agent, "CodexRPC", MissingModelRPC)
    assert run(config) == FakeRPC.payload
    store = Store(config.state_dir / "trader.sqlite3")
    try:
        assert store.get("readiness")["models_available"] is False
        assert store.get("entry_budget_blocked") is True
        assert agent.account_limit_reason(store.get("quota")) is None
        assert json.loads(store.rows("SELECT payload FROM usage")[0]["payload"])["state"] == "completed"
    finally:
        store.close()


def rpc_stream(config, messages):
    rpc = agent.CodexRPC.__new__(agent.CodexRPC)
    rpc.config, rpc.workspace, rpc.backlog = config, config.state_dir, []
    sent = []
    rpc.send = sent.append
    rpc.rpc = lambda method, params: (
        {"thread": {"id": "thread-current"}} if method == "thread/start"
        else {"turn": {"id": "turn-current"}}
    )
    iterator = iter(messages)
    rpc.receive = lambda deadline: next(iterator)
    return rpc, sent


def test_stream_ceiling_interrupts_and_retains_usage(config):
    window = quota(80)["windows"][0]
    rpc, sent = rpc_stream(config, [
        {"method": "thread/tokenUsage/updated", "params": {
            "tokenUsage": {"last": {"inputTokens": 50, "outputTokens": 5}},
        }},
        {"method": "account/rateLimits/updated", "params": {
            "rateLimits": {"primary": window},
        }},
    ])
    with pytest.raises(agent.AgentUnavailable, match="20% account reserve"):
        rpc.run(None, "Evidence", config.research_model, "low", {})
    assert sent[-1]["method"] == "turn/interrupt"
    assert rpc.last_attempt["phase"] == "quota_interrupt"
    assert rpc.last_attempt["usage"]["last"]["outputTokens"] == 5


def test_late_other_turn_completion_cannot_supply_current_result(config):
    rpc, _ = rpc_stream(config, [
        {"method": "item/agentMessage/delta", "params": {
            "turnId": "turn-old", "delta": "BAD-OLD-OUTPUT",
        }},
        {"method": "turn/completed", "params": {
            "turn": {"id": "turn-old", "status": "failed"},
        }},
        {"method": "item/completed", "params": {
            "item": {"type": "agentMessage", "text": '{"ok": true}'},
        }},
        {"method": "turn/completed", "params": {
            "turn": {"id": "turn-current", "status": "completed"},
        }},
    ])
    _, payload, _, _ = rpc.run(None, "Evidence", config.research_model, "low", {})
    assert payload == {"ok": True}


def test_invalid_reply_excerpt_is_bounded_and_retains_hash():
    raw = "x" * 100001
    result = agent.bounded_failure_reply(None, raw)
    assert result["truncated"] and len(result["text_excerpt"]) == 100000
    assert result["characters"] == 100001 and len(result["sha256"]) == 64
