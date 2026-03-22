"""Tests for ResearchAgent configuration behavior."""

import tempfile

import pytest

import agent_trader.agents.research_agent as research_module
from agent_trader.core.message_bus import Message, MessageType
from agent_trader.agents.research_agent import ResearchAgent
from agent_trader.config.settings import reset_settings


class DummyTracker:
    def __init__(self, *args, **kwargs):
        return None

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
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setattr(research_module, "PerformanceTracker", DummyTracker)
    reset_settings()

    agent = ResearchAgent(message_bus)

    assert agent._get_provider_name() == "anthropic"
    assert agent._get_research_model() == "claude-sonnet-4-6"
    assert agent._get_monitor_model() == "claude-haiku-4-5-20251001"


def test_research_agent_falls_back_to_openai_when_only_openai_key_present(
    message_bus, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("MONITOR_MODEL_OPENAI", "gpt-4.1-mini")
    monkeypatch.setattr(research_module, "PerformanceTracker", DummyTracker)
    reset_settings()

    agent = ResearchAgent(message_bus)

    assert agent._get_provider_name() == "openai"
    assert agent._get_research_model() == "gpt-4o-mini"
    assert agent._get_monitor_model() == "gpt-4.1-mini"
    assert agent._get_model_for_phase("openai", "evening_reflection") == "gpt-4.1-mini"
    assert agent._get_model_for_phase("openai", "weekly_consolidation") == "gpt-4.1-mini"
    assert agent._get_model_for_phase("openai", "monthly_retrospective") == "gpt-4.1-mini"


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


def test_research_agent_claude_cli_limits_api_fallback_to_anthropic(
    message_bus, monkeypatch
):
    monkeypatch.setenv("USE_CLI_AGENT", "true")
    monkeypatch.setenv("CLI_AGENT_PROVIDER", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setattr(research_module, "PerformanceTracker", DummyTracker)
    reset_settings()

    agent = ResearchAgent(message_bus)

    assert agent._get_api_provider_sequence() == ["anthropic"]
    assert agent._get_provider_name() == "anthropic"


def test_research_agent_codex_cli_limits_api_fallback_to_openai(
    message_bus, monkeypatch
):
    monkeypatch.setenv("USE_CLI_AGENT", "true")
    monkeypatch.setenv("CLI_AGENT_PROVIDER", "codex")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setattr(research_module, "PerformanceTracker", DummyTracker)
    reset_settings()

    agent = ResearchAgent(message_bus)

    assert agent._get_api_provider_sequence() == ["openai"]
    assert agent._get_provider_name() == "openai"


def test_research_agent_monitor_can_force_api_even_when_cli_enabled(
    message_bus, monkeypatch
):
    monkeypatch.setenv("USE_CLI_AGENT", "true")
    monkeypatch.setenv("USE_CLI_AGENT_FOR_MONITOR", "false")
    monkeypatch.setenv("CLI_AGENT_PROVIDER", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setattr(research_module, "PerformanceTracker", DummyTracker)
    reset_settings()

    agent = ResearchAgent(message_bus)

    assert agent._should_use_cli_for_phase("research") is True
    assert agent._should_use_cli_for_phase("monitor") is False


def test_select_monitor_candidates_prefers_active_and_near_entry_symbols(
    message_bus, monkeypatch
):
    with tempfile.TemporaryDirectory(dir=".") as temp_dir:
        monkeypatch.setenv("DATA_DIR", temp_dir)
        monkeypatch.setenv("MONITOR_CANDIDATE_LIMIT", "2")
        monkeypatch.setenv("MONITOR_ENTRY_PROXIMITY_PCT", "2")
        monkeypatch.setattr(research_module, "PerformanceTracker", DummyTracker)
        reset_settings()

        portfolio_path = research_module.Path(temp_dir) / "portfolio_state.json"
        portfolio_path.write_text(
            '{"LMT":{"shares":10,"avg_cost":600,"last_price":625},"KO":{"shares":0}}',
            encoding="utf-8",
        )

        agent = ResearchAgent(message_bus)
        candidates = agent._select_monitor_candidates(
            {
                "LMT": {"latest_price": 625.0},
                "CVX": {"latest_price": 203.5},
                "KO": {"latest_price": 74.9},
            },
            {
                "stocks": {
                    "LMT": {"recommendation": "buy", "trade_plan": {"entry": 628.0, "stop_loss": 610.0, "target": 665.0}},
                    "CVX": {"recommendation": "buy", "trade_plan": {"entry": 203.0, "stop_loss": 196.0, "target": 215.0}},
                    "KO": {"recommendation": "watch", "trade_plan": {"entry": 70.0, "stop_loss": 68.0, "target": 75.0}},
                }
            },
            {"CVX": {"news_headlines": [{"title": "fresh"}]}},
        )

        assert [item["symbol"] for item in candidates] == ["LMT", "CVX"]


def test_research_agent_collects_web_context_for_high_value_symbols(
    message_bus, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setattr(research_module, "PerformanceTracker", DummyTracker)
    reset_settings()

    agent = ResearchAgent(message_bus)

    def fake_fetch(*, symbol: str, query: str, search_url: str, limit: int) -> list[dict]:
        return [
            {
                "title": f"{symbol} live article",
                "url": f"https://example.com/{symbol.lower()}",
                "source": "ExampleWire",
                "reason": f"Live verification for {symbol}",
            }
        ]

    monkeypatch.setattr(agent, "_fetch_google_news_articles", fake_fetch)

    context = agent._collect_web_context(
        {
            "AAPL": {"latest_price": 190.0, "info": {"market_cap": 3_000_000_000_000}},
            "MSFT": {"latest_price": 430.0, "info": {"market_cap": 3_200_000_000_000}},
            "SOFI": {"latest_price": 8.0, "info": {"market_cap": 8_000_000_000}},
        },
        {
            "AAPL": {"news_headlines": [{"title": "AAPL headline"}], "source_count": 2},
            "MSFT": {"news_headlines": [{"title": "MSFT headline"}], "source_count": 3},
            "SOFI": {"news_headlines": [], "source_count": 0},
        },
        limit=2,
    )

    assert context["priority_symbols"] == ["MSFT", "AAPL"]
    assert [check["symbol"] for check in context["checks"]] == ["MSFT", "AAPL"]
    assert context["articles_by_symbol"]["MSFT"][0]["url"] == "https://example.com/msft"


def test_research_agent_merges_web_context_into_analysis(
    message_bus, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setattr(research_module, "PerformanceTracker", DummyTracker)
    reset_settings()

    agent = ResearchAgent(message_bus)
    merged = agent._merge_web_context_into_analysis(
        {
            "stocks": {
                "AAPL": {
                    "supporting_articles": [
                        {"title": "Original", "url": "https://example.com/original"}
                    ]
                },
                "MSFT": {},
            },
            "web_checks": [{"symbol": "AAPL", "url": "https://example.com/search/aapl"}],
        },
        {
            "checks": [
                {"symbol": "AAPL", "url": "https://example.com/search/aapl"},
                {"symbol": "MSFT", "url": "https://example.com/search/msft"},
            ],
            "articles_by_symbol": {
                "AAPL": [
                    {"title": "Original", "url": "https://example.com/original"},
                    {"title": "Fresh AAPL", "url": "https://example.com/aapl"},
                ],
                "MSFT": [{"title": "Fresh MSFT", "url": "https://example.com/msft"}],
            },
        },
    )

    assert len(merged["web_checks"]) == 2
    assert len(merged["stocks"]["AAPL"]["supporting_articles"]) == 2
    assert merged["stocks"]["MSFT"]["supporting_articles"][0]["url"] == "https://example.com/msft"


class AnthropicErroringClient:
    class Messages:
        @staticmethod
        def create(**kwargs):
            raise RuntimeError("Your credit balance is too low to access the Anthropic API")

    class MessagesWithRawResponse:
        @staticmethod
        def create(**kwargs):
            raise RuntimeError("Your credit balance is too low to access the Anthropic API")

    class WrappedMessages(Messages):
        pass

    WrappedMessages.with_raw_response = MessagesWithRawResponse()
    messages = WrappedMessages()


class OpenAIJsonClient:
    class RawResponse:
        headers = {
            "x-ratelimit-remaining-requests": "4999",
            "x-ratelimit-remaining-tokens": "9990",
        }
        request_id = "req_test"

        @staticmethod
        def parse():
            class Usage:
                prompt_tokens = 10
                completion_tokens = 5
                total_tokens = 15
                prompt_tokens_details = None
                completion_tokens_details = None

            class Message:
                content = (
                    '{"overall_sentiment":"bullish","market_summary":"fallback ok",'
                    '"stocks":{}}'
                )

            class Choice:
                message = Message()

            class Response:
                model = "gpt-4o-mini"
                service_tier = "default"
                choices = [Choice()]
                usage = Usage()

            return Response()

    class Chat:
        class Completions:
            @staticmethod
            def create(**kwargs):
                return OpenAIJsonClient.RawResponse()

            with_raw_response = None

        Completions.with_raw_response = Completions()

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


@pytest.mark.asyncio
async def test_research_agent_cli_path_falls_back_without_raising(
    message_bus, monkeypatch
):
    monkeypatch.setenv("DEBUG_MODE", "false")
    monkeypatch.setenv("USE_CLI_AGENT", "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setattr(research_module, "PerformanceTracker", DummyTracker)
    monkeypatch.setattr(research_module, "build_recent_artifact_summary", lambda **kwargs: "")
    monkeypatch.setattr(research_module, "save_prompt_context_snapshot", lambda **kwargs: None)
    monkeypatch.setattr(research_module, "record_llm_analytics", lambda **kwargs: None)
    monkeypatch.setattr(ResearchAgent, "_save_research", lambda self, analysis, phase: None)
    monkeypatch.setattr(research_module, "is_cli_available", lambda provider: True)
    monkeypatch.setattr(research_module, "write_staging_data", lambda **kwargs: None)
    monkeypatch.setattr(research_module, "build_research_task", lambda symbols, **kwargs: "task")
    monkeypatch.setattr(
        research_module,
        "run_cli_agent",
        lambda *args, **kwargs: {
            "_meta": {
                "status": "error",
                "error": "cli failed",
                "provider": "cli:claude",
            }
        },
    )

    async def fake_call_llm(self, prompt: str, phase: str, **kwargs) -> dict:
        return {
            "overall_sentiment": "neutral",
            "market_summary": "fallback ok",
            "stocks": {},
            "_meta": {"status": "success", "provider": "openai", "model": "gpt-4o-mini"},
        }

    monkeypatch.setattr(ResearchAgent, "_call_llm", fake_call_llm)
    reset_settings()

    agent = ResearchAgent(message_bus)
    result = await agent.process(
        Message(
            type=MessageType.COMMAND,
            source="test",
            data={
                "symbols": ["AAPL"],
                "market_data": {
                    "AAPL": {
                        "latest_price": 100.0,
                        "price_change_pct": 1.0,
                        "volume": 1000,
                        "indicators": {},
                        "price_history": [],
                        "info": {},
                    }
                },
                "phase": "research",
                "news": {},
                "market_headlines": [],
                "market_context": {},
                "news_discoveries": [],
                "hot_stocks": [],
                "finviz": {},
            },
        )
    )

    assert result["research"]["market_summary"] == "fallback ok"
    assert result["research"]["_meta"]["provider"] == "openai"


@pytest.mark.asyncio
async def test_research_agent_reflection_phase_does_not_require_market_data(
    message_bus, monkeypatch
):
    monkeypatch.setenv("USE_CLI_AGENT", "false")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(research_module, "PerformanceTracker", DummyTracker)
    monkeypatch.setattr(
        research_module,
        "build_recent_artifact_summary",
        lambda **kwargs: "recent artifacts",
    )
    reset_settings()

    agent = ResearchAgent(message_bus)

    async def fake_call_analysis(self, prompt: str, phase: str, **kwargs) -> dict:
        assert phase == "evening_reflection"
        return {
            "date": "2026-03-22",
            "market_regime": "neutral",
            "market_summary": "Reflection succeeded",
            "lessons": ["Keep sizing tight after resets."],
            "_meta": {"status": "success", "provider": "openai", "model": "gpt-4o-mini"},
        }

    monkeypatch.setattr(ResearchAgent, "_call_phase_analysis", fake_call_analysis)
    monkeypatch.setattr(ResearchAgent, "_save_research", lambda self, analysis, phase: None)

    result = await agent.process(
        Message(
            type=MessageType.COMMAND,
            source="test",
            data={
                "phase": "evening_reflection",
                "market_data": {},
                "todays_trades": "No trades executed today.",
                "market_regime_summary": "Flat tape.",
                "active_positions": "No active swing positions.",
                "recent_observations": "No prior observations.",
                "symbols": ["AAPL"],
            },
        )
    )

    assert result["phase"] == "evening_reflection"
    assert result["research"]["market_summary"] == "Reflection succeeded"


@pytest.mark.asyncio
async def test_research_agent_records_cli_failure_before_api_fallback(
    message_bus, monkeypatch
):
    monkeypatch.setenv("DEBUG_MODE", "false")
    monkeypatch.setenv("USE_CLI_AGENT", "true")
    monkeypatch.setenv("CLI_AGENT_PROVIDER", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setattr(research_module, "PerformanceTracker", DummyTracker)
    monkeypatch.setattr(research_module, "is_cli_available", lambda provider: True)
    monkeypatch.setattr(research_module, "write_staging_data", lambda **kwargs: None)
    monkeypatch.setattr(research_module, "build_research_task", lambda symbols, **kwargs: "task")
    monkeypatch.setattr(
        research_module,
        "run_cli_agent",
        lambda *args, **kwargs: {
            "_meta": {
                "status": "error",
                "provider": "cli:claude",
                "model": "claude-sonnet-4-6",
                "duration_ms": 123.4,
                "error": "cli limit hit",
            }
        },
    )
    reset_settings()

    agent = ResearchAgent(message_bus)
    captured = {}

    async def fake_call_llm(self, prompt: str, phase: str, **kwargs) -> dict:
        captured["providers"] = kwargs.get("providers")
        captured["prior_attempts"] = kwargs.get("prior_attempts")
        return {
            "overall_sentiment": "neutral",
            "market_summary": "anthropic fallback ok",
            "stocks": {},
            "_meta": {"status": "success", "provider": "anthropic", "model": "claude-sonnet-4-6"},
        }

    monkeypatch.setattr(ResearchAgent, "_call_llm", fake_call_llm)

    result = await agent._call_analysis(
        prompt="{}",
        phase="research",
        symbols=["AAPL"],
        market_data={"AAPL": {"latest_price": 100}},
        news_data={},
        market_context={},
        market_headlines=[],
        screener_results=None,
        news_discoveries=[],
        hot_stocks=[],
        finviz_data={},
        performance_feedback="",
        learned_rules="",
        artifact_context="",
    )

    assert result["market_summary"] == "anthropic fallback ok"
    assert captured["providers"] == ["anthropic"]
    assert captured["prior_attempts"][0]["provider"] == "cli:claude"
    assert captured["prior_attempts"][0]["quota_issue_detected"] is False


@pytest.mark.asyncio
async def test_research_agent_debug_mode_returns_template_without_model_calls(
    message_bus, monkeypatch
):
    monkeypatch.setenv("DEBUG_MODE", "true")
    monkeypatch.setenv("USE_CLI_AGENT", "true")
    monkeypatch.setenv("CLI_AGENT_PROVIDER", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setattr(research_module, "PerformanceTracker", DummyTracker)
    reset_settings()

    agent = ResearchAgent(message_bus)
    result = await agent._call_analysis(
        prompt="{}",
        phase="research",
        symbols=["AAPL"],
        market_data={"AAPL": {"latest_price": 200.0, "price_change_pct": 1.5}},
        news_data={},
        market_context={},
        market_headlines=[],
        screener_results=None,
        news_discoveries=[],
        hot_stocks=[],
        finviz_data={},
        performance_feedback="",
        learned_rules="",
        artifact_context="",
    )

    assert result["_meta"]["execution_mode"] == "template"
    assert result["_meta"]["usage"]["total_tokens"] == 0
    assert result["stocks"]["AAPL"]["recommendation"] == "watch"
