from datetime import datetime

import pytest

from agent_trader.runtime import probe
from agent_trader.runtime.store import Store


def test_probe_cannot_create_execution_plans_or_overwrite_production_knowledge(config, monkeypatch):
    live = Store(config.state_dir / "trader.sqlite3")
    live.set("research_catalogue", [{"id": "original"}])
    live.set("brief", {"summary": "production brief"})
    monkeypatch.setattr(probe, "market_packet", lambda *args: {"market": {}})
    monkeypatch.setattr(probe, "research_prompt", lambda *args: "Research evidence")
    monkeypatch.setattr(probe, "ResearchData", lambda config: object())
    monkeypatch.setattr(probe, "notify", lambda *args, **kwargs: True)
    calls = []

    def inference(config, role, prompt, schema, model, effort, day, **kwargs):
        calls.append((role, kwargs["scope"]))
        return {
            "summary": "isolated research",
            "plans": [],
            "sources": [{"url": "https://example.com"}],
        }

    monkeypatch.setattr(probe, "run_task", inference)
    result = probe.run_probe(config, "dummy-safe", "research", True)
    assert result["state"] == "passed" and result["orders_authorized"] is False
    assert live.get("brief") == {"summary": "production brief"}
    assert live.get("research_catalogue") == [{"id": "original"}]
    assert not live.rows("SELECT * FROM plans") and not live.rows("SELECT * FROM orders")
    assert calls == [("probe_research", "dummy-safe")]
    # A completed check is idempotent rather than silently consuming another call.
    assert probe.run_probe(config, "dummy-safe", "research", True) == result
    assert len(calls) == 1
    live.close()


def test_probe_rejects_actionable_output_and_records_failure(config, monkeypatch):
    monkeypatch.setattr(probe, "market_packet", lambda *args: {"market": {}})
    monkeypatch.setattr(probe, "research_prompt", lambda *args: "Research evidence")
    monkeypatch.setattr(probe, "ResearchData", lambda config: object())
    monkeypatch.setattr(probe, "notify", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        probe, "run_task", lambda *args, **kwargs: {"plans": [{"id": "must-not-execute"}]}
    )
    with pytest.raises(ValueError, match="execution plans"):
        probe.run_probe(config, "dummy-reject", "research", True)
    live = Store(config.state_dir / "trader.sqlite3")
    assert live.get("research_probes")[0]["state"] == "failed"
    assert not live.rows("SELECT * FROM orders")
    live.close()


def test_probe_ids_cannot_escape_private_artifact_directory(config):
    with pytest.raises(ValueError, match="probe ID"):
        probe.run_probe(config, "../../private")


def test_adhoc_timer_is_timezone_explicit_persistent_and_once(config, monkeypatch):
    monkeypatch.setattr(probe.Path, "home", lambda: config.root)
    calls = []
    monkeypatch.setattr(probe.subprocess, "run", lambda args, **kwargs: calls.append(args))
    when = datetime.fromisoformat("2026-10-29T19:00:00-04:00")
    entry = probe.schedule(config, "test-1900", when)
    timer = (config.root / ".config/systemd/user/agent-trader-probe-test-1900.timer").read_text()
    assert "OnCalendar=2026-10-29 19:00:00 America/New_York" in timer
    assert "Persistent=true" in timer and "AccuracySec=1s" in timer
    assert entry["orders_authorized"] is False
    assert calls[-1][-1] == "agent-trader-probe-test-1900.timer"
    with pytest.raises(ValueError):
        probe.schedule(config, "bad-time", datetime.now())


def test_rejected_hypotheses_do_not_claim_a_positive_morning_handoff(config, monkeypatch):
    from datetime import datetime, timezone

    live = Store(config.state_dir / "trader.sqlite3")
    live.set("historical_screen", {"trials": []})
    live.close()
    now = datetime.now(timezone.utc).isoformat()
    source = {"url": "https://example.com/paper", "title": "Primary source", "observed_at": now}
    hypothesis = {
        "id": "hypothesis-test",
        "branch": "intraday",
        "family": "catalyst",
        "claim": "A hypothesis needing a concrete test.",
        "mechanism": "Information diffusion",
        "falsification": "Need a predeclared test",
        "free_data_feasibility": "limited",
        "source_urls": [source["url"]],
        "screen_trial_ids": [],
        "experiment_ids": [],
    }
    report = {
        "summary": "Test",
        "hypotheses": [hypothesis],
        "sources": [source],
        "experiments": [],
        "shadow_plans": [],
    }
    review = {
        "summary": "Not ready",
        "hypotheses": [
            {
                "id": hypothesis["id"],
                "verdict": "needs_work",
                "reason": "Execution and data rules are incomplete.",
            }
        ],
    }
    monkeypatch.setattr(probe, "notify", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        probe,
        "run_task",
        lambda config, role, *args, **kwargs: report if role == "probe_hypotheses" else review,
    )
    result = probe.run_probe(config, "dummy-unapproved", "hypotheses", True)
    assert result["state"] == "passed"  # the workflow ran, and rejection is a valid result
    assert result["reviewed_for_testing"] == 0
    assert result["morning_handoff_verified"] is False
    assert result["handoff_result"] == "no_cards_approved"
