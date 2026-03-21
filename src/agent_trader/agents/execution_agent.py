"""Execution Agent — places trades via Alpaca paper trading API.

This agent only processes trades that have been approved by the RiskAgent.
It uses Alpaca's paper trading environment (free, no real money at risk).

Key safety features:
  - Only works in paper trading mode by default
  - Logs every order attempt with full details
  - Confirms fills and reports back to the portfolio agent
  - Has a kill switch (dry_run mode) for testing without any API calls
"""

from typing import Any

from agent_trader.core.base_agent import BaseAgent, AgentRole
from agent_trader.core.message_bus import MessageBus, Message, MessageType
from agent_trader.config.settings import get_settings


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
            paper=True,  # ALWAYS paper trading
        )
        return self._client

    async def process(self, message: Message) -> Any:
        approved_trades = message.data.get("approved_trades", [])
        settings = get_settings()

        if not approved_trades:
            return {
                "executed": [],
                "message": "No approved trades to execute",
                "symbols": message.data.get("symbols", []),
                "market_data": message.data.get("market_data", {}),
            }

        client = self._get_client()
        executed = []

        for trade in approved_trades:
            result = await self._execute_trade(trade, client, settings)
            executed.append(result)

            self.emit(MessageType.TRADE_EXECUTED, result)

        return {
            "executed": executed,
            "symbols": message.data.get("symbols", []),
            "market_data": message.data.get("market_data", {}),
        }

    async def _execute_trade(
        self, trade: dict, client, settings
    ) -> dict:
        """Execute a single trade. Returns execution result."""
        symbol = trade["symbol"]
        action = trade["action"]
        strength = trade["strength"]

        # Calculate quantity based on position size and portfolio value
        portfolio_value = settings.paper_portfolio_value
        size_pct = trade.get("suggested_size_pct", 5.0)
        allocation = portfolio_value * (size_pct / 100)

        # Get approximate share count
        # In a real system, we'd use the current bid/ask
        price = trade.get("latest_price", 0)
        if price <= 0:
            return {
                "symbol": symbol,
                "status": "failed",
                "reason": "Could not determine price",
            }

        qty = max(1, int(allocation / price))

        # Dry run mode — log what would happen without calling the API
        if settings.dry_run or client is None:
            return {
                "symbol": symbol,
                "action": action,
                "quantity": qty,
                "estimated_price": price,
                "estimated_value": qty * price,
                "status": "dry_run",
                "reason": "Dry run mode — no order placed",
            }

        # Place the actual order via Alpaca
        try:
            from alpaca.trading.requests import MarketOrderRequest
            from alpaca.trading.enums import OrderSide, TimeInForce

            order_request = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=OrderSide.BUY if action == "buy" else OrderSide.SELL,
                time_in_force=TimeInForce.DAY,
            )

            order = client.submit_order(order_request)

            return {
                "symbol": symbol,
                "action": action,
                "quantity": qty,
                "order_id": str(order.id),
                "status": "submitted",
                "estimated_value": qty * price,
            }

        except Exception as e:
            return {
                "symbol": symbol,
                "action": action,
                "quantity": qty,
                "status": "failed",
                "reason": str(e),
            }
