"""CLI entry point for the trading system.

Usage:
  python -m agent_trader research              # Morning research phase
  python -m agent_trader monitor               # Monitor & trade phase
  python -m agent_trader run                   # Both phases back-to-back
  python -m agent_trader run --dry-run         # Full run, no orders
  python -m agent_trader status                # Show portfolio
  python -m agent_trader dashboard             # Generate dashboard HTML
"""

import asyncio
import argparse
import sys

from rich.console import Console

from agent_trader.runner import build_system, run_research, run_monitor, run_full

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

    # Status command
    subparsers.add_parser("status", help="Show portfolio status")

    # Dashboard command
    subparsers.add_parser("dashboard", help="Generate dashboard data")

    args = parser.parse_args()

    if args.command == "research":
        asyncio.run(cmd_research(args))
    elif args.command == "monitor":
        asyncio.run(cmd_monitor(args))
    elif args.command == "run":
        asyncio.run(cmd_run(args))
    elif args.command == "status":
        cmd_status()
    elif args.command == "dashboard":
        cmd_dashboard()
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
    if args.dry_run is not None:
        settings.dry_run = args.dry_run
    mode = "DRY RUN" if settings.dry_run else "PAPER TRADING"
    console.print(f"Mode: [yellow]{mode}[/yellow]")
    return await run_full(orchestrator, symbols)


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


if __name__ == "__main__":
    main()
