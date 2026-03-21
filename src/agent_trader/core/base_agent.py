"""Base agent class that all trading agents inherit from.

Every agent in the system follows the same lifecycle:
  1. receive() - gets a message from the orchestrator
  2. process() - does its work (overridden by each agent)
  3. emit() - sends results back via the message bus

This keeps every agent testable in isolation and swappable.
"""

from abc import ABC, abstractmethod
from enum import Enum
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

from agent_trader.core.message_bus import MessageBus, Message, MessageType


class AgentRole(str, Enum):
    """Defines what each agent does in the system."""

    DATA = "data"               # Fetches market data
    RESEARCH = "research"       # Analyzes market conditions via LLM
    STRATEGY = "strategy"       # Generates buy/sell signals
    RISK = "risk"               # Validates trades against risk rules
    EXECUTION = "execution"     # Places trades via broker
    PORTFOLIO = "portfolio"     # Tracks positions and P&L


class AgentStatus(BaseModel):
    """Snapshot of an agent's current state — useful for debugging."""

    role: AgentRole
    last_run: datetime | None = None
    last_error: str | None = None
    run_count: int = 0
    is_healthy: bool = True


class BaseAgent(ABC):
    """Base class for all trading agents.

    Subclasses must implement:
      - process(message) -> Any : the agent's core logic
    """

    def __init__(self, role: AgentRole, message_bus: MessageBus):
        self.role = role
        self.bus = message_bus
        self._status = AgentStatus(role=role)

    @property
    def name(self) -> str:
        return f"{self.role.value}_agent"

    @property
    def status(self) -> AgentStatus:
        return self._status

    @abstractmethod
    async def process(self, message: Message) -> Any:
        """Core logic. Receives a message, returns a result.

        Each agent implements this differently:
          - DataAgent: fetches prices, returns DataFrame
          - ResearchAgent: calls LLM, returns analysis text
          - StrategyAgent: computes signals, returns trade recommendations
          - RiskAgent: validates trades, returns approved/rejected list
          - ExecutionAgent: places orders, returns fill confirmations
          - PortfolioAgent: updates positions, returns portfolio snapshot
        """
        ...

    async def receive(self, message: Message) -> Message | None:
        """Entry point called by the orchestrator. Wraps process() with
        error handling and status tracking."""
        try:
            self._status.last_run = datetime.now(timezone.utc)
            self._status.run_count += 1

            result = await self.process(message)

            # Wrap the result in a message and send it back
            response = Message(
                type=MessageType.RESULT,
                source=self.role,
                data=result,
                correlation_id=message.id,
            )
            self.bus.publish(response)
            self._status.is_healthy = True
            self._status.last_error = None
            return response

        except Exception as e:
            self._status.is_healthy = False
            self._status.last_error = str(e)

            error_msg = Message(
                type=MessageType.ERROR,
                source=self.role,
                data={"error": str(e), "agent": self.name},
                correlation_id=message.id,
            )
            self.bus.publish(error_msg)
            return error_msg

    def emit(self, msg_type: MessageType, data: Any) -> Message:
        """Convenience method for agents to emit messages mid-process."""
        msg = Message(type=msg_type, source=self.role, data=data)
        self.bus.publish(msg)
        return msg
