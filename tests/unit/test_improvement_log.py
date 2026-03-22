"""Tests for the improvement log — self-improvement proposal persistence."""

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from agent_trader.utils.improvement_log import (
    append_improvement_proposals,
    get_pending_proposals,
)


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp(prefix="imp_log_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


SAMPLE_PROPOSALS = [
    {
        "category": "data_source",
        "priority": "high",
        "title": "Add options flow data",
        "description": "Integrate unusual options activity as a signal.",
        "expected_impact": "Better catch institutional positioning shifts.",
    },
    {
        "category": "strategy",
        "priority": "medium",
        "title": "Fade gap-ups above 3%",
        "description": "Mean reversion on large gap-ups has been profitable in back-tests.",
        "expected_impact": "Increase win rate by ~5%.",
    },
]


class TestAppendProposals:
    def test_creates_markdown_file(self, tmp_dir):
        path = append_improvement_proposals(SAMPLE_PROPOSALS, data_dir=tmp_dir, profile_id="claude")
        assert path.exists()
        assert path.suffix == ".md"

    def test_markdown_contains_proposals(self, tmp_dir):
        append_improvement_proposals(SAMPLE_PROPOSALS, data_dir=tmp_dir, profile_id="claude")
        content = (Path(tmp_dir) / "IMPROVEMENT_PROPOSALS.md").read_text()
        assert "Add options flow data" in content
        assert "Fade gap-ups above 3%" in content

    def test_priority_badges_present(self, tmp_dir):
        append_improvement_proposals(SAMPLE_PROPOSALS, data_dir=tmp_dir, profile_id="claude")
        content = (Path(tmp_dir) / "IMPROVEMENT_PROPOSALS.md").read_text()
        assert "[HIGH]" in content
        assert "[MED]" in content

    def test_profile_header_written(self, tmp_dir):
        append_improvement_proposals(SAMPLE_PROPOSALS, data_dir=tmp_dir, profile_id="claude")
        content = (Path(tmp_dir) / "IMPROVEMENT_PROPOSALS.md").read_text()
        assert "claude Strategist" in content

    def test_second_call_prepends_new_section(self, tmp_dir):
        append_improvement_proposals(
            [SAMPLE_PROPOSALS[0]], data_dir=tmp_dir, date="2026-03-20"
        )
        append_improvement_proposals(
            [SAMPLE_PROPOSALS[1]], data_dir=tmp_dir, date="2026-03-21"
        )
        content = (Path(tmp_dir) / "IMPROVEMENT_PROPOSALS.md").read_text()
        # Most recent date should appear before the older date
        idx_new = content.index("2026-03-21")
        idx_old = content.index("2026-03-20")
        assert idx_new < idx_old

    def test_header_not_duplicated_on_second_call(self, tmp_dir):
        for _ in range(3):
            append_improvement_proposals(SAMPLE_PROPOSALS, data_dir=tmp_dir)
        content = (Path(tmp_dir) / "IMPROVEMENT_PROPOSALS.md").read_text()
        assert content.count("# Improvement Proposals") == 1

    def test_empty_proposals_returns_path_without_writing(self, tmp_dir):
        path = append_improvement_proposals([], data_dir=tmp_dir)
        assert not path.exists()

    def test_also_writes_json(self, tmp_dir):
        append_improvement_proposals(SAMPLE_PROPOSALS, data_dir=tmp_dir)
        json_path = Path(tmp_dir) / "improvement_proposals.json"
        assert json_path.exists()
        entries = json.loads(json_path.read_text())
        assert len(entries) == 1
        assert len(entries[0]["proposals"]) == 2

    def test_json_appends_across_days(self, tmp_dir):
        append_improvement_proposals([SAMPLE_PROPOSALS[0]], data_dir=tmp_dir, date="2026-03-20")
        append_improvement_proposals([SAMPLE_PROPOSALS[1]], data_dir=tmp_dir, date="2026-03-21")
        json_path = Path(tmp_dir) / "improvement_proposals.json"
        entries = json.loads(json_path.read_text())
        assert len(entries) == 2
        assert entries[0]["date"] == "2026-03-20"
        assert entries[1]["date"] == "2026-03-21"


class TestGetPendingProposals:
    def test_returns_empty_when_no_file(self, tmp_dir):
        assert get_pending_proposals(tmp_dir) == []

    def test_returns_all_proposals(self, tmp_dir):
        append_improvement_proposals(SAMPLE_PROPOSALS, data_dir=tmp_dir, date="2026-03-21")
        proposals = get_pending_proposals(tmp_dir)
        assert len(proposals) == 2

    def test_filters_by_min_priority(self, tmp_dir):
        append_improvement_proposals(SAMPLE_PROPOSALS, data_dir=tmp_dir)
        high_only = get_pending_proposals(tmp_dir, min_priority="high")
        assert len(high_only) == 1
        assert high_only[0]["priority"] == "high"

    def test_filters_by_category(self, tmp_dir):
        append_improvement_proposals(SAMPLE_PROPOSALS, data_dir=tmp_dir)
        strategy_only = get_pending_proposals(tmp_dir, category="strategy")
        assert len(strategy_only) == 1
        assert strategy_only[0]["category"] == "strategy"

    def test_proposals_include_date(self, tmp_dir):
        append_improvement_proposals(SAMPLE_PROPOSALS, data_dir=tmp_dir, date="2026-03-21")
        proposals = get_pending_proposals(tmp_dir)
        assert all(p["date"] == "2026-03-21" for p in proposals)
