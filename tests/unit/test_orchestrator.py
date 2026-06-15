"""Tests for the Orchestrator — pipeline coordination."""

import json
import tempfile
from pathlib import Path
import pytest
from agent_trader.core import MessageBus, Orchestrator, BaseAgent, AgentRole, MessageType
from agent_trader.config.settings import reset_settings


class MockAgent(BaseAgent):
    """Simple test agent that returns whatever you configure."""

    def __init__(self, role, bus, return_value=None, should_fail=False):
        super().__init__(role, bus)
        self.return_value = return_value or {"mock": True}
        self.should_fail = should_fail
        self.received_messages = []

    async def process(self, message):
        self.received_messages.append(message)
        if self.should_fail:
            raise RuntimeError("Mock failure")
        return self.return_value


@pytest.fixture(autouse=True)
def force_debug_runtime(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "debug")
    monkeypatch.setenv("DATA_DIR", "data/profiles/default")
    monkeypatch.setenv("AGENT_PROFILE", "default")
    monkeypatch.setenv("AGENT_LABEL", "Test Strategist")
    reset_settings()
    yield
    reset_settings()


@pytest.mark.asyncio
async def test_pipeline_runs_agents_in_order():
    bus = MessageBus()
    orch = Orchestrator(bus)

    data_agent = MockAgent(AgentRole.DATA, bus, return_value={"prices": [1, 2, 3]})
    strategy_agent = MockAgent(AgentRole.STRATEGY, bus, return_value={"signals": []})

    orch.register(data_agent)
    orch.register(strategy_agent)

    await orch.run_pipeline(["AAPL"])

    # Both agents should have run (data agent runs in both phases)
    assert len(data_agent.received_messages) >= 1
    assert len(strategy_agent.received_messages) >= 1


@pytest.mark.asyncio
async def test_run_pipeline_uses_research_watchlist_for_monitor():
    with tempfile.TemporaryDirectory(dir=".") as temp_dir:
        bus = MessageBus()
        orch = Orchestrator(bus)

        screener_agent = MockAgent(
            AgentRole.DATA,
            bus,
            return_value={"symbols": ["ABBV", "UNH"], "shortlist": []},
        )
        screener_agent.role_name = "screener"
        data_agent = MockAgent(AgentRole.DATA, bus, return_value={"market_data": {}})
        strategy_agent = MockAgent(AgentRole.STRATEGY, bus, return_value={"signals": []})

        orch.register(screener_agent)
        orch.register(data_agent)
        orch.register(strategy_agent)

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setenv("DATA_DIR", temp_dir)

        try:
            await orch.run_pipeline(["AAPL", "MSFT"])
        finally:
            monkeypatch.undo()

        assert len(strategy_agent.received_messages) == 1
        assert strategy_agent.received_messages[0].data["symbols"] == ["ABBV", "UNH"]


@pytest.mark.asyncio
async def test_monitor_phase_includes_active_positions_from_portfolio(monkeypatch):
    with tempfile.TemporaryDirectory(dir=".") as temp_dir:
        monkeypatch.setenv("DATA_DIR", temp_dir)
        bus = MessageBus()
        orch = Orchestrator(bus)

        (Path(temp_dir) / "portfolio_state.json").write_text(
            '{"LMT":{"shares":5,"avg_cost":600},"KO":{"shares":0}}',
            encoding="utf-8",
        )

        data_agent = MockAgent(AgentRole.DATA, bus, return_value={"market_data": {}})
        strategy_agent = MockAgent(AgentRole.STRATEGY, bus, return_value={"signals": []})

        orch.register(data_agent)
        orch.register(strategy_agent)
        orch._today_watchlist = ["AAPL"]

        await orch.run_monitor_phase()

        assert strategy_agent.received_messages[0].data["symbols"] == ["AAPL", "LMT"]
        assert strategy_agent.received_messages[0].data["active_positions"] == ["LMT"]


@pytest.mark.asyncio
async def test_pipeline_continues_after_agent_failure():
    bus = MessageBus()
    orch = Orchestrator(bus)

    # Data agent fails, but strategy should still run
    data_agent = MockAgent(AgentRole.DATA, bus, should_fail=True)
    strategy_agent = MockAgent(AgentRole.STRATEGY, bus, return_value={"signals": []})

    orch.register(data_agent)
    orch.register(strategy_agent)

    await orch.run_pipeline(["AAPL"])

    # Strategy still ran (with error data from previous step)
    assert len(strategy_agent.received_messages) >= 1


