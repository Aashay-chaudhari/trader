"""System builder and runner — wires everything together."""

from rich.console import Console

from agent_trader.core import MessageBus, Orchestrator
from agent_trader.agents import (
    DataAgent,
    ScreenerAgent,
    ResearchAgent,
    StrategyAgent,
    RiskAgent,
    ExecutionAgent,
    PortfolioAgent,
)
from agent_trader.agents.news_agent import NewsAgent
from agent_trader.config.settings import Settings, get_settings, reset_settings

console = Console()


def build_system(settings: Settings | None = None) -> tuple[Orchestrator, Settings]:
    """Create and wire up all agents."""
    reset_settings()
    settings = settings or get_settings()

    console.print("[bold]Building trading system...[/bold]")

    bus = MessageBus()
    orchestrator = Orchestrator(bus)

    # Register all agents — orchestrator looks them up by key name
    screener = ScreenerAgent(bus)
    orchestrator._agents["screener"] = screener
    console.print("  [green]Registered[/green] screener_agent")

    orchestrator.register(DataAgent(bus))

    news = NewsAgent(bus)
    orchestrator._agents["news"] = news
    console.print("  [green]Registered[/green] news_agent")

    orchestrator.register(ResearchAgent(bus))
    orchestrator.register(StrategyAgent(bus))
    orchestrator.register(RiskAgent(bus))
    orchestrator.register(ExecutionAgent(bus))
    orchestrator.register(PortfolioAgent(bus))

    console.print("[green]System ready.[/green]\n")
    return orchestrator, settings


async def run_research(orchestrator: Orchestrator, symbols: list[str] | None = None) -> dict:
    return await orchestrator.run_research_phase(fallback_symbols=symbols)


async def run_monitor(orchestrator: Orchestrator, symbols: list[str] | None = None) -> dict:
    return await orchestrator.run_monitor_phase(symbols)


async def run_full(orchestrator: Orchestrator, symbols: list[str]) -> dict:
    return await orchestrator.run_pipeline(symbols)
