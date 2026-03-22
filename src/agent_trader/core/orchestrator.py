"""Orchestrator — the brain that coordinates all agents.

Two operating modes:

PHASE 1 — Morning Research (9:00 AM ET):
  1. ScreenerAgent scans universe for today's opportunities
  2. DataAgent fetches detailed data for shortlisted stocks
  3. NewsAgent gathers headlines, analyst recs, earnings calendar
  4. ResearchAgent does deep Claude Sonnet analysis with full context
  → Output: today's watchlist + research insights + trade plans
  → Saved to journal

PHASE 2 — Monitor & Trade (every 30 min during market hours):
  1. DataAgent refreshes prices for the watchlist
  2. NewsAgent checks for new headlines
  3. ResearchAgent does light Claude Haiku check
  4. StrategyAgent checks 8 strategies for entry/exit signals
  5. RiskAgent validates proposed trades
  6. ExecutionAgent places approved trades (or dry-run logs)
  7. PortfolioAgent updates positions and dashboard
  → Each run saved to journal with full reasoning
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from agent_trader.config.settings import get_settings
from agent_trader.core.base_agent import BaseAgent, AgentRole
from agent_trader.core.message_bus import MessageBus, Message, MessageType
from agent_trader.utils.profiles import build_profile_metadata

console = Console()


class Orchestrator:
    """Coordinates all agents through research and trading pipelines."""

    def __init__(self, message_bus: MessageBus | None = None):
        self.bus = message_bus or MessageBus()
        self._agents: dict[str, BaseAgent] = {}
        self._today_watchlist: list[str] = []
        self._morning_research: dict | None = None

    def register(self, agent: BaseAgent) -> None:
        key = getattr(agent, "role_name", agent.role.value)
        self._agents[key] = agent
        console.print(f"  [green]Registered[/green] {agent.name}")

    def get_agent(self, key: str) -> BaseAgent | None:
        return self._agents.get(key)

    # ── Phase 1: Morning Research ────────────────────────────────

    async def run_research_phase(self, fallback_symbols: list[str] | None = None) -> dict:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self._print_header(run_id, "Morning Research")

        results: dict[str, Any] = {"run_id": run_id, "phase": "research"}
        screener_results = None

        # Step 1: News discovery FIRST — find what's in the news
        # This feeds into the screener so stock selection is news+data driven
        news_discoveries = []
        hot_stocks = []
        finviz_data = {}
        market_context = {}
        market_headlines = []
        news_agent = self._agents.get("news")
        if news_agent:
            console.print("  [cyan]Scanning[/cyan] news for stock discoveries...")
            response = await news_agent.receive(
                Message(type=MessageType.COMMAND, source="orchestrator",
                        data={"symbols": [], "market_data": {}, "discover_stocks": True})
            )
            if response and response.type == MessageType.RESULT:
                news_discoveries = response.data.get("news_discoveries", [])
                hot_stocks = response.data.get("hot_stocks", [])
                finviz_data = response.data.get("finviz", {})
                market_context = response.data.get("market_context", {})
                results["news_discovery"] = {
                    "discoveries": len(news_discoveries),
                    "hot_stocks": len(hot_stocks),
                    "analyst_changes": len(finviz_data.get("analyst_changes", [])),
                    "market_regime": market_context.get("market_regime", "unknown"),
                }
                disc_symbols = [d["symbol"] for d in news_discoveries]
                if disc_symbols:
                    console.print(f"  [green]News found[/green] {len(disc_symbols)} stocks: "
                                  f"{', '.join(disc_symbols)}")
                else:
                    console.print("  [dim]No strong news-driven discoveries[/dim]")

        # Step 2: Screen with news context — news discovers, data confirms
        screener = self._agents.get("screener")
        if screener:
            console.print("  [cyan]Screening[/cyan] stock universe (news + technicals)...")
            response = await screener.receive(
                Message(type=MessageType.COMMAND, source="orchestrator",
                        data={
                            "max_stocks": 10,
                            "news_discoveries": news_discoveries,
                            "hot_stocks": hot_stocks,
                            "finviz": finviz_data,
                        })
            )
            if response and response.type == MessageType.RESULT:
                screener_results = response.data
                self._today_watchlist = response.data.get("symbols", [])
                console.print(f"  [green]Found[/green] {len(self._today_watchlist)} stocks: "
                              f"{', '.join(self._today_watchlist)}")
                results["screener"] = response.data
            else:
                console.print("  [yellow]Screener failed, using fallback[/yellow]")
                self._today_watchlist = fallback_symbols or ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN"]
        else:
            self._today_watchlist = fallback_symbols or ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN"]

        # Step 3: Fetch detailed data for the shortlist
        market_data = {}
        data_agent = self._agents.get("data")
        if data_agent:
            console.print("  [cyan]Fetching[/cyan] market data...")
            response = await data_agent.receive(
                Message(type=MessageType.COMMAND, source="orchestrator",
                        data={"symbols": self._today_watchlist})
            )
            if response and response.type == MessageType.RESULT:
                results["data"] = response.data
                market_data = response.data.get("market_data", {})
                console.print("  [green]Done[/green] market data")

        # Step 4: Full news for the shortlisted stocks (per-stock detail)
        news_data = {}
        if news_agent:
            console.print("  [cyan]Gathering[/cyan] detailed news for shortlist...")
            response = await news_agent.receive(
                Message(type=MessageType.COMMAND, source="orchestrator",
                        data={"symbols": self._today_watchlist, "market_data": market_data})
            )
            if response and response.type == MessageType.RESULT:
                news_data = response.data.get("news", {})
                market_headlines = response.data.get("market_headlines", [])
                # Update market context with fresh data
                market_context = response.data.get("market_context", {}) or market_context
                results["news"] = response.data
                headline_count = sum(len(v.get("news_headlines", [])) for v in news_data.values())
                source_stats = response.data.get("source_stats", {})
                sources_msg = ", ".join(f"{k}:{v}" for k, v in source_stats.items() if v) if source_stats else ""
                console.print(f"  [green]Done[/green] news ({headline_count} headlines"
                              + (f" | {sources_msg}" if sources_msg else "") + ")")

        # Step 5: Claude Sonnet deep research (with everything)
        research_agent = self._agents.get("research")
        if research_agent:
            console.print("  [cyan]Analyzing[/cyan] with Claude Sonnet...")
            response = await research_agent.receive(
                Message(type=MessageType.COMMAND, source="orchestrator", data={
                    "symbols": self._today_watchlist,
                    "market_data": market_data,
                    "phase": "research",
                    "screener_results": screener_results,
                    "news": news_data,
                    "market_headlines": market_headlines,
                    "market_context": market_context,
                    "news_discoveries": news_discoveries,
                    "hot_stocks": hot_stocks,
                    "finviz": finviz_data,
                })
            )
            if response and response.type == MessageType.RESULT:
                self._morning_research = response.data.get("research", {})
                results["research"] = response.data
                sentiment = self._morning_research.get("overall_sentiment", "unknown")
                regime = self._morning_research.get("market_regime", "unknown")
                console.print(f"  [green]Done[/green] research — {sentiment}, regime: {regime}")

        self._save_morning_context()
        self._write_journal(run_id, "research", results, screener_results)
        self._print_research_summary(results)

        return results

    # ── Phase 2: Monitor & Trade ─────────────────────────────────

    async def run_monitor_phase(self, symbols: list[str] | None = None) -> dict:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        watchlist = symbols or self._today_watchlist or self._load_watchlist()

        if not watchlist:
            console.print("[yellow]No watchlist. Run research phase first.[/yellow]")
            return {"run_id": run_id, "phase": "monitor", "error": "no watchlist"}

        self._print_header(run_id, f"Monitor ({', '.join(watchlist[:5])})")

        results: dict[str, Any] = {"run_id": run_id, "phase": "monitor"}
        morning_context = self._morning_research or self._load_morning_context()

        # Step 1: Refresh market data
        market_data = {}
        data_agent = self._agents.get("data")
        if data_agent:
            console.print("  [cyan]Refreshing[/cyan] prices...")
            response = await data_agent.receive(
                Message(type=MessageType.COMMAND, source="orchestrator",
                        data={"symbols": watchlist})
            )
            if response and response.type == MessageType.RESULT:
                market_data = response.data.get("market_data", {})
                results["data"] = {"status": "ok", "data": response.data}
                console.print("  [green]Done[/green] prices")

        # Step 2: Check for new news
        news_data = {}
        market_context = {}
        market_headlines = []
        news_agent = self._agents.get("news")
        if news_agent:
            console.print("  [cyan]Checking[/cyan] news...")
            response = await news_agent.receive(
                Message(type=MessageType.COMMAND, source="orchestrator",
                        data={"symbols": watchlist, "market_data": market_data})
            )
            if response and response.type == MessageType.RESULT:
                news_data = response.data.get("news", {})
                market_context = response.data.get("market_context", {})
                market_headlines = response.data.get("market_headlines", [])

        # Step 3: Light Claude Haiku check
        research_data = {}
        research_agent = self._agents.get("research")
        if research_agent:
            console.print("  [cyan]Claude check[/cyan]...")
            response = await research_agent.receive(
                Message(type=MessageType.COMMAND, source="orchestrator", data={
                    "symbols": watchlist,
                    "market_data": market_data,
                    "phase": "monitor",
                    "morning_context": morning_context,
                    "news": news_data,
                    "market_headlines": market_headlines,
                    "market_context": market_context,
                })
            )
            if response and response.type == MessageType.RESULT:
                research_data = response.data.get("research", {})
                results["research"] = {"status": "ok", "data": response.data}
                console.print("  [green]Done[/green] Claude check")

        # Step 4: Strategy signals
        strategy_data = {}
        strategy_agent = self._agents.get("strategy")
        if strategy_agent:
            console.print("  [cyan]Evaluating[/cyan] strategies...")
            response = await strategy_agent.receive(
                Message(type=MessageType.COMMAND, source="orchestrator", data={
                    "symbols": watchlist,
                    "market_data": market_data,
                    "research": research_data,
                    "news": news_data,
                    "market_context": market_context,
                })
            )
            if response and response.type == MessageType.RESULT:
                strategy_data = response.data
                signals = strategy_data.get("signals", [])
                results["strategy"] = {"status": "ok", "data": strategy_data}
                console.print(f"  [green]Done[/green] {len(signals)} signal(s)")

        # Step 5: Risk check
        risk_data = {}
        risk_agent = self._agents.get("risk")
        if risk_agent and strategy_data.get("signals"):
            console.print("  [cyan]Risk check[/cyan]...")
            response = await risk_agent.receive(
                Message(type=MessageType.COMMAND, source="orchestrator", data={
                    "signals": strategy_data.get("signals", []),
                    "market_data": market_data,
                    "symbols": watchlist,
                })
            )
            if response and response.type == MessageType.RESULT:
                risk_data = response.data
                approved = len(risk_data.get("approved_trades", []))
                rejected = len(risk_data.get("rejected_trades", []))
                results["risk"] = {"status": "ok", "data": risk_data}
                console.print(f"  [green]Done[/green] {approved} approved, {rejected} rejected")

        # Step 6: Execute
        execution_data = {}
        execution_agent = self._agents.get("execution")
        if execution_agent:
            exec_input = risk_data if risk_data else {"approved_trades": [], "symbols": watchlist, "market_data": market_data}
            console.print("  [cyan]Executing[/cyan]...")
            response = await execution_agent.receive(
                Message(type=MessageType.COMMAND, source="orchestrator", data=exec_input)
            )
            if response and response.type == MessageType.RESULT:
                execution_data = response.data
                executed = execution_data.get("executed", [])
                results["execution"] = {"status": "ok", "data": execution_data}
                console.print(f"  [green]Done[/green] {len(executed)} trade(s)")

        # Step 7: Portfolio update
        portfolio_agent = self._agents.get("portfolio")
        if portfolio_agent:
            console.print("  [cyan]Updating[/cyan] portfolio...")
            response = await portfolio_agent.receive(
                Message(type=MessageType.COMMAND, source="orchestrator", data={
                    "executed": execution_data.get("executed", []),
                    "market_data": market_data,
                    "symbols": watchlist,
                })
            )
            if response and response.type == MessageType.RESULT:
                results["portfolio"] = {"status": "ok", "data": response.data}
                val = response.data.get("portfolio_value", 0)
                console.print(f"  [green]Done[/green] portfolio ${val:,.0f}")

        self._write_journal(run_id, "monitor", results)
        self._print_monitor_summary(results)

        return results

    # ── Full Pipeline ────────────────────────────────────────────

    # ── Phase 3: Evening Reflection ──────────────────────────────

    async def run_evening_reflection(self) -> dict:
        """Evening reflection: review the day and extract observations."""
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self._print_header(run_id, "Evening Reflection")

        results: dict[str, Any] = {"run_id": run_id, "phase": "evening_reflection"}

        # Gather context for reflection
        from agent_trader.utils.knowledge_base import KnowledgeBase
        from agent_trader.utils.swing_tracker import SwingTracker
        from agent_trader.utils.improvement_log import append_improvement_proposals

        settings = get_settings()
        kb = KnowledgeBase(settings.data_dir)
        st = SwingTracker(settings.data_dir)

        # Today's trades from journal
        todays_trades = self._load_todays_journal_summary()

        # Market regime from morning research
        morning = self._morning_research or self._load_morning_context()
        market_regime_summary = "No regime data."
        if morning:
            regime = morning.get("market_regime", "unknown")
            summary = morning.get("market_summary", "")
            market_regime_summary = f"Regime: {regime}. {summary}"

        # Active swing positions
        active_positions = st.get_summary_for_prompt(token_budget=300)
        if not active_positions:
            active_positions = "No active swing positions."

        # Recent observations
        recent_obs = kb.get_recent_observations(days=3)
        recent_observations = "No prior observations."
        if recent_obs:
            lines = []
            for obs in recent_obs:
                lines.append(f"  {obs.get('date', '?')}: {obs.get('market_summary', '')}")
            recent_observations = "Recent observations:\n" + "\n".join(lines)

        # Call research agent with reflection phase
        research_agent = self._agents.get("research")
        if research_agent:
            console.print("  [cyan]Reflecting[/cyan] on today's session...")
            response = await research_agent.receive(
                Message(type=MessageType.COMMAND, source="orchestrator", data={
                    "phase": "evening_reflection",
                    "market_data": {},  # Required by research agent
                    "todays_trades": todays_trades,
                    "market_regime_summary": market_regime_summary,
                    "active_positions": active_positions,
                    "recent_observations": recent_observations,
                    "symbols": self._today_watchlist or self._load_watchlist(),
                })
            )
            if response and response.type == MessageType.RESULT:
                results["research"] = response.data
                reflection = response.data.get("research", {})
                lessons = reflection.get("lessons", [])
                console.print(f"  [green]Done[/green] reflection — {len(lessons)} lessons extracted")

                # Persist self-improvement proposals
                proposals = reflection.get("self_improvement_proposals", [])
                if proposals:
                    profile_id = settings.agent_profile or "default"
                    append_improvement_proposals(
                        proposals,
                        data_dir=settings.data_dir,
                        profile_id=profile_id,
                    )
                    console.print(f"  [green]Saved[/green] {len(proposals)} improvement proposals")

        self._write_journal(run_id, "evening_reflection", results)
        return results

    # ── Phase 4: Weekly Consolidation ─────────────────────────────

    async def run_weekly_review(self) -> dict:
        """Weekly review: consolidate observations and update knowledge base."""
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self._print_header(run_id, "Weekly Review")

        results: dict[str, Any] = {"run_id": run_id, "phase": "weekly_consolidation"}

        research_agent = self._agents.get("research")
        if research_agent:
            console.print("  [cyan]Consolidating[/cyan] week's observations...")
            response = await research_agent.receive(
                Message(type=MessageType.COMMAND, source="orchestrator", data={
                    "phase": "weekly_consolidation",
                    "market_data": {},  # Required
                    "symbols": self._load_watchlist(),
                })
            )
            if response and response.type == MessageType.RESULT:
                results["research"] = response.data
                review = response.data.get("research", {})
                updates = review.get("knowledge_updates", {})
                console.print(f"  [green]Done[/green] weekly review — "
                              f"patterns: {len(updates.get('new_patterns', []))}, "
                              f"lessons: {len(updates.get('new_lessons', []))}")

        # Run archival pass
        from agent_trader.utils.knowledge_base import KnowledgeBase
        settings = get_settings()
        kb = KnowledgeBase(settings.data_dir)
        archived = kb.archive_old_observations(keep_days=settings.observation_retention_days)
        if archived:
            console.print(f"  [dim]Archived {archived} old observations[/dim]")

        self._write_journal(run_id, "weekly_consolidation", results)
        return results

    # ── Phase 5: Monthly Retrospective ────────────────────────────

    async def run_monthly_retrospective(self) -> dict:
        """Monthly review: deep retrospective and strategic adjustments."""
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self._print_header(run_id, "Monthly Retrospective")

        results: dict[str, Any] = {"run_id": run_id, "phase": "monthly_retrospective"}

        research_agent = self._agents.get("research")
        if research_agent:
            console.print("  [cyan]Conducting[/cyan] monthly retrospective...")
            response = await research_agent.receive(
                Message(type=MessageType.COMMAND, source="orchestrator", data={
                    "phase": "monthly_retrospective",
                    "market_data": {},  # Required
                    "symbols": [],
                })
            )
            if response and response.type == MessageType.RESULT:
                results["research"] = response.data
                review = response.data.get("research", {})
                lessons = review.get("top_lessons", [])
                console.print(f"  [green]Done[/green] monthly retrospective — "
                              f"{len(lessons)} top lessons")

        self._write_journal(run_id, "monthly_retrospective", results)
        return results

    # ── Full Pipeline ─────────────────────────────────────────────

    async def run_pipeline(self, symbols: list[str]) -> dict:
        self._today_watchlist = symbols
        research = await self.run_research_phase(fallback_symbols=symbols)
        monitor_symbols = self._today_watchlist or symbols
        monitor = await self.run_monitor_phase(monitor_symbols)
        return {"research": research, "monitor": monitor}

    async def run_single(self, role: AgentRole, data: Any = None) -> Message | None:
        agent = self._agents.get(role.value)
        if not agent:
            return None
        return await agent.receive(
            Message(type=MessageType.COMMAND, source="orchestrator", data=data or {})
        )

    # ── Journal ──────────────────────────────────────────────────

    def _write_journal(self, run_id, phase, results, screener_results=None):
        try:
            from agent_trader.utils.journal import create_journal_entry
            settings = get_settings()

            def unwrap_stage(stage_key: str) -> dict[str, Any]:
                stage = results.get(stage_key, {})
                if isinstance(stage, dict) and "data" in stage:
                    return stage.get("data", {}) or {}
                return stage if isinstance(stage, dict) else {}

            research_data = unwrap_stage("research")
            strategy_data = unwrap_stage("strategy")
            risk_data = unwrap_stage("risk")
            execution_data = unwrap_stage("execution")
            portfolio_data = unwrap_stage("portfolio")

            filepath = create_journal_entry(
                run_id=run_id, phase=phase,
                screener_results=screener_results or results.get("screener"),
                research_results=research_data,
                signals=strategy_data.get("signals") if strategy_data else None,
                risk_results=risk_data,
                executed=execution_data.get("executed") if execution_data else None,
                portfolio_snapshot=portfolio_data,
                market_data=strategy_data.get("market_data") if strategy_data else None,
                data_dir=settings.data_dir,
                profile=build_profile_metadata(settings),
            )
            console.print(f"  [dim]Journal: {filepath}[/dim]")
        except Exception as e:
            console.print(f"  [yellow]Journal failed: {e}[/yellow]")

    # ── Context Persistence ──────────────────────────────────────

    def _save_morning_context(self):
        if not self._morning_research:
            return
        ctx_dir = Path(get_settings().data_dir) / "cache"
        ctx_dir.mkdir(parents=True, exist_ok=True)
        (ctx_dir / "morning_research.json").write_text(
            json.dumps(self._morning_research, indent=2, default=str))
        (ctx_dir / "watchlist.json").write_text(json.dumps(self._today_watchlist))

    def _load_morning_context(self) -> dict | None:
        path = Path(get_settings().data_dir) / "cache" / "morning_research.json"
        return json.loads(path.read_text()) if path.exists() else None

    def _load_watchlist(self) -> list[str]:
        path = Path(get_settings().data_dir) / "cache" / "watchlist.json"
        return json.loads(path.read_text()) if path.exists() else []

    def _load_todays_journal_summary(self) -> str:
        """Load a summary of today's journal entries for evening reflection."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        journal_dir = Path(get_settings().data_dir) / "journal" / today
        if not journal_dir.exists():
            return "No journal entries today."

        lines = [f"TODAY'S JOURNAL ({today}):"]
        for f in sorted(journal_dir.glob("*_report.json")):
            try:
                entry = json.loads(f.read_text())
                research = entry.get("research", {})
                sentiment = research.get("overall_sentiment", "?")
                regime = research.get("market_regime", "?")
                phase = entry.get("phase", f.stem)
                lines.append(f"  {phase}: sentiment={sentiment}, regime={regime}")
                # Include executed trades if any
                executed = entry.get("executed", [])
                if executed:
                    for trade in executed[:5]:
                        lines.append(
                            f"    Trade: {trade.get('action', '?')} {trade.get('symbol', '?')} "
                            f"@ ${trade.get('price', 0):.2f}"
                        )
            except (json.JSONDecodeError, OSError):
                pass

        return "\n".join(lines) if len(lines) > 1 else "No readable journal entries today."

    # ── Display ──────────────────────────────────────────────────

    def _print_header(self, run_id, phase):
        console.print(f"\n[bold blue]{'='*60}[/bold blue]")
        console.print(f"[bold blue]  {phase} — {run_id}[/bold blue]")
        console.print(f"[bold blue]{'='*60}[/bold blue]\n")

    def _print_research_summary(self, results):
        console.print("\n[bold]Research Summary[/bold]")
        research_stage = results.get("research", {})
        research = research_stage.get("data", {}).get("research", {})
        if not research and isinstance(research_stage, dict):
            research = research_stage.get("research", {})
        if not research:
            console.print("  [yellow]No research results[/yellow]")
            return
        console.print(f"  Sentiment: {research.get('overall_sentiment', '?')}")
        console.print(f"  Regime: {research.get('market_regime', '?')}")
        console.print(f"  {research.get('market_summary', '')}")
        best = research.get("best_opportunities", [])
        if best:
            console.print(f"  Best opportunities: [bold]{', '.join(best)}[/bold]")

    def _print_monitor_summary(self, results):
        console.print("\n[bold]Monitor Summary[/bold]")
        table = Table(show_header=True)
        table.add_column("Stage", style="cyan")
        table.add_column("Status")
        table.add_column("Details", max_width=50)

        for key in ["data", "research", "strategy", "risk", "execution", "portfolio"]:
            result = results.get(key)
            if result is None:
                table.add_row(key, "[dim]skipped[/dim]", "-")
            elif result.get("status") == "error":
                table.add_row(key, "[red]error[/red]", str(result.get("error", ""))[:50])
            else:
                data = result.get("data", {})
                detail = ""
                if key == "strategy":
                    detail = f"{len(data.get('signals', []))} signals"
                elif key == "risk":
                    detail = f"{len(data.get('approved_trades', []))} approved, {len(data.get('rejected_trades', []))} rejected"
                elif key == "execution":
                    detail = f"{len(data.get('executed', []))} trades"
                elif key == "portfolio":
                    detail = f"${data.get('portfolio_value', 0):,.0f}"
                table.add_row(key, "[green]ok[/green]", detail)

        console.print(table)
