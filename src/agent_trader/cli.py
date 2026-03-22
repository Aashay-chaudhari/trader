"""CLI entry point for the trading system.

Usage:
  python -m agent_trader research              # Morning research phase
  python -m agent_trader monitor               # Monitor & trade phase
  python -m agent_trader run                   # Both phases back-to-back
  python -m agent_trader run --dry-run         # Full run, no orders
  python -m agent_trader reset                 # Reset generated runtime state
  python -m agent_trader status                # Show portfolio
  python -m agent_trader dashboard             # Generate dashboard HTML
"""

import asyncio
import argparse
import sys

from rich.console import Console

from agent_trader.runner import (
    build_system, run_research, run_monitor, run_full, run_cycle,
    run_reflection, run_weekly, run_monthly, run_evolution,
)

console = Console()


def main():
    parser = argparse.ArgumentParser(description="Agent Trader - Multi-agent trading system")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Research command (Phase 1)
    research_parser = subparsers.add_parser("research", help="Morning research phase")
    research_parser.add_argument("--symbols", nargs="+", help="Override watchlist")

    # Monitor command (Phase 2)
    monitor_parser = subparsers.add_parser("monitor", help="Monitor & trade phase")
    monitor_parser.add_argument("--symbols", nargs="+", help="Override watchlist")

    # Full run command
    run_parser = subparsers.add_parser("run", help="Run both phases")
    run_parser.add_argument("--symbols", nargs="+", help="Override watchlist")
    run_parser.add_argument("--dry-run", action="store_true", default=None,
                            help="Run without placing orders")

    # Full cycle command
    cycle_parser = subparsers.add_parser("cycle", help="Run research, monitor, reflection, weekly, and monthly")
    cycle_parser.add_argument("--symbols", nargs="+", help="Override watchlist")
    cycle_parser.add_argument("--dry-run", action="store_true", default=None,
                              help="Run without placing orders")

    # Reflection command (Phase 3)
    reflect_parser = subparsers.add_parser("reflect", help="Evening reflection phase")

    # Weekly review command (Phase 4)
    weekly_parser = subparsers.add_parser("weekly", help="Weekly consolidation review")

    # Monthly retrospective command (Phase 5)
    monthly_parser = subparsers.add_parser("monthly", help="Monthly retrospective")

    # Evolution command (Phase 6) — propose concrete system improvements
    subparsers.add_parser("evolve", help="Analyze performance and propose system improvements")

    # Validate command — structural integrity checks
    validate_parser = subparsers.add_parser("validate", help="Validate system structure and schemas")
    validate_parser.add_argument("--smoke", action="store_true",
                                 help="Also run debug-mode smoke tests for each phase")

    # Status command
    subparsers.add_parser("status", help="Show portfolio status")

    # Reset command
    reset_parser = subparsers.add_parser("reset", help="Reset generated runtime state")
    reset_parser.add_argument("--all-profiles", action="store_true",
                              help="Reset all strategist profile data under data/profiles")
    reset_parser.add_argument("--docs", action="store_true",
                              help="Also clear generated GitHub Pages output under docs/")
    reset_parser.add_argument("--keep-knowledge", action="store_true",
                              help="Preserve knowledge/ and observations/ dirs (reset only runtime)")
    reset_parser.add_argument("--data-dir", help="Override data directory to reset")
    reset_parser.add_argument("--docs-dir", help="Override docs directory to reset")

    # Dashboard command
    subparsers.add_parser("dashboard", help="Generate dashboard data")

    # Alert command — send SMS manually
    alert_parser = subparsers.add_parser("alert", help="Send SMS alert/reminder")
    alert_parser.add_argument("type", choices=["morning", "evening", "weekly", "monthly", "test"],
                              help="Which reminder to send")

    # Add --debug flag to all action commands
    for p in [research_parser, monitor_parser, run_parser, cycle_parser,
              reflect_parser, weekly_parser, monthly_parser,
              subparsers._name_parser_map["evolve"]]:
        p.add_argument("--debug", action="store_true", help="Debug mode (reduced tokens)")

    args = parser.parse_args()

    # Apply debug mode if requested
    if getattr(args, "debug", False):
        import os
        os.environ["RUN_MODE"] = "debug"
        os.environ["DEBUG_MODE"] = "true"  # backward compat
        from agent_trader.config.settings import reset_settings
        reset_settings()

    if args.command == "research":
        asyncio.run(cmd_research(args))
    elif args.command == "monitor":
        asyncio.run(cmd_monitor(args))
    elif args.command == "run":
        asyncio.run(cmd_run(args))
    elif args.command == "cycle":
        asyncio.run(cmd_cycle(args))
    elif args.command == "reflect":
        asyncio.run(cmd_reflect())
    elif args.command == "weekly":
        asyncio.run(cmd_weekly())
    elif args.command == "monthly":
        asyncio.run(cmd_monthly())
    elif args.command == "evolve":
        asyncio.run(cmd_evolve())
    elif args.command == "validate":
        cmd_validate(args)
    elif args.command == "status":
        cmd_status()
    elif args.command == "reset":
        cmd_reset(args)
    elif args.command == "dashboard":
        cmd_dashboard()
    elif args.command == "alert":
        cmd_alert(args)
    else:
        parser.print_help()
        sys.exit(1)


async def cmd_research(args):
    """Morning research phase."""
    console.print("\n[bold]Agent Trader[/bold] — Morning Research\n")
    orchestrator, settings = build_system()
    symbols = getattr(args, "symbols", None) or settings.watchlist
    return await run_research(orchestrator, symbols)


