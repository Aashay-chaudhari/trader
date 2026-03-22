"""Tests for the evolution phase and improved proposal schema."""

import json
import pytest
import tempfile
from pathlib import Path

from agent_trader.utils.improvement_log import (
    append_improvement_proposals,
    save_evolution_proposals,
    get_evolution_summary,
    get_pending_proposals,
)


def test_append_proposals_stamps_status():
    """append_improvement_proposals stamps status=pending and created_date."""
    with tempfile.TemporaryDirectory() as tmpdir:
        proposals = [
            {
                "category": "strategy",
                "priority": "high",
                "title": "Test proposal",
                "description": "Test",
                "expected_impact": "Better win rate",
            }
        ]
        append_improvement_proposals(proposals, data_dir=tmpdir, date="2026-03-22")

        json_path = Path(tmpdir) / "improvement_proposals.json"
        data = json.loads(json_path.read_text())
        assert len(data) == 1
        p = data[0]["proposals"][0]
        assert p["status"] == "pending"
        assert p["created_date"] == "2026-03-22"


def test_evolution_proposals_with_implementation_hint():
    """save_evolution_proposals saves enriched proposals and creates EVOLUTION_REPORT.md."""
    with tempfile.TemporaryDirectory() as tmpdir:
        proposals = [
            {
                "category": "threshold",
                "priority": "high",
                "title": "Reduce RSI threshold",
                "description": "RSI 35 fires too often in risk_off",
                "expected_impact": "Reduce false signals ~20%",
                "implementation_hint": {
                    "file": "src/agent_trader/agents/strategy_agent.py",
                    "function": "_check_momentum",
                    "current_value": "rsi < 35",
                    "proposed_value": "rsi < 25",
                    "type": "threshold_adjustment",
                },
                "evidence": {
                    "sample_size": 12,
                    "win_rate_current": 0.33,
                    "dates": ["2026-03-19"],
                },
            }
        ]
        save_evolution_proposals(proposals, data_dir=tmpdir, date="2026-03-22")

        json_path = Path(tmpdir) / "improvement_proposals.json"
        assert json_path.exists()

        report_path = Path(tmpdir) / "EVOLUTION_REPORT.md"
        assert report_path.exists()
        content = report_path.read_text()
        assert "Reduce RSI threshold" in content
        assert "_check_momentum" in content
        assert "rsi < 35" in content


def test_get_evolution_summary_counts():
    """get_evolution_summary returns correct counts."""
    with tempfile.TemporaryDirectory() as tmpdir:
        proposals = [
            {"category": "strategy", "priority": "high", "title": "A"},
            {"category": "data_source", "priority": "high", "title": "B"},
            {"category": "infrastructure", "priority": "low", "title": "C"},
        ]
        append_improvement_proposals(proposals, data_dir=tmpdir, date="2026-03-22")

        summary = get_evolution_summary(tmpdir)
        assert summary["total"] == 3
        assert summary["high_priority_count"] == 2
        assert "strategy" in summary["by_category"]


def test_get_pending_proposals_filter_by_priority():
    """get_pending_proposals correctly filters by min_priority."""
    with tempfile.TemporaryDirectory() as tmpdir:
        proposals = [
            {"category": "strategy", "priority": "high", "title": "High"},
            {"category": "strategy", "priority": "low", "title": "Low"},
        ]
        append_improvement_proposals(proposals, data_dir=tmpdir, date="2026-03-22")

        high_only = get_pending_proposals(tmpdir, min_priority="high")
        assert all(p["priority"] == "high" for p in high_only)
        assert len(high_only) == 1

        all_proposals = get_pending_proposals(tmpdir, min_priority="low")
        assert len(all_proposals) == 2


def test_proposals_backward_compat_no_hint():
    """Old proposals without implementation_hint still load fine."""
    with tempfile.TemporaryDirectory() as tmpdir:
        json_path = Path(tmpdir) / "improvement_proposals.json"
        json_path.write_text(json.dumps([
            {"date": "2026-03-01", "proposals": [
                {"category": "other", "priority": "medium", "title": "Old style"}
            ]}
        ]))

        pending = get_pending_proposals(tmpdir)
        assert len(pending) == 1
        assert pending[0]["title"] == "Old style"
        assert "implementation_hint" not in pending[0]