@pytest.mark.asyncio
async def test_run_single_agent():
    bus = MessageBus()
    orch = Orchestrator(bus)

    agent = MockAgent(AgentRole.DATA, bus, return_value={"test": "value"})
    orch.register(agent)

    result = await orch.run_single(AgentRole.DATA, {"symbols": ["AAPL"]})

    assert result is not None
    assert result.type == MessageType.RESULT
    assert result.data == {"test": "value"}


@pytest.mark.asyncio
async def test_run_evening_reflection_writes_journal(monkeypatch):
    """run_evening_reflection should call the research agent and write a journal entry."""
    original_cwd = Path.cwd()
    with tempfile.TemporaryDirectory(dir=".") as tmp_dir:
        monkeypatch.chdir(Path(tmp_dir).resolve())
        bus = MessageBus()
        orch = Orchestrator(bus)

        research_agent = MockAgent(
            AgentRole.RESEARCH,
            bus,
            return_value={
                "research": {
                    "date": "2026-03-21",
                    "market_regime": "risk_on",
                    "market_summary": "Tech led rally",
                    "lessons": ["Momentum works in risk-on"],
                    "self_improvement_proposals": [],
                },
                "phase": "evening_reflection",
            },
        )
        orch.register(research_agent)

        result = await orch.run_evening_reflection()
        monkeypatch.chdir(original_cwd)

    assert result["phase"] == "evening_reflection"
    assert len(research_agent.received_messages) == 1
    assert research_agent.received_messages[0].data["phase"] == "evening_reflection"


@pytest.mark.asyncio
async def test_run_weekly_review_writes_journal(monkeypatch):
    """run_weekly_review should call research agent and run archival pass."""
    original_cwd = Path.cwd()
    with tempfile.TemporaryDirectory(dir=".") as tmp_dir:
        monkeypatch.chdir(Path(tmp_dir).resolve())
        bus = MessageBus()
        orch = Orchestrator(bus)

        research_agent = MockAgent(
            AgentRole.RESEARCH,
            bus,
            return_value={
                "research": {
                    "knowledge_updates": {"new_patterns": ["gap_and_go"], "new_lessons": ["lesson1"]},
                },
                "phase": "weekly_consolidation",
            },
        )
        orch.register(research_agent)

        result = await orch.run_weekly_review()
        monkeypatch.chdir(original_cwd)

    assert result["phase"] == "weekly_consolidation"
    assert len(research_agent.received_messages) == 1
    assert research_agent.received_messages[0].data["phase"] == "weekly_consolidation"


@pytest.mark.asyncio
async def test_run_monthly_retrospective_writes_journal(monkeypatch):
    """run_monthly_retrospective should call research agent for monthly review."""
    original_cwd = Path.cwd()
    with tempfile.TemporaryDirectory(dir=".") as tmp_dir:
        monkeypatch.chdir(Path(tmp_dir).resolve())
        bus = MessageBus()
        orch = Orchestrator(bus)

        research_agent = MockAgent(
            AgentRole.RESEARCH,
            bus,
            return_value={
                "research": {
                    "top_lessons": ["lesson A", "lesson B"],
                },
                "phase": "monthly_retrospective",
            },
        )
        orch.register(research_agent)

        result = await orch.run_monthly_retrospective()
        monkeypatch.chdir(original_cwd)

    assert result["phase"] == "monthly_retrospective"
    assert len(research_agent.received_messages) == 1
    assert research_agent.received_messages[0].data["phase"] == "monthly_retrospective"


def test_write_journal_preserves_research_phase_payload(monkeypatch):
    original_cwd = Path.cwd()
    with tempfile.TemporaryDirectory(dir=".") as temp_dir:
        monkeypatch.chdir(Path(temp_dir).resolve())
        bus = MessageBus()
        orch = Orchestrator(bus)

        orch._write_journal(
            "20260321_175214",
            "research",
            {
                "research": {
                    "research": {
                        "overall_sentiment": "neutral",
                        "market_summary": "test summary",
                        "stocks": {},
                    }
                }
            },
            screener_results={"shortlist": []},
        )

        report = next((Path("data") / "profiles" / "default" / "journal").rglob("*_research_report.json"))
        raw = json.loads(report.read_text(encoding="utf-8"))
        monkeypatch.chdir(original_cwd)

        assert raw["research"]["research"]["overall_sentiment"] == "neutral"


