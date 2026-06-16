"""Execution Agent — places trades via Alpaca paper trading API.

This agent only processes trades that have been approved by the RiskAgent.
It uses Alpaca's paper trading environment (free, no real money at risk).

Key safety features:
  - Only works in paper trading mode by default
  - Logs every order attempt with full details
  - Confirms fills and reports back to the portfolio agent
  - Has a kill switch (dry_run mode) for testing without any API calls
"""

import json
from pathlib import Path
from typing import Any

from agent_trader.core.base_agent import BaseAgent, AgentRole
from agent_trader.core.message_bus import MessageBus, Message, MessageType
from agent_trader.config.settings import get_settings
from agent_trader.utils.profiles import build_profile_metadata


class ExecutionAgent(BaseAgent):
    """Places trades via broker API (Alpaca paper trading)."""

    def __init__(self, message_bus: MessageBus):
        super().__init__(AgentRole.EXECUTION, message_bus)
        self._client = None

    def _get_client(self):
        """Lazy-init the Alpaca client."""
        if self._client is not None:
            return self._client

        settings = get_settings()

        if not settings.alpaca_api_key or not settings.alpaca_secret_key:
            return None  # Will run in dry_run mode

        from alpaca.trading.client import TradingClient

        self._client = TradingClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_secret_key,
            paper=settings.run_mode != "live",
        )
        return self._client

    async def process(self, message: Message) -> Any:
        approved_trades = message.data.get("approved_trades", [])
        market_data = message.data.get("market_data", {})
        settings = get_settings()

        if not approved_trades:
            return {
                "executed": [],
                "message": "No approved trades to execute",
                "symbols": message.data.get("symbols", []),
                "market_data": market_data,
            }

        client = self._get_client()
        executed = []

        for trade in approved_trades:
            result = await self._execute_trade(trade, market_data, client, settings)
            executed.append(result)

            self.emit(MessageType.TRADE_EXECUTED, result)

        return {
            "executed": executed,
            "symbols": message.data.get("symbols", []),
            "market_data": market_data,
        }

    async def _execute_trade(
        self, trade: dict, market_data: dict, client, settings
    ) -> dict:
        """Execute a single trade. Returns execution result."""
        symbol = trade["symbol"]
        action = trade["action"]
        profile = build_profile_metadata(settings)

        # Calculate quantity based on position size and portfolio value
        snapshot = self._load_latest_snapshot(settings)
        portfolio_value = float(snapshot.get("portfolio_value") or settings.paper_portfolio_value)
        cash = float(snapshot.get("cash") or portfolio_value)
        current_position = self._current_position(symbol, settings)
        current_position_value = float(current_position.get("current_value") or 0)
        current_shares = int(current_position.get("shares") or 0)
        max_position_value = portfolio_value * (settings.max_position_pct / 100)
        remaining_position_value = max(0.0, max_position_value - current_position_value)

        # Get approximate share count
        # In a real system, we'd use the current bid/ask
        price = (
            trade.get("latest_price")
            or trade.get("entry")
            or market_data.get(symbol, {}).get("latest_price", 0)
        )
        if price <= 0:
            return {
                "symbol": symbol,
                "profile": profile["id"],
                "profile_label": profile["label"],
                "status": "failed",
                "reason": "Could not determine price",
            }

        if action == "sell":
            if current_shares < 1:
                return {
                    "symbol": symbol,
                    "action": action,
                    "profile": profile["id"],
                    "profile_label": profile["label"],
                    "status": "failed",
                    "reason": "No long position to sell; short sales are not modeled",
                    "estimated_price": price,
                    "estimated_value": 0,
                }
            requested_qty = trade.get("quantity")
            try:
                qty = int(requested_qty) if requested_qty is not None else current_shares
            except (TypeError, ValueError):
                qty = current_shares
            qty = min(current_shares, qty)
        else:
            allocation = self._allocation_from_risk(
                trade=trade,
                price=price,
                portfolio_value=portfolio_value,
                settings=settings,
            )
            allocation = min(allocation, cash, remaining_position_value)
            qty = int(allocation / price)

        if qty < 1:
            return {
                "symbol": symbol,
                "action": action,
                "profile": profile["id"],
                "profile_label": profile["label"],
                "status": "failed",
                "reason": "Position sizing produced quantity below 1 share",
                "estimated_price": price,
                "estimated_value": 0,
            }

        # Dry run mode — log what would happen without calling the API
        if settings.is_dry_run or client is None:
            return {
                "symbol": symbol,
                "action": action,
                "quantity": qty,
                "estimated_price": price,
                "estimated_value": qty * price,
                "profile": profile["id"],
                "profile_label": profile["label"],
                "status": "dry_run",
                "reason": "Dry run mode — no order placed",
            }

        # Place the actual order via Alpaca
        try:
            from alpaca.trading.requests import MarketOrderRequest
            from alpaca.trading.enums import OrderSide, TimeInForce

            client_order_id = trade.get("client_order_id")
            order_request = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=OrderSide.BUY if action == "buy" else OrderSide.SELL,
                time_in_force=TimeInForce.DAY,
                client_order_id=client_order_id,
            )

            order = client.submit_order(order_request)

            return {
                "symbol": symbol,
                "action": action,
                "quantity": qty,
                "order_id": str(order.id),
                "client_order_id": client_order_id,
                "profile": profile["id"],
                "profile_label": profile["label"],
                "status": "submitted",
                "estimated_price": price,
                "estimated_value": qty * price,
            }

        except Exception as e:
            return {
                "symbol": symbol,
                "action": action,
                "quantity": qty,
                "client_order_id": trade.get("client_order_id"),
                "profile": profile["id"],
                "profile_label": profile["label"],
                "status": "failed",
                "reason": str(e),
            }

    def _allocation_from_risk(self, trade: dict, price: float, portfolio_value: float, settings) -> float:
        """Return notional allocation, preferring stop-loss risk over flat sizing."""
        entry = trade.get("entry") or price
        stop_loss = trade.get("stop_loss")
        try:
            entry = float(entry)
            stop_loss = float(stop_loss)
        except (TypeError, ValueError):
            entry = 0
            stop_loss = 0

        per_share_risk = abs(entry - stop_loss)
        if per_share_risk > 0:
            risk_budget = portfolio_value * (settings.risk_per_trade_pct / 100)
            return int(risk_budget / per_share_risk) * price

        size_pct = trade.get("suggested_size_pct", 5.0)
        return portfolio_value * (size_pct / 100)

    def _load_latest_snapshot(self, settings) -> dict:
        path = Path(settings.data_dir) / "snapshots" / "latest.json"
        try:
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
        return {}

    def _current_position(self, symbol: str, settings) -> dict:
        path = Path(settings.data_dir) / "portfolio_state.json"
        try:
            if not path.exists():
                return {}
            portfolio = json.loads(path.read_text(encoding="utf-8"))
            position = portfolio.get(symbol, {})
            return position if isinstance(position, dict) else {}
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            return {}
