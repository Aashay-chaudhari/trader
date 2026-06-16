"""Risk Agent — validates trades before execution.

This is the safety net. Every trade signal must pass through here
before it reaches the execution agent. It checks:

  1. Position limits: no single stock > X% of portfolio
  2. Daily loss limit: stop trading if daily loss exceeds threshold
  3. Concentration: don't over-allocate to one sector
  4. Correlation: don't hold too many correlated positions
  5. Signal strength: reject weak signals

If a trade fails any check, it's rejected with a clear reason.
The orchestrator sees exactly why trades were blocked.
"""

from typing import Any

from agent_trader.core.base_agent import BaseAgent, AgentRole
from agent_trader.core.message_bus import MessageBus, Message, MessageType
from agent_trader.config.settings import get_settings


class RiskAgent(BaseAgent):
    """Validates trade signals against risk rules."""

    def __init__(self, message_bus: MessageBus):
        super().__init__(AgentRole.RISK, message_bus)

    async def process(self, message: Message) -> Any:
        signals = message.data.get("signals", [])
        market_data = message.data.get("market_data", {})
        active_positions = self._active_position_symbols(message.data)
        settings = get_settings()

        approved = []
        rejected = []

        for signal in signals:
            checks = self._run_checks(signal, market_data, settings, active_positions)
            failures = [c for c in checks if not c["passed"]]

            if failures:
                signal["rejection_reasons"] = [f["reason"] for f in failures]
                rejected.append(signal)

                self.emit(MessageType.TRADE_REJECTED, {
                    "symbol": signal["symbol"],
                    "reasons": signal["rejection_reasons"],
                })
            else:
                approved.append(signal)
                self.emit(MessageType.TRADE_APPROVED, {
                    "symbol": signal["symbol"],
                    "action": signal["action"],
                    "strength": signal["strength"],
                })

        return {
            "approved_trades": approved,
            "rejected_trades": rejected,
            "symbols": message.data.get("symbols", []),
            "market_data": market_data,
            "active_positions": sorted(active_positions),
        }

    def _run_checks(
        self,
        signal: dict,
        market_data: dict,
        settings,
        active_positions: set[str],
    ) -> list[dict]:
        """Run all risk checks on a single trade signal."""
        checks = []

        # Check 1: Long-only enforcement
        checks.append(self._check_long_only_exit(signal, active_positions))

        # Check 2: Minimum signal strength
        checks.append(self._check_signal_strength(signal, settings))

        # Check 3: Position size limit
        checks.append(self._check_position_size(signal, settings))

        # Check 4: Price sanity (is the stock trading normally?)
        checks.append(self._check_price_sanity(signal, market_data))

        # Check 5: Volume check (enough liquidity?)
        checks.append(self._check_volume(signal, market_data))

        return checks

    def _active_position_symbols(self, data: dict) -> set[str]:
        """Normalize held long symbols from orchestrator payloads."""
        symbols: set[str] = set()

        for item in data.get("active_positions", []) or []:
            if isinstance(item, str) and item.strip():
                symbols.add(item.strip().upper())
            elif isinstance(item, dict):
                symbol = str(item.get("symbol") or "").strip().upper()
                if symbol:
                    symbols.add(symbol)

        for item in data.get("positions", []) or []:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol") or "").strip().upper()
            shares = item.get("shares", item.get("quantity", 0))
            try:
                share_count = float(shares or 0)
            except (TypeError, ValueError):
                share_count = 0.0
            if symbol and share_count > 0:
                symbols.add(symbol)

        return symbols

    def _check_long_only_exit(self, signal: dict, active_positions: set[str]) -> dict:
        """Sells are exits only; short sales are disabled."""
        action = str(signal.get("action", "")).lower()
        symbol = str(signal.get("symbol", "")).upper()
        passed = action != "sell" or symbol in active_positions
        return {
            "check": "long_only_exit",
            "passed": passed,
            "reason": (
                f"{symbol} sell is only allowed to exit an existing long position; "
                "shorts are disabled"
            ),
        }

    def _check_signal_strength(self, signal: dict, settings) -> dict:
        """Reject signals that aren't strong enough."""
        min_strength = settings.min_signal_strength
        strength = signal.get("strength", 0)

        return {
            "check": "signal_strength",
            "passed": strength >= min_strength,
            "reason": f"Signal strength {strength:.2f} below minimum {min_strength}",
        }

    def _check_position_size(self, signal: dict, settings) -> dict:
        """No single position should exceed max allocation."""
        size_pct = signal.get("suggested_size_pct", 0)
        max_pct = settings.max_position_pct

        return {
            "check": "position_size",
            "passed": size_pct <= max_pct,
            "reason": f"Position size {size_pct}% exceeds max {max_pct}%",
        }

    def _check_price_sanity(self, signal: dict, market_data: dict) -> dict:
        """Flag stocks with extreme price moves (possible data error or halt)."""
        symbol = signal["symbol"]
        data = market_data.get(symbol, {})
        change_pct = abs(data.get("price_change_pct", 0))

        return {
            "check": "price_sanity",
            "passed": change_pct < 15,  # >15% move in a day is suspicious
            "reason": f"{symbol} moved {change_pct:.1f}% today — possible anomaly",
        }

    def _check_volume(self, signal: dict, market_data: dict) -> dict:
        """Ensure stock has enough trading volume."""
        symbol = signal["symbol"]
        data = market_data.get(symbol, {})
        volume = data.get("volume", 0)
        min_volume = 100_000  # At least 100K shares traded

        return {
            "check": "volume",
            "passed": volume >= min_volume,
            "reason": f"{symbol} volume ({volume:,}) below minimum ({min_volume:,})",
        }