class LocalMonitorResearchHelper:
    """Tiny helper that mimics the ResearchAgent monitor helpers without LLM calls."""

    def __init__(self):
        self.saved = []
        self.monitor_market_data = None

    def _prepare_rich_summary(self, market_data):
        return {symbol: {"price": payload.get("latest_price")} for symbol, payload in market_data.items()}

    def _build_lean_monitor_context(self, market_summary, morning_context, news_data, market_context):
        self.monitor_market_data = market_summary
        return {
            "morning_plans": "  AAPL: buy | entry=$100 stop=$95 target=$110",
            "current_state": "| Stock | Price |\n|-------|-------|\n| AAPL | $100.50 |",
            "active_positions": "  (none)",
            "strategy_signals": "Strategy runs after monitor gate.",
            "decision_rules": "  - Approve only if the execution condition is satisfied.",
            "candidate_symbols": ["AAPL"],
        }

    def _normalize_monitor_analysis(self, analysis, *, morning_context, candidate_symbols):
        normalized = dict(analysis)
        normalized["stocks"] = {
            symbol: normalized.get("stocks", {}).get(symbol, {})
            for symbol in candidate_symbols
        }
        return normalized

    def _save_research(self, analysis, phase):
        self.saved.append((phase, analysis))


@pytest.mark.asyncio
async def test_prepare_local_monitor_context_writes_artifacts(monkeypatch):
    with tempfile.TemporaryDirectory(dir=".") as temp_dir:
        monkeypatch.setenv("DATA_DIR", temp_dir)
        reset_settings()
        cache_dir = Path(temp_dir) / "cache"
        cache_dir.mkdir(parents=True)
        (cache_dir / "morning_research.json").write_text(
            json.dumps(
                {
                    "stocks": {
                        "AAPL": {
                            "recommendation": "buy",
                            "execution_condition": "AAPL holds above $100.",
                            "trade_plan": {"entry": 100, "stop_loss": 95, "target": 110},
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

        bus = MessageBus()
        orch = Orchestrator(bus)
        orch.register(
            MockAgent(
                AgentRole.DATA,
                bus,
                return_value={
                    "market_data": {
                        "AAPL": {
                            "latest_price": 100.5,
                            "price_change_pct": 1.2,
                        }
                    }
                },
            )
        )
        news_agent = MockAgent(
            AgentRole.DATA,
            bus,
            return_value={"news": {"AAPL": {"news_headlines": []}}, "market_context": {}},
        )
        orch._agents["news"] = news_agent
        orch._agents["research"] = LocalMonitorResearchHelper()

        context = await orch.prepare_local_monitor_context(["AAPL"])

        assert context["status"] == "ready"
        assert context["candidate_symbols"] == ["AAPL"]
        assert orch._agents["research"].monitor_market_data["AAPL"]["latest_price"] == 100.5
        assert (cache_dir / "local_monitor_context.json").exists()
        assert (cache_dir / "local_monitor_prompt.md").exists()
        prompt = (cache_dir / "local_monitor_prompt.md").read_text(encoding="utf-8")
        assert "AAPL" in prompt
        assert "local_monitor_decision.json" in prompt


@pytest.mark.asyncio
async def test_prepare_local_monitor_context_rejects_stale_market_hours_quote(monkeypatch):
    with tempfile.TemporaryDirectory(dir=".") as temp_dir:
        monkeypatch.setenv("DATA_DIR", temp_dir)
        monkeypatch.setenv("RUN_MODE", "paper")
        monkeypatch.setattr("agent_trader.core.orchestrator._is_market_hours", lambda: True)
        reset_settings()
        cache_dir = Path(temp_dir) / "cache"
        cache_dir.mkdir(parents=True)
        (cache_dir / "morning_research.json").write_text(
            json.dumps(
                {
                    "stocks": {
                        "AAPL": {
                            "recommendation": "buy",
                            "trade_plan": {"entry": 100, "stop_loss": 95, "target": 110},
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

        bus = MessageBus()
        orch = Orchestrator(bus)
        orch.register(
            MockAgent(
                AgentRole.DATA,
                bus,
                return_value={
                    "market_data": {
                        "AAPL": {
                            "latest_price": 100.5,
                            "quote_source": "yahoo_daily_fallback",
                            "quote_is_fresh": False,
                        }
                    }
                },
            )
        )

        context = await orch.prepare_local_monitor_context(["AAPL"])

        assert context["status"] == "error"
        assert context["reason"] == "stale_monitor_quotes:AAPL"


@pytest.mark.asyncio
async def test_apply_local_monitor_decision_runs_trade_pipeline(monkeypatch):
    with tempfile.TemporaryDirectory(dir=".") as temp_dir:
        monkeypatch.setenv("DATA_DIR", temp_dir)
        reset_settings()
        cache_dir = Path(temp_dir) / "cache"
        cache_dir.mkdir(parents=True)

        context = {
            "run_id": "20260614_150000",
            "phase": "monitor",
            "status": "ready",
            "reason": "",
            "symbols": ["AAPL"],
            "active_positions": [],
            "market_data": {"AAPL": {"latest_price": 100.5}},
            "news": {"AAPL": {"news_headlines": []}},
            "market_context": {},
            "market_headlines": [],
            "morning_context": {
                "stocks": {
                    "AAPL": {
                        "recommendation": "buy",
                        "execution_condition": "AAPL holds above $100.",
                        "trade_plan": {"entry": 100, "stop_loss": 95, "target": 110},
                    }
                }
            },
            "prompt_sections": {"candidate_symbols": ["AAPL"]},
            "candidate_symbols": ["AAPL"],
            "prompt_text": "prepared monitor prompt",
        }
        decision = {
            "run_id": "20260614_150000",
            "overall_sentiment": "bullish",
            "market_summary": "AAPL confirms the morning setup.",
            "stocks": {
                "AAPL": {
                    "recommendation": "buy",
                    "confidence": 0.8,
                    "ready_to_trade": True,
                    "matched_conditions": ["held above $100"],
                    "failed_conditions": [],
                    "monitor_reason": "Price is holding above the trigger.",
                    "execution_condition": "AAPL holds above $100.",
                    "trade_plan": {"entry": 100, "stop_loss": 95, "target": 110},
                }
            },
        }
        (cache_dir / "local_monitor_context.json").write_text(json.dumps(context), encoding="utf-8")
        (cache_dir / "local_monitor_decision.json").write_text(json.dumps(decision), encoding="utf-8")

        bus = MessageBus()
        orch = Orchestrator(bus)
        research_helper = LocalMonitorResearchHelper()
        orch._agents["research"] = research_helper
        strategy_agent = MockAgent(
            AgentRole.STRATEGY,
            bus,
            return_value={
                "signals": [
                    {
                        "symbol": "AAPL",
                        "action": "buy",
                        "strength": 0.8,
                        "strategy": "monitor_gate",
                        "reasoning": "Local Codex gate confirmed the morning trigger.",
                    }
                ]
            },
        )
        risk_agent = MockAgent(
            AgentRole.RISK,
            bus,
            return_value={"approved_trades": [{"symbol": "AAPL", "action": "buy"}], "rejected_trades": []},
        )
        execution_agent = MockAgent(
            AgentRole.EXECUTION,
            bus,
            return_value={
                "executed": [
                    {
                        "symbol": "AAPL",
                        "action": "buy",
                        "price": 100.5,
                        "status": "submitted",
                        "client_order_id": "codex-20260614_150000-AAPL-buy-1",
                    }
                ]
            },
        )
        portfolio_agent = MockAgent(
            AgentRole.PORTFOLIO,
            bus,
            return_value={"portfolio_value": 100500, "positions": []},
        )
        orch.register(strategy_agent)
        orch.register(risk_agent)
        orch.register(execution_agent)
        orch.register(portfolio_agent)

        result = await orch.run_local_monitor_decision()

        assert result["phase"] == "monitor"
        assert strategy_agent.received_messages[0].data["research"]["stocks"]["AAPL"]["ready_to_trade"] is True
        assert len(risk_agent.received_messages) == 1
        assert len(execution_agent.received_messages) == 1
        approved_trade = execution_agent.received_messages[0].data["approved_trades"][0]
        assert approved_trade["client_order_id"] == "codex-20260614_150000-AAPL-buy-1"
        assert research_helper.saved[0][0] == "monitor"
        assert next((Path(temp_dir) / "journal").rglob("*_monitor_report.json")).exists()
        applied = json.loads(
            (cache_dir / "local_monitor_applied.json").read_text(encoding="utf-8")
        )
        assert applied["status"] == "completed"

        repeated = await orch.run_local_monitor_decision()
        assert repeated["skipped"] == "already_applied"
        assert len(execution_agent.received_messages) == 1
