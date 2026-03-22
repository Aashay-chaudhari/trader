"""Swing Position Tracker — multi-day position management.

Tracks open swing trades (2-5 day holds) with daily updates, stop-loss
monitoring, and P&L tracking. Integrates with the evening reflection
phase for daily updates and with the research prompt for context.

Position lifecycle:
  1. open_position() → creates positions/active/SYMBOL_YYYYMMDD.json
  2. update_position() → appends daily update to the position
  3. close_position() → moves to positions/closed/ with P&L + lessons
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SwingTracker:
    """Manages swing trade positions on disk."""

    def __init__(self, data_dir: str = "data"):
        self.root = Path(data_dir)
        self.active_dir = self.root / "positions" / "active"
        self.closed_dir = self.root / "positions" / "closed"
        self.active_dir.mkdir(parents=True, exist_ok=True)
        self.closed_dir.mkdir(parents=True, exist_ok=True)

    def open_position(
        self,
        symbol: str,
        entry_price: float,
        quantity: int,
        stop_loss: float,
        target: float,
        *,
        timeframe: str = "swing_2_5_days",
        reasoning: str = "",
        confidence: float = 0.5,
        position_size_pct: float = 0.0,
    ) -> Path:
        """Open a new swing position.

        Returns:
            Path to the created position file.
        """
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        position = {
            "symbol": symbol.upper(),
            "entry_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "entry_price": entry_price,
            "quantity": quantity,
            "stop_loss": stop_loss,
            "target": target,
            "timeframe": timeframe,
            "reasoning": reasoning,
            "confidence": confidence,
            "position_size_pct": position_size_pct,
            "daily_updates": [],
            "status": "active",
        }

        path = self.active_dir / f"{symbol.upper()}_{today}.json"
        _write_json(path, position)
        logger.info("Opened swing position: %s @ %.2f", symbol, entry_price)
        return path

    def update_position(
        self,
        symbol: str,
        current_price: float,
        *,
        notes: str = "",
        date: str | None = None,
    ) -> dict | None:
        """Add a daily update to an active position.

        Returns:
            Updated position dict, or None if position not found.
        """
        path = self._find_active_position(symbol)
        if not path:
            logger.warning("No active position for %s", symbol)
            return None

        position = json.loads(path.read_text())
        entry = position["entry_price"]
        pnl_pct = ((current_price - entry) / entry * 100) if entry > 0 else 0

        update = {
            "date": date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "close": current_price,
            "pnl_pct": round(pnl_pct, 2),
            "note": notes,
        }
        position["daily_updates"].append(update)
        _write_json(path, position)
        return position

    def close_position(
        self,
        symbol: str,
        exit_price: float,
        reason: str = "",
        *,
        lessons: str = "",
    ) -> dict | None:
        """Close an active position and move it to closed/.

        Args:
            symbol: Stock symbol.
            exit_price: Price at which the position was closed.
            reason: Why it was closed (target_hit, stop_hit, thesis_break, manual).
            lessons: What we learned from this trade.

        Returns:
            Closed position dict with P&L, or None if not found.
        """
        path = self._find_active_position(symbol)
        if not path:
            logger.warning("No active position to close for %s", symbol)
            return None

        position = json.loads(path.read_text())
        entry = position["entry_price"]
        quantity = position["quantity"]
        pnl = (exit_price - entry) * quantity
        pnl_pct = ((exit_price - entry) / entry * 100) if entry > 0 else 0

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        entry_date = position.get("entry_date", "")
        days_held = 0
        if entry_date:
            try:
                d1 = datetime.strptime(entry_date, "%Y-%m-%d")
                d2 = datetime.strptime(today, "%Y-%m-%d")
                days_held = (d2 - d1).days
            except ValueError:
                pass

        position.update({
            "exit_date": today,
            "exit_price": exit_price,
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "days_held": days_held,
            "exit_reason": reason,
            "lessons": lessons,
            "status": "closed",
        })

        # Move to closed directory
        entry_date_compact = entry_date.replace("-", "")
        today_compact = today.replace("-", "")
        closed_path = self.closed_dir / f"{symbol.upper()}_{entry_date_compact}_{today_compact}.json"
        _write_json(closed_path, position)

        # Remove from active
        path.unlink()
        logger.info(
            "Closed swing %s: %+.2f (%+.1f%%) after %d days — %s",
            symbol, pnl, pnl_pct, days_held, reason,
        )
        return position

    def get_active_positions(self) -> list[dict]:
        """Load all active positions."""
        positions = []
        for f in sorted(self.active_dir.glob("*.json")):
            try:
                positions.append(json.loads(f.read_text()))
            except (json.JSONDecodeError, OSError):
                pass
        return positions

    def get_position(self, symbol: str) -> dict | None:
        """Load a specific active position."""
        path = self._find_active_position(symbol)
        if not path:
            return None
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def get_closed_positions(self, last_n: int = 20) -> list[dict]:
        """Load recent closed positions, newest first."""
        files = sorted(self.closed_dir.glob("*.json"), reverse=True)
        results = []
        for f in files[:last_n]:
            try:
                results.append(json.loads(f.read_text()))
            except (json.JSONDecodeError, OSError):
                pass
        return results

    def check_stops(self, market_data: dict[str, Any]) -> list[dict]:
        """Check if any active positions have hit their stop loss.

        Args:
            market_data: Dict mapping symbol -> {current_price, ...}

        Returns:
            List of positions that hit their stop loss.
        """
        triggered = []
        for position in self.get_active_positions():
            symbol = position["symbol"]
            stock_data = market_data.get(symbol, {})
            current_price = stock_data.get("current_price", stock_data.get("close", 0))
            if not current_price:
                continue

            stop = position.get("stop_loss", 0)
            if stop and current_price <= stop:
                triggered.append({
                    "symbol": symbol,
                    "current_price": current_price,
                    "stop_loss": stop,
                    "entry_price": position["entry_price"],
                    "pnl_pct": round(
                        (current_price - position["entry_price"])
                        / position["entry_price"] * 100, 2
                    ),
                })

            # Also check if target hit
            target = position.get("target", 0)
            if target and current_price >= target:
                triggered.append({
                    "symbol": symbol,
                    "current_price": current_price,
                    "target": target,
                    "entry_price": position["entry_price"],
                    "pnl_pct": round(
                        (current_price - position["entry_price"])
                        / position["entry_price"] * 100, 2
                    ),
                    "hit_target": True,
                })

        return triggered

    def get_summary_for_prompt(self, token_budget: int = 300) -> str:
        """Build a compact summary of active swing positions for the research prompt.

        Returns natural language, fits within token budget.
        """
        positions = self.get_active_positions()
        if not positions:
            return ""

        char_budget = token_budget * 4
        lines = [f"ACTIVE SWING POSITIONS ({len(positions)}):"]
        used = len(lines[0])

        for pos in positions:
            symbol = pos["symbol"]
            entry = pos["entry_price"]
            stop = pos.get("stop_loss", 0)
            target = pos.get("target", 0)
            days = len(pos.get("daily_updates", []))
            latest = pos.get("daily_updates", [{}])[-1] if pos.get("daily_updates") else {}
            current_pnl = latest.get("pnl_pct", 0)
            reason = pos.get("reasoning", "")[:60]

            line = (
                f"  {symbol}: entry ${entry:.2f}, stop ${stop:.2f}, "
                f"target ${target:.2f}, day {days}, P&L {current_pnl:+.1f}%"
            )
            if reason:
                line += f" — {reason}"

            if used + len(line) > char_budget:
                break
            lines.append(line)
            used += len(line)

        return "\n".join(lines) if len(lines) > 1 else ""

    # ── Private ────────────────────────────────────────────────────────

    def _find_active_position(self, symbol: str) -> Path | None:
        """Find the active position file for a symbol."""
        symbol = symbol.upper()
        matches = list(self.active_dir.glob(f"{symbol}_*.json"))
        if not matches:
            return None
        # If multiple (shouldn't happen), return most recent
        return sorted(matches, reverse=True)[0]


def _write_json(path: Path, data: Any) -> None:
    """Write JSON to file."""
    path.write_text(json.dumps(data, indent=2, default=str))
