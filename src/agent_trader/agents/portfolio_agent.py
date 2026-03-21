"""Portfolio Agent — tracks positions, P&L, and generates snapshots.

This agent runs last in the pipeline. It:
  1. Records executed trades
  2. Updates position values based on current prices
  3. Calculates daily/total P&L
  4. Generates a snapshot for the dashboard

Portfolio state is persisted to a JSON file so it survives between runs.
The GitHub Pages dashboard reads these snapshots.
"""

import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

from agent_trader.core.base_agent import BaseAgent, AgentRole
from agent_trader.core.message_bus import MessageBus, Message
from agent_trader.config.settings import get_settings
from agent_trader.utils.profiles import build_profile_metadata


class PortfolioAgent(BaseAgent):
    """Tracks portfolio state and generates performance snapshots."""

    def __init__(self, message_bus: MessageBus):
        super().__init__(AgentRole.PORTFOLIO, message_bus)
        self._portfolio: dict = {}
        self._history: list[dict] = []

    async def process(self, message: Message) -> Any:
        executed = message.data.get("executed", [])
        market_data = message.data.get("market_data", {})

        # Load existing portfolio state
        self._load_state()

        # Record new trades
        for trade in executed:
            if trade.get("status") in ("submitted", "dry_run"):
                self._record_trade(trade)

        # Update position values from current market data
        self._update_values(market_data)

        # Calculate P&L
        snapshot = self._generate_snapshot(market_data)

        # Save state and snapshot
        self._save_state()
        self._save_snapshot(snapshot)

        return snapshot

    def _record_trade(self, trade: dict) -> None:
        """Record a trade in the portfolio."""
        symbol = trade["symbol"]
        action = trade["action"]
        qty = trade.get("quantity", 0)
        price = trade.get("estimated_price", 0)

        if symbol not in self._portfolio:
            self._portfolio[symbol] = {
                "shares": 0,
                "avg_cost": 0,
                "total_invested": 0,
                "trades": [],
            }

        position = self._portfolio[symbol]

        if action == "buy":
            total_shares = position["shares"] + qty
            total_cost = position["total_invested"] + (qty * price)
            position["shares"] = total_shares
            position["total_invested"] = total_cost
            position["avg_cost"] = total_cost / total_shares if total_shares > 0 else 0

        elif action == "sell":
            position["shares"] = max(0, position["shares"] - qty)
            if position["shares"] == 0:
                position["total_invested"] = 0
                position["avg_cost"] = 0

        position["trades"].append({
            "action": action,
            "quantity": qty,
            "price": price,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": trade.get("status"),
        })

    def _update_values(self, market_data: dict) -> None:
        """Update current values based on latest prices."""
        for symbol, position in self._portfolio.items():
            data = market_data.get(symbol, {})
            current_price = data.get("latest_price", position.get("last_price", 0))
            position["last_price"] = current_price
            position["current_value"] = position["shares"] * current_price
            position["unrealized_pnl"] = (
                position["current_value"] - position["total_invested"]
            )
            if position["total_invested"] > 0:
                position["unrealized_pnl_pct"] = (
                    position["unrealized_pnl"] / position["total_invested"] * 100
                )
            else:
                position["unrealized_pnl_pct"] = 0

    def _generate_snapshot(self, market_data: dict) -> dict:
        """Generate a portfolio snapshot for the dashboard."""
        settings = get_settings()
        profile = build_profile_metadata(settings)

        total_value = sum(
            p.get("current_value", 0) for p in self._portfolio.values()
        )
        total_invested = sum(
            p.get("total_invested", 0) for p in self._portfolio.values()
        )
        total_pnl = total_value - total_invested
        cash = settings.paper_portfolio_value - total_invested

        positions = []
        for symbol, pos in self._portfolio.items():
            if pos["shares"] > 0:
                positions.append({
                    "symbol": symbol,
                    "shares": pos["shares"],
                    "avg_cost": round(pos["avg_cost"], 2),
                    "current_price": round(pos.get("last_price", 0), 2),
                    "current_value": round(pos.get("current_value", 0), 2),
                    "unrealized_pnl": round(pos.get("unrealized_pnl", 0), 2),
                    "unrealized_pnl_pct": round(pos.get("unrealized_pnl_pct", 0), 2),
                })

        snapshot = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "profile": profile["id"],
            "profile_label": profile["label"],
            "portfolio_value": round(total_value + cash, 2),
            "cash": round(cash, 2),
            "invested": round(total_invested, 2),
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": round(total_pnl / settings.paper_portfolio_value * 100, 2)
            if settings.paper_portfolio_value > 0
            else 0,
            "positions": positions,
            "position_count": len(positions),
        }

        return snapshot

    def _state_path(self) -> Path:
        return Path(get_settings().data_dir) / "portfolio_state.json"

    def _snapshot_dir(self) -> Path:
        return Path(get_settings().data_dir) / "snapshots"

    def _load_state(self) -> None:
        """Load portfolio state from disk."""
        path = self._state_path()
        if path.exists():
            self._portfolio = json.loads(path.read_text())

    def _save_state(self) -> None:
        """Persist portfolio state to disk."""
        path = self._state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self._portfolio, indent=2))

    def _save_snapshot(self, snapshot: dict) -> None:
        """Save a timestamped snapshot for the dashboard."""
        snapshot_dir = self._snapshot_dir()
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        # Save as latest
        latest = snapshot_dir / "latest.json"
        latest.write_text(json.dumps(snapshot, indent=2))

        # Append to history
        history_file = snapshot_dir / "history.json"
        history = []
        if history_file.exists():
            history = json.loads(history_file.read_text())

        history.append(snapshot)

        # Keep last 365 snapshots (one per day for a year)
        if len(history) > 365:
            history = history[-365:]

        history_file.write_text(json.dumps(history, indent=2))
