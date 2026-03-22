"""Tests for the Orchestrator — pipeline coordination."""

import json
import tempfile
from pathlib import Path
import pytest
from agent_trader.core import MessageBus, Orchestrator, BaseAgent, AgentRole, MessageType


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

        report = next((Path("data") / "journal").rglob("*_research_report.json"))
        raw = json.loads(report.read_text(encoding="utf-8"))
        monkeypatch.chdir(original_cwd)

        assert raw["research"]["research"]["overall_sentiment"] == "neutral"
