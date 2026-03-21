"""Message bus for inter-agent communication.

Agents don't talk to each other directly. They publish messages to the bus,
and the orchestrator routes them. This makes the system:
  - Testable: you can inspect every message
  - Debuggable: full audit trail of what happened and when
  - Modular: agents don't know about each other
"""

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

from pydantic import BaseModel, Field


class MessageType(str, Enum):
    """What kind of message is this?"""

    # Orchestrator -> Agent
    COMMAND = "command"          # "go do your thing"

    # Agent -> Orchestrator
    RESULT = "result"           # "here's what I found"
    ERROR = "error"             # "something went wrong"

    # Agent -> Agent (via orchestrator)
    SIGNAL = "signal"           # trading signal from strategy agent
    TRADE_REQUEST = "trade_request"     # proposed trade needing risk approval
    TRADE_APPROVED = "trade_approved"   # risk agent approved the trade
    TRADE_REJECTED = "trade_rejected"   # risk agent rejected the trade
    TRADE_EXECUTED = "trade_executed"   # execution agent filled the order

    # System
    LOG = "log"                 # informational message for the audit trail


class Message(BaseModel):
    """A single message flowing through the system."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    type: MessageType
    source: str                 # which agent sent this
    data: Any                   # the payload (varies by message type)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    correlation_id: str | None = None  # links responses to their original request

    model_config = {"arbitrary_types_allowed": True}


class MessageBus:
    """Simple in-process message bus with history.

    Not a full pub/sub system — this is intentionally simple.
    The orchestrator drives the flow; the bus just records and routes.
    """

    def __init__(self):
        self._history: list[Message] = []
        self._subscribers: dict[MessageType, list[Callable]] = {}

    def publish(self, message: Message) -> None:
        """Record a message and notify any subscribers."""
        self._history.append(message)

        for callback in self._subscribers.get(message.type, []):
            callback(message)

    def subscribe(self, msg_type: MessageType, callback: Callable) -> None:
        """Register a callback for a specific message type."""
        self._subscribers.setdefault(msg_type, []).append(callback)

    @property
    def history(self) -> list[Message]:
        """Full ordered history of all messages."""
        return list(self._history)

    def get_by_correlation(self, correlation_id: str) -> list[Message]:
        """Get all messages related to a specific request."""
        return [m for m in self._history if m.correlation_id == correlation_id]

    def get_by_type(self, msg_type: MessageType) -> list[Message]:
        """Get all messages of a specific type."""
        return [m for m in self._history if m.type == msg_type]

    def get_errors(self) -> list[Message]:
        """Get all error messages — useful for debugging."""
        return self.get_by_type(MessageType.ERROR)

    def clear(self) -> None:
        """Reset history (useful between trading sessions)."""
        self._history.clear()

    def summary(self) -> dict[str, int]:
        """Quick count of messages by type — good for dashboards."""
        counts: dict[str, int] = {}
        for msg in self._history:
            counts[msg.type.value] = counts.get(msg.type.value, 0) + 1
        return counts