async def cmd_monitor(args):
    """Monitor and trade phase."""
    console.print("\n[bold]Agent Trader[/bold] — Monitor & Trade\n")
    orchestrator, settings = build_system()
    symbols = getattr(args, "symbols", None)
    return await run_monitor(orchestrator, symbols)


async def cmd_run(args):
    """Run both phases."""
    console.print("\n[bold]Agent Trader[/bold] — Full Pipeline\n")
    orchestrator, settings = build_system()
    symbols = args.symbols or settings.watchlist
    if args.dry_run is not None and args.dry_run:
        settings.run_mode = "paper"
        settings.dry_run = True
    mode_label = {"debug": "DEBUG", "paper": "PAPER TRADING", "live": "LIVE"}
    console.print(f"Mode: [yellow]{mode_label.get(settings.run_mode, settings.run_mode)}[/yellow]")
    return await run_full(orchestrator, symbols)


async def cmd_cycle(args):
    """Run the full end-to-end cycle, including knowledge phases."""
    console.print("\n[bold]Agent Trader[/bold] - Full Cycle\n")
    orchestrator, settings = build_system()
    symbols = args.symbols or settings.watchlist
    if args.dry_run is not None and args.dry_run:
        settings.run_mode = "paper"
        settings.dry_run = True
    mode_label = {"debug": "DEBUG", "paper": "PAPER TRADING", "live": "LIVE"}
    console.print(f"Mode: [yellow]{mode_label.get(settings.run_mode, settings.run_mode)}[/yellow]")
    return await run_cycle(orchestrator, symbols)


async def cmd_reflect():
    """Evening reflection phase."""
    console.print("\n[bold]Agent Trader[/bold] — Evening Reflection\n")
    orchestrator, settings = build_system()
    return await run_reflection(orchestrator)


async def cmd_weekly():
    """Weekly consolidation review."""
    console.print("\n[bold]Agent Trader[/bold] — Weekly Review\n")
    orchestrator, settings = build_system()
    return await run_weekly(orchestrator)


async def cmd_monthly():
    """Monthly retrospective."""
    console.print("\n[bold]Agent Trader[/bold] — Monthly Retrospective\n")
    orchestrator, settings = build_system()
    return await run_monthly(orchestrator)


async def cmd_evolve():
    """Evolution phase — propose concrete system improvements."""
    console.print("\n[bold]Agent Trader[/bold] — Evolution\n")
    orchestrator, settings = build_system()
    return await run_evolution(orchestrator)


def cmd_status():
    """Show current portfolio status."""
    from pathlib import Path
    import json
    from agent_trader.config.settings import get_settings

    snapshot_path = Path(get_settings().data_dir) / "snapshots" / "latest.json"
    if not snapshot_path.exists():
        console.print("[yellow]No portfolio data yet. Run the pipeline first.[/yellow]")
        return

    snapshot = json.loads(snapshot_path.read_text())
    console.print(f"\n[bold]Portfolio Snapshot[/bold] ({snapshot['timestamp']})")
    console.print(f"  Value:    ${snapshot['portfolio_value']:,.2f}")
    console.print(f"  Cash:     ${snapshot['cash']:,.2f}")
    console.print(f"  Invested: ${snapshot['invested']:,.2f}")
    console.print(f"  P&L:      ${snapshot['total_pnl']:,.2f} ({snapshot['total_pnl_pct']:.2f}%)")
    console.print(f"  Positions: {snapshot['position_count']}")

    for pos in snapshot.get("positions", []):
        pnl_color = "green" if pos["unrealized_pnl"] >= 0 else "red"
        console.print(
            f"    {pos['symbol']:6s}  {pos['shares']:4d} shares  "
            f"${pos['current_value']:>10,.2f}  "
            f"[{pnl_color}]{pos['unrealized_pnl']:+,.2f} ({pos['unrealized_pnl_pct']:+.2f}%)[/{pnl_color}]"
        )


def cmd_dashboard():
    """Generate dashboard HTML from latest snapshot."""
    from agent_trader.dashboard.generator import generate_dashboard
    generate_dashboard()
    console.print("[green]Dashboard generated at docs/index.html[/green]")


def cmd_reset(args):
    """Reset generated runtime state."""
    from agent_trader.utils.project_state import reset_project_state

    summary = reset_project_state(
        data_dir=args.data_dir,
        docs_dir=args.docs_dir,
        all_profiles=bool(args.all_profiles),
        include_docs=bool(args.docs),
        keep_knowledge=bool(args.keep_knowledge),
    )
    console.print("[green]Project state reset complete.[/green]")
    console.print(f"  Data root: {summary['data_root']}")
    console.print(f"  Removed paths: {len(summary['removed'])}")
    if summary["removed"]:
        for path in summary["removed"][:12]:
            console.print(f"    - {path}")
        if len(summary["removed"]) > 12:
            console.print(f"    ... and {len(summary['removed']) - 12} more")


def cmd_validate(args):
    """Validate system structure and run optional smoke tests."""
    from agent_trader.utils.validator import run_validation
    import sys
    report = run_validation(smoke=bool(getattr(args, "smoke", False)))
    if report["failed"] > 0:
        sys.exit(1)


def cmd_alert(args):
    """Send a push notification / alert."""
    from agent_trader.utils.alerts import alert_reminder, send_notification

    if args.type == "test":
        result = send_notification("Test alert working!", title="Agent Trader Test")
    else:
        result = alert_reminder(args.type)

    status = result.get("status", "unknown")
    if status == "skipped":
        console.print(f"[yellow]Skipped:[/yellow] {result.get('reason', 'no phone configured')}")
    elif status == "error":
        console.print(f"[red]Error:[/red] {result.get('error', 'unknown')}")
    else:
        console.print(f"[green]SMS sent[/green] (status: {status})")


if __name__ == "__main__":
    main()
