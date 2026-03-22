"""Tests for top-level runner helpers."""

import pytest

from agent_trader.runner import run_cycle


class StubOrchestrator:
    def __init__(self):
        self.calls = []

    async def run_pipeline(self, symbols):
        self.calls.append(("run_pipeline", list(symbols)))
        return {"phase": "run"}

    async def run_evening_reflection(self):
        self.calls.append(("reflect", None))
        return {"phase": "reflect"}

    async def run_weekly_review(self):
        self.calls.append(("weekly", None))
        return {"phase": "weekly"}

    async def run_monthly_retrospective(self):
        self.calls.append(("monthly", None))
        return {"phase": "monthly"}

    async def run_evolution(self):
        self.calls.append(("evolution", None))
        return {"phase": "evolution"}


@pytest.mark.asyncio
async def test_run_cycle_includes_evolution():
    orchestrator = StubOrchestrator()

    result = await run_cycle(orchestrator, ["AAPL", "MSFT"])

    assert result["evolution"]["phase"] == "evolution"
    assert orchestrator.calls == [
        ("run_pipeline", ["AAPL", "MSFT"]),
        ("reflect", None),
        ("weekly", None),
        ("monthly", None),
        ("evolution", None),
    ]
