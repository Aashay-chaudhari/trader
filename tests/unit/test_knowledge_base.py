"""Unit tests for KnowledgeBase — knowledge accumulation layer."""

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from agent_trader.utils.knowledge_base import KnowledgeBase


@pytest.fixture
def kb():
    """Create a KnowledgeBase with a temporary data directory."""
    d = tempfile.mkdtemp(prefix="kb_test_")
    yield KnowledgeBase(d)
    shutil.rmtree(d, ignore_errors=True)


class TestDailyObservations:
    def test_save_and_load(self, kb):
        obs = {
            "date": "2026-03-21",
            "market_regime": "risk_on",
            "market_summary": "Tech led rally",
            "lessons": ["Momentum worked today"],
        }
        path = kb.save_daily_observation(obs)
        assert path.exists()
        assert "obs_2026-03-21" in path.name

        recent = kb.get_recent_observations(days=1)
        assert len(recent) == 1
        assert recent[0]["date"] == "2026-03-21"

    def test_multiple_days_newest_first(self, kb):
        for i in range(5):
            kb.save_daily_observation({"date": f"2026-03-{20+i:02d}", "market_regime": "risk_on"})

        recent = kb.get_recent_observations(days=3)
        assert len(recent) == 3
        assert recent[0]["date"] == "2026-03-24"
        assert recent[2]["date"] == "2026-03-22"

    def test_empty_observations(self, kb):
        assert kb.get_recent_observations() == []


class TestWeeklyReviews:
    def test_save_and_load(self, kb):
        review = {
            "week_start": "2026-03-17",
            "week_end": "2026-03-21",
            "summary": {"trades_count": 10, "win_rate": 0.7},
            "forward_thesis": {"outlook": "Risk-on continues", "confidence": 0.75},
        }
        path = kb.save_weekly_review(review)
        assert path.exists()

        latest = kb.get_latest_weekly_review()
        assert latest["week_start"] == "2026-03-17"

    def test_no_reviews(self, kb):
        assert kb.get_latest_weekly_review() is None


class TestMonthlyReviews:
    def test_save_and_load(self, kb):
        review = {
            "month": "2026-03",
            "summary": {"total_trades": 72, "win_rate": 0.68},
            "top_lessons": ["Momentum is best in risk-on"],
        }
        path = kb.save_monthly_review(review)
        assert path.exists()

        latest = kb.get_latest_monthly_review()
        assert latest["month"] == "2026-03"

    def test_lessons_saved_from_monthly(self, kb):
        kb.save_monthly_review({
            "month": "2026-03",
            "top_lessons": ["Lesson A", "Lesson B"],
        })
        # Lessons should be persisted to knowledge base
        path = kb.knowledge_dir / "lessons_learned.json"
        assert path.exists()
        data = json.loads(path.read_text())
        lessons = data if isinstance(data, list) else data["lessons"]
        assert "Lesson A" in lessons


class TestPatternsLibrary:
    def test_add_new_pattern(self, kb):
        kb.update_patterns_library([{
            "name": "gap_and_go",
            "occurrences": 5,
            "win_rate": 0.8,
            "symbols_seen": ["TSLA"],
        }])
        path = kb.knowledge_dir / "patterns_library.json"
        data = json.loads(path.read_text())
        patterns = data if isinstance(data, list) else data["patterns"]
        assert len(patterns) == 1
        assert patterns[0]["name"] == "gap_and_go"

    def test_merge_existing_pattern(self, kb):
        kb.update_patterns_library([{
            "name": "gap_and_go",
            "occurrences": 5,
            "win_rate": 0.8,
            "symbols_seen": ["TSLA"],
        }])
        kb.update_patterns_library([{
            "name": "gap_and_go",
            "occurrences": 3,
            "win_rate": 0.6,
            "symbols_seen": ["NVDA"],
        }])
        data = json.loads((kb.knowledge_dir / "patterns_library.json").read_text())
        patterns = data if isinstance(data, list) else data["patterns"]
        assert len(patterns) == 1
        p = patterns[0]
        assert p["total_occurrences"] == 8
        assert 0.7 < p["win_rate"] < 0.75  # Weighted average
        assert "TSLA" in p["symbols_seen"]
        assert "NVDA" in p["symbols_seen"]

    def test_max_100_patterns(self, kb):
        patterns = [{"name": f"pattern_{i}", "occurrences": 1, "win_rate": 0.5}
                    for i in range(120)]
        kb.update_patterns_library(patterns)
        data = json.loads((kb.knowledge_dir / "patterns_library.json").read_text())
        stored = data if isinstance(data, list) else data["patterns"]
        assert len(stored) == 100

    def test_update_patterns_preserves_prompt_managed_list_shape(self, kb):
        path = kb.knowledge_dir / "patterns_library.json"
        path.write_text(json.dumps([]), encoding="utf-8")

        kb.update_patterns_library([{
            "name": "oil_shock_equity_drawdown",
            "occurrences": 1,
            "win_rate": 0.5,
        }])

        data = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(data, list)
        assert data[0]["name"] == "oil_shock_equity_drawdown"


