"""Tests for ResearchAgent configuration behavior."""

import pytest

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


def test_research_agent_honors_provider_preference_when_both_keys_present(
    message_bus, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setattr(research_module, "PerformanceTracker", DummyTracker)
    reset_settings()

    agent = ResearchAgent(message_bus)

    assert agent._get_provider_name() == "openai"
    assert agent._get_provider_sequence() == ["openai", "anthropic"]
    assert agent._get_research_model() == "gpt-4o-mini"


class AnthropicErroringClient:
    class Messages:
        @staticmethod
        def create(**kwargs):
            raise RuntimeError("Your credit balance is too low to access the Anthropic API")

    messages = Messages()


class OpenAIJsonClient:
    class Chat:
        class Completions:
            @staticmethod
            def create(**kwargs):
                class Message:
                    content = (
                        '{"overall_sentiment":"bullish","market_summary":"fallback ok",'
                        '"stocks":{}}'
                    )

                class Choice:
                    message = Message()

                class Response:
                    choices = [Choice()]

                return Response()

        completions = Completions()

    chat = Chat()


@pytest.mark.asyncio
async def test_research_agent_retries_with_openai_when_primary_provider_fails(
    message_bus, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setattr(research_module, "PerformanceTracker", DummyTracker)
    reset_settings()

    agent = ResearchAgent(message_bus)
    agent._llm_clients["anthropic"] = AnthropicErroringClient()
    agent._llm_clients["openai"] = OpenAIJsonClient()

    response = await agent._call_llm("{}", phase="research")

    assert response["overall_sentiment"] == "bullish"
    assert response["market_summary"] == "fallback ok"
    assert response["_meta"]["provider"] == "openai"
    assert response["_meta"]["model"] == "gpt-4o-mini"
