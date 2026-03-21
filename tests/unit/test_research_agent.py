"""Tests for ResearchAgent configuration behavior."""

import agent_trader.agents.research_agent as research_module
from agent_trader.agents.research_agent import ResearchAgent
from agent_trader.config.settings import reset_settings


class DummyTracker:
    def get_recent_trades_for_prompt(self, last_n: int = 10) -> str:
        return ""

    def get_performance_summary(self) -> dict:
        return {}

    def get_learned_rules(self) -> str:
        return ""

    def save_learned_rules(self, rules: list[str]) -> None:
        return None


def test_research_agent_prefers_anthropic_models_when_key_present(message_bus, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(research_module, "PerformanceTracker", DummyTracker)
    reset_settings()

    agent = ResearchAgent(message_bus)

    assert agent._get_provider_name() == "anthropic"
    assert agent._get_research_model() == "claude-sonnet-4-6"
    assert agent._get_monitor_model() == "claude-haiku-4-5-20251001"


def test_research_agent_falls_back_to_openai_when_only_openai_key_present(
    message_bus, monkeypatch
):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setattr(research_module, "PerformanceTracker", DummyTracker)
    reset_settings()

    agent = ResearchAgent(message_bus)

    assert agent._get_provider_name() == "openai"
    assert agent._get_research_model() == "gpt-4o-mini"
    assert agent._get_monitor_model() == "gpt-4o-mini"
