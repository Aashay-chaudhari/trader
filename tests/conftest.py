"""Shared test fixtures."""

import pytest
from agent_trader.core.message_bus import MessageBus
from agent_trader.config.settings import reset_settings


@pytest.fixture(autouse=True)
def clean_settings():
    """Reset settings cache between tests."""
    reset_settings()
    yield
    reset_settings()


@pytest.fixture
def message_bus():
    return MessageBus()