class TestLessonsLearned:
    def test_add_lessons(self, kb):
        kb.update_lessons_learned(["Lesson 1", "Lesson 2"])
        data = json.loads((kb.knowledge_dir / "lessons_learned.json").read_text())
        lessons = data if isinstance(data, list) else data["lessons"]
        assert len(lessons) == 2

    def test_deduplication(self, kb):
        kb.update_lessons_learned(["Same lesson"])
        kb.update_lessons_learned(["Same lesson"])
        data = json.loads((kb.knowledge_dir / "lessons_learned.json").read_text())
        lessons = data if isinstance(data, list) else data["lessons"]
        assert len(lessons) == 1

    def test_max_50_lessons(self, kb):
        for i in range(60):
            kb.update_lessons_learned([f"Lesson {i}"])
        data = json.loads((kb.knowledge_dir / "lessons_learned.json").read_text())
        lessons = data if isinstance(data, list) else data["lessons"]
        assert len(lessons) == 50


class TestContextAssembly:
    def test_empty_knowledge_returns_empty(self, kb):
        assert kb.build_knowledge_context() == ""

    def test_empty_observations_returns_empty(self, kb):
        assert kb.build_observations_context() == ""

    def test_knowledge_context_with_data(self, kb):
        kb.update_lessons_learned(["Always set stops", "Avoid earnings"])
        kb.update_patterns_library([{
            "name": "gap_and_go", "occurrences": 10, "win_rate": 0.75,
            "symbols_seen": ["TSLA"],
        }])
        context = kb.build_knowledge_context(token_budget=500)
        assert "ACCUMULATED KNOWLEDGE" in context
        assert "LESSONS" in context

    def test_knowledge_context_supports_by_regime_strategy_shape(self, kb):
        (kb.knowledge_dir / "strategy_effectiveness.json").write_text(
            json.dumps({
                "last_updated": "2026-03-22",
                "by_regime": {
                    "risk_off": {
                        "relative_strength": {"win_rate": 0.57},
                        "mean_reversion": {"win_rate": 0.56},
                    }
                },
            }),
            encoding="utf-8",
        )

        context = kb.build_knowledge_context(
            token_budget=500,
            current_regime="risk_off",
        )

        assert "TOP STRATEGIES" in context
        assert "relative_strength" in context

    def test_knowledge_context_supports_flat_regime_library_shape(self, kb):
        (kb.knowledge_dir / "regime_library.json").write_text(
            json.dumps({
                "risk_on": {"rules": ["Ride trend"]},
                "risk_off": {"rules": ["Cut exposure fast"]},
                "neutral": {"rules": ["Trade smaller"]},
            }),
            encoding="utf-8",
        )

        context = kb.build_knowledge_context(
            token_budget=500,
            current_regime="risk_off",
        )

        assert "CURRENT REGIME RULES (risk_off)" in context
        assert "Cut exposure fast" in context

    def test_observations_context_with_data(self, kb):
        kb.save_daily_observation({
            "date": "2026-03-21",
            "market_regime": "risk_on",
            "market_summary": "Tech rally",
            "lessons": ["Momentum worked"],
        })
        context = kb.build_observations_context(token_budget=200)
        assert "RECENT DAILY OBSERVATIONS" in context
        assert "2026-03-21" in context


class TestArchival:
    def test_archive_old_observations(self, kb):
        # Create an old observation
        old_path = kb.daily_dir / "obs_2025-01-15.json"
        old_path.write_text(json.dumps({"date": "2025-01-15", "market_regime": "risk_off"}))

        # Create a recent observation
        kb.save_daily_observation({"date": "2026-03-21", "market_regime": "risk_on"})

        archived = kb.archive_old_observations(keep_days=90)
        assert archived == 1
        assert not old_path.exists()
        assert list(kb.archive_dir.glob("*.json.gz"))
        # Recent file should still exist
        assert kb.get_recent_observations(days=1)[0]["date"] == "2026-03-21"
