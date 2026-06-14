"""Tests for the simplified run_mode control flow."""

import pytest
from agent_trader.config.settings import Settings, reset_settings


@pytest.fixture(autouse=True)
def clean():
    reset_settings()
    yield
    reset_settings()


def make_settings(**env_overrides):
    """Build a Settings instance with patched env vars (no .env file)."""
    # Pass values directly to avoid .env file interference
    return Settings(**env_overrides)


def test_run_mode_debug_is_default(monkeypatch):
    monkeypatch.delenv("RUN_MODE", raising=False)
    monkeypatch.delenv("MONITOR_RUNTIME", raising=False)
    reset_settings()
    s = Settings(_env_file=None)
    assert s.run_mode == "debug"
    assert s.monitor_runtime == "codex_loop"
    assert s.monitor_execution_owner == "github_actions"
    assert s.is_debug is True
    assert s.is_dry_run is True
    assert s.agent_profile == "codex"
    assert s.agent_label == "Codex Strategist"
    assert s.data_dir == "data/profiles/codex"


def test_monitor_runtime_can_use_github_actions_api(monkeypatch):
    monkeypatch.setenv("MONITOR_RUNTIME", "github_actions_api")
    reset_settings()
    s = Settings(_env_file=None)
    assert s.monitor_runtime == "github_actions_api"


def test_monitor_execution_owner_can_be_local(monkeypatch):
    monkeypatch.setenv("MONITOR_EXECUTION_OWNER", "local")
    reset_settings()
    s = Settings(_env_file=None)
    assert s.monitor_execution_owner == "local"


def test_run_mode_paper_via_env(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "paper")
    reset_settings()
    s = Settings(_env_file=None)
    assert s.run_mode == "paper"
    assert s.is_debug is False
    assert s.is_dry_run is False  # paper places broker paper orders


def test_run_mode_live(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "live")
    reset_settings()
    s = Settings(_env_file=None)
    assert s.run_mode == "live"
    assert s.is_debug is False
    assert s.is_dry_run is False  # live = real orders


def test_max_stocks_debug(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "debug")
    reset_settings()
    s = Settings(_env_file=None)
    assert s.max_stocks == 3


def test_max_stocks_paper(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "paper")
    reset_settings()
    s = Settings(_env_file=None)
    assert s.max_stocks == 0  # 0 = unlimited


def test_skip_web_debug(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "debug")
    reset_settings()
    s = Settings(_env_file=None)
    assert s.skip_web is True


def test_skip_web_paper(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "paper")
    reset_settings()
    s = Settings(_env_file=None)
    assert s.skip_web is False
