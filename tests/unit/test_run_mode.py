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
    monkeypatch.delenv("PRODUCTION_MODE", raising=False)
    monkeypatch.setenv("DEBUG_MODE", "true")
    monkeypatch.setenv("DRY_RUN", "true")
    reset_settings()
    s = Settings()
    assert s.run_mode == "debug"
    assert s.is_debug is True
    assert s.is_dry_run is True


def test_run_mode_paper_via_env(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "paper")
    monkeypatch.delenv("PRODUCTION_MODE", raising=False)
    reset_settings()
    s = Settings()
    assert s.run_mode == "paper"
    assert s.is_debug is False
    assert s.is_dry_run is False  # paper places broker paper orders


def test_run_mode_production_mode_true(monkeypatch):
    monkeypatch.delenv("RUN_MODE", raising=False)
    monkeypatch.setenv("PRODUCTION_MODE", "true")
    reset_settings()
    s = Settings()
    assert s.run_mode == "paper"
    assert s.is_debug is False
    assert s.is_dry_run is False


def test_run_mode_debug_mode_false_maps_to_paper(monkeypatch):
    monkeypatch.delenv("RUN_MODE", raising=False)
    monkeypatch.delenv("PRODUCTION_MODE", raising=False)
    monkeypatch.setenv("DEBUG_MODE", "false")
    monkeypatch.setenv("DRY_RUN", "false")
    reset_settings()
    s = Settings()
    assert s.run_mode == "paper"
    assert s.is_debug is False


def test_run_mode_live(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "live")
    monkeypatch.delenv("PRODUCTION_MODE", raising=False)
    reset_settings()
    s = Settings()
    assert s.run_mode == "live"
    assert s.is_debug is False
    assert s.is_dry_run is False  # live = real orders


def test_legacy_dry_run_override_still_supported(monkeypatch):
    monkeypatch.delenv("RUN_MODE", raising=False)
    monkeypatch.delenv("PRODUCTION_MODE", raising=False)
    monkeypatch.setenv("DEBUG_MODE", "false")
    monkeypatch.setenv("DRY_RUN", "true")
    reset_settings()
    s = Settings()
    assert s.run_mode == "paper"
    assert s.is_dry_run is True


def test_max_stocks_debug(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "debug")
    reset_settings()
    s = Settings()
    assert s.max_stocks == 3  # debug_max_stocks default


def test_max_stocks_paper(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "paper")
    reset_settings()
    s = Settings()
    assert s.max_stocks == 0  # 0 = unlimited


def test_skip_web_debug(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "debug")
    reset_settings()
    s = Settings()
    assert s.skip_web is True


def test_skip_web_paper(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "paper")
    reset_settings()
    s = Settings()
    assert s.skip_web is False
