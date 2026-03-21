"""Performance Feedback — lets Claude learn from its own trades.

After each trade closes (or at end of week), this module:
  1. Loads all completed trades from the journal
  2. Calculates actual P&L for each
  3. Builds a "performance review" prompt for Claude
  4. Claude analyzes what it got right and wrong
  5. Generates updated trading rules/biases for future sessions

This creates a feedback loop:
  Claude's analysis → trades → outcomes → Claude reviews → better analysis

The feedback is stored in data/feedback/ and loaded into the research prompt
so Claude sees its own track record every time it makes a recommendation.
"""

import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Any


class PerformanceTracker:
    """Tracks trade outcomes and generates feedback for Claude."""

    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.feedback_dir = self.data_dir / "feedback"
        self.feedback_dir.mkdir(parents=True, exist_ok=True)

    def record_trade_outcome(
        self,
        symbol: str,
        action: str,
        entry_price: float,
        exit_price: float | None,
        quantity: int,
        entry_date: str,
        exit_date: str | None = None,
        status: str = "open",
        reasoning: str = "",
        claude_confidence: float = 0.5,
        claude_recommendation: str = "",
    ) -> dict:
        """Record a trade's outcome for feedback."""
        pnl = 0.0
        pnl_pct = 0.0
        if exit_price and entry_price > 0:
            if action == "buy":
                pnl = (exit_price - entry_price) * quantity
                pnl_pct = (exit_price - entry_price) / entry_price * 100
            else:
                pnl = (entry_price - exit_price) * quantity
                pnl_pct = (entry_price - exit_price) / entry_price * 100

        trade = {
            "symbol": symbol,
            "action": action,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "quantity": quantity,
            "entry_date": entry_date,
            "exit_date": exit_date,
            "status": status,
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "won": pnl > 0,
            "reasoning": reasoning,
            "claude_confidence": claude_confidence,
            "claude_recommendation": claude_recommendation,
        }

        # Append to trades log
        trades_file = self.feedback_dir / "completed_trades.json"
        trades = []
        if trades_file.exists():
            trades = json.loads(trades_file.read_text())
        trades.append(trade)
        trades_file.write_text(json.dumps(trades, indent=2))

        return trade

    def get_performance_summary(self) -> dict:
        """Calculate overall trading performance stats."""
        trades_file = self.feedback_dir / "completed_trades.json"
        if not trades_file.exists():
            return {"total_trades": 0, "message": "No completed trades yet"}

        trades = json.loads(trades_file.read_text())
        if not trades:
            return {"total_trades": 0, "message": "No completed trades yet"}

        completed = [t for t in trades if t.get("status") == "closed"]
        if not completed:
            return {
                "total_trades": len(trades),
                "completed": 0,
                "open": len(trades),
                "message": "All trades still open",
            }

        wins = [t for t in completed if t["pnl"] > 0]
        losses = [t for t in completed if t["pnl"] <= 0]

        total_pnl = sum(t["pnl"] for t in completed)
        avg_win = sum(t["pnl"] for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t["pnl"] for t in losses) / len(losses) if losses else 0
        avg_win_pct = sum(t["pnl_pct"] for t in wins) / len(wins) if wins else 0
        avg_loss_pct = sum(t["pnl_pct"] for t in losses) / len(losses) if losses else 0

        # Best and worst trades
        best = max(completed, key=lambda t: t["pnl"])
        worst = min(completed, key=lambda t: t["pnl"])

        # Confidence calibration: were high-confidence trades more accurate?
        high_conf = [t for t in completed if t.get("claude_confidence", 0) >= 0.7]
        low_conf = [t for t in completed if t.get("claude_confidence", 0) < 0.5]

        high_conf_win_rate = (
            len([t for t in high_conf if t["pnl"] > 0]) / len(high_conf) * 100
            if high_conf else None
        )
        low_conf_win_rate = (
            len([t for t in low_conf if t["pnl"] > 0]) / len(low_conf) * 100
            if low_conf else None
        )

        return {
            "total_trades": len(trades),
            "completed": len(completed),
            "open": len(trades) - len(completed),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(completed) * 100, 1),
            "total_pnl": round(total_pnl, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "avg_win_pct": round(avg_win_pct, 2),
            "avg_loss_pct": round(avg_loss_pct, 2),
            "best_trade": {
                "symbol": best["symbol"],
                "pnl": best["pnl"],
                "pnl_pct": best["pnl_pct"],
            },
            "worst_trade": {
                "symbol": worst["symbol"],
                "pnl": worst["pnl"],
                "pnl_pct": worst["pnl_pct"],
            },
            "confidence_calibration": {
                "high_confidence_win_rate": high_conf_win_rate,
                "low_confidence_win_rate": low_conf_win_rate,
                "high_confidence_trades": len(high_conf),
                "low_confidence_trades": len(low_conf),
            },
        }

    def get_recent_trades_for_prompt(self, last_n: int = 10) -> str:
        """Format recent trade history for Claude's prompt.

        This is the key piece — it shows Claude its own track record
        so it can learn from what worked and what didn't.
        """
        trades_file = self.feedback_dir / "completed_trades.json"
        if not trades_file.exists():
            return "No trade history yet — this is the first run."

        trades = json.loads(trades_file.read_text())
        if not trades:
            return "No trade history yet — this is the first run."

        recent = trades[-last_n:]
        summary = self.get_performance_summary()

        lines = [
            f"YOUR TRADING TRACK RECORD ({summary.get('completed', 0)} completed trades):",
            f"  Win rate: {summary.get('win_rate', 0)}%",
            f"  Total P&L: ${summary.get('total_pnl', 0):+,.2f}",
            f"  Avg win: ${summary.get('avg_win', 0):+,.2f} ({summary.get('avg_win_pct', 0):+.1f}%)",
            f"  Avg loss: ${summary.get('avg_loss', 0):+,.2f} ({summary.get('avg_loss_pct', 0):+.1f}%)",
            "",
        ]

        # Confidence calibration feedback
        cal = summary.get("confidence_calibration", {})
        if cal.get("high_confidence_win_rate") is not None:
            lines.append(
                f"  Your high-confidence trades win {cal['high_confidence_win_rate']:.0f}% "
                f"of the time ({cal['high_confidence_trades']} trades)"
            )
        if cal.get("low_confidence_win_rate") is not None:
            lines.append(
                f"  Your low-confidence trades win {cal['low_confidence_win_rate']:.0f}% "
                f"of the time ({cal['low_confidence_trades']} trades)"
            )

        lines.append("")
        lines.append("RECENT TRADES:")

        for t in recent:
            result = "WON" if t.get("won") else "LOST"
            exit_part = f" → ${t['exit_price']:.2f}" if t.get("exit_price") else " (still open)"
            conf = t.get("claude_confidence", 0)
            conf_str = f"{conf:.0%}" if isinstance(conf, (int, float)) else str(conf)
            lines.append(
                f"  {t['entry_date']}: {t['action'].upper()} {t['symbol']} "
                f"@ ${t['entry_price']:.2f}{exit_part}"
                f" | {result} ${t['pnl']:+,.2f} ({t['pnl_pct']:+.1f}%)"
                f" | Your confidence was {conf_str}"
            )
            if t.get("reasoning"):
                lines.append(f"    Reasoning: {t['reasoning'][:100]}")

        lines.append("")
        lines.append("LEARN FROM THIS: Adjust your confidence and recommendations based on your actual results.")
        lines.append("If your high-confidence calls are losing, be more conservative.")
        lines.append("If a strategy pattern keeps winning, lean into it more.")

        return "\n".join(lines)

    def get_learned_rules(self) -> str:
        """Load Claude's self-generated trading rules from previous reviews."""
        rules_file = self.feedback_dir / "learned_rules.json"
        if not rules_file.exists():
            return ""

        rules = json.loads(rules_file.read_text())
        if not rules:
            return ""

        lines = ["YOUR SELF-GENERATED RULES FROM PAST PERFORMANCE REVIEWS:"]
        for rule in rules:
            lines.append(f"  - {rule}")

        return "\n".join(lines)

    def save_learned_rules(self, rules: list[str]) -> None:
        """Save Claude's self-generated rules after a performance review."""
        rules_file = self.feedback_dir / "learned_rules.json"
        existing = []
        if rules_file.exists():
            existing = json.loads(rules_file.read_text())

        # Append new rules, keep last 20
        existing.extend(rules)
        existing = existing[-20:]

        rules_file.write_text(json.dumps(existing, indent=2))
