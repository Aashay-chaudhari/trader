"""Tests for the Orchestrator — pipeline coordination."""

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

    await orch.run_pipeline(["AAPL", "MSFT"])

    assert len(strategy_agent.received_messages) == 1
    assert strategy_agent.received_messages[0].data["symbols"] == ["ABBV", "UNH"]


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
