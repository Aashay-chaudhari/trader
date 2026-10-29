"""Shared test fixtures."""

import pytest
from agent_trader.core.message_bus import MessageBus
from agent_trader.config.settings import reset_settings


@pytest.fixture(autouse=True)
def clean_settings(monkeypatch, tmp_path):
    """Reset settings cache between tests."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "legacy-profile"))
    for key in ("ALPACA_API_KEY", "ALPACA_SECRET_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "NTFY_TOPIC"):
        monkeypatch.setenv(key, "")
    reset_settings()
    yield
    reset_settings()


@pytest.fixture
def message_bus():
    return MessageBus()
