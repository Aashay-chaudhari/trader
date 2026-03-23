"""Unit tests for SwingTracker — multi-day position management."""

import json
import shutil
import tempfile

import pytest

from agent_trader.utils.swing_tracker import SwingTracker


@pytest.fixture
def tracker():
    """Create a SwingTracker with a temporary data directory."""
    d = tempfile.mkdtemp(prefix="swing_test_")
    yield SwingTracker(d)
    shutil.rmtree(d, ignore_errors=True)


class TestOpenPosition:
    def test_open_creates_file(self, tracker):
        path = tracker.open_position(
            "NVDA", entry_price=128.50, quantity=78,
            stop_loss=126.50, target=135.00,
            reasoning="Breakout above 200-day MA",
            confidence=0.75,
        )
        assert path.exists()
        assert "NVDA" in path.name

        data = json.loads(path.read_text())
        assert data["symbol"] == "NVDA"
        assert data["entry_price"] == 128.50
        assert data["stop_loss"] == 126.50
        assert data["status"] == "active"
        assert data["daily_updates"] == []

    def test_get_active_positions(self, tracker):
        tracker.open_position("NVDA", 128.50, 78, 126.50, 135.00)
        tracker.open_position("AAPL", 185.00, 54, 182.00, 192.00)

        positions = tracker.get_active_positions()
        assert len(positions) == 2
        symbols = {p["symbol"] for p in positions}
        assert symbols == {"NVDA", "AAPL"}


class TestUpdatePosition:
    def test_daily_update(self, tracker):
        tracker.open_position("NVDA", 128.50, 78, 126.50, 135.00)

        result = tracker.update_position("NVDA", 130.00, notes="Holding, volume confirmed")
        assert result is not None
        assert len(result["daily_updates"]) == 1
        assert result["daily_updates"][0]["close"] == 130.00
        assert result["daily_updates"][0]["pnl_pct"] == pytest.approx(1.17, abs=0.01)

    def test_update_nonexistent_returns_none(self, tracker):
        assert tracker.update_position("FAKE", 100.00) is None


class TestClosePosition:
    def test_close_moves_to_closed(self, tracker):
        tracker.open_position("NVDA", 128.50, 78, 126.50, 135.00)
        result = tracker.close_position("NVDA", 134.00, reason="target_hit")

        assert result is not None
        assert result["pnl"] == pytest.approx(429.00, abs=0.01)
        assert result["pnl_pct"] == pytest.approx(4.28, abs=0.01)
        assert result["status"] == "closed"
        assert result["exit_reason"] == "target_hit"

        # Active should be empty now
        assert tracker.get_active_positions() == []
        # Closed should have one
        assert len(tracker.get_closed_positions()) == 1

    def test_close_nonexistent_returns_none(self, tracker):
        assert tracker.close_position("FAKE", 100.00) is None


class TestCheckStops:
    def test_stop_triggered(self, tracker):
        tracker.open_position("NVDA", 128.50, 78, 126.50, 135.00)

        triggered = tracker.check_stops({"NVDA": {"current_price": 126.00}})
        assert len(triggered) == 1
        assert triggered[0]["symbol"] == "NVDA"
        assert triggered[0]["stop_loss"] == 126.50

    def test_target_triggered(self, tracker):
        tracker.open_position("NVDA", 128.50, 78, 126.50, 135.00)

        triggered = tracker.check_stops({"NVDA": {"current_price": 136.00}})
        assert any(t.get("hit_target") for t in triggered)

    def test_no_trigger(self, tracker):
        tracker.open_position("NVDA", 128.50, 78, 126.50, 135.00)

        triggered = tracker.check_stops({"NVDA": {"current_price": 130.00}})
        assert triggered == []


class TestPromptSummary:
    def test_empty_returns_empty(self, tracker):
        assert tracker.get_summary_for_prompt() == ""

    def test_summary_with_positions(self, tracker):
        tracker.open_position(
            "NVDA", 128.50, 78, 126.50, 135.00,
            reasoning="Breakout play",
        )
        tracker.update_position("NVDA", 130.00, notes="Day 1")

        summary = tracker.get_summary_for_prompt()
        assert "ACTIVE SWING POSITIONS" in summary
        assert "NVDA" in summary
        assert "128.50" in summary


class TestGetPosition:
    def test_get_existing(self, tracker):
        tracker.open_position("NVDA", 128.50, 78, 126.50, 135.00)
        pos = tracker.get_position("NVDA")
        assert pos is not None
        assert pos["symbol"] == "NVDA"

    def test_get_nonexistent(self, tracker):
        assert tracker.get_position("FAKE") is None

    def test_case_insensitive(self, tracker):
        tracker.open_position("NVDA", 128.50, 78, 126.50, 135.00)
        pos = tracker.get_position("nvda")
        assert pos is not None
