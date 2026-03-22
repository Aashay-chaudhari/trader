"""Tests for cold-start knowledge initialization."""

import json
import tempfile
from pathlib import Path

from agent_trader.utils.knowledge_base import KnowledgeBase


def test_ensure_cold_start_creates_missing_files():
    """ensure_cold_start_schemas() creates all knowledge files if missing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        kb = KnowledgeBase(tmpdir)
        kb.ensure_cold_start_schemas()

        expected = [
            "lessons_learned.json",
            "patterns_library.json",
            "strategy_effectiveness.json",
            "regime_library.json",
        ]
        for filename in expected:
            path = Path(tmpdir) / "knowledge" / filename
            assert path.exists(), f"Missing: {filename}"
            data = json.loads(path.read_text())
            assert data is not None


def test_ensure_cold_start_does_not_overwrite_existing():
    """ensure_cold_start_schemas() must not clobber existing files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        kb = KnowledgeBase(tmpdir)
        # Pre-populate with real data
        lessons_path = Path(tmpdir) / "knowledge" / "lessons_learned.json"
        lessons_path.parent.mkdir(parents=True, exist_ok=True)
        lessons_path.write_text(json.dumps({"lessons": ["my lesson"], "last_updated": "2026-01-01"}))

        kb.ensure_cold_start_schemas()

        loaded = json.loads(lessons_path.read_text())
        assert loaded["lessons"] == ["my lesson"], "Should not overwrite existing lessons"


def test_build_knowledge_context_empty_returns_empty():
    """build_knowledge_context() handles empty cold-start schemas gracefully."""
    with tempfile.TemporaryDirectory() as tmpdir:
        kb = KnowledgeBase(tmpdir)
        kb.ensure_cold_start_schemas()
        ctx = kb.build_knowledge_context(token_budget=1500)
        assert isinstance(ctx, str)


def test_build_observations_context_empty():
    """build_observations_context() handles no observations gracefully."""
    with tempfile.TemporaryDirectory() as tmpdir:
        kb = KnowledgeBase(tmpdir)
        ctx = kb.build_observations_context(token_budget=500)
        assert isinstance(ctx, str)


def test_lessons_learned_bare_list_handled():
    """Legacy bare list format in lessons_learned.json does not crash summarizer."""
    with tempfile.TemporaryDirectory() as tmpdir:
        kb = KnowledgeBase(tmpdir)
        # Write legacy bare-list format
        lessons_path = Path(tmpdir) / "knowledge" / "lessons_learned.json"
        lessons_path.parent.mkdir(parents=True, exist_ok=True)
        lessons_path.write_text(json.dumps(["legacy lesson 1", "legacy lesson 2"]))

        ctx = kb.build_knowledge_context(token_budget=1500)
        assert isinstance(ctx, str)
