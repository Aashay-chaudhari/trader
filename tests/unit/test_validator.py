"""Tests for the validation pipeline."""

import json
import tempfile
from pathlib import Path

from agent_trader.utils.validator import (
    check_knowledge_schemas,
    check_prompt_placeholders,
    check_strategy_methods,
    check_profile_structure,
    check_imports,
)


def test_check_knowledge_schemas_all_missing():
    """All checks fail when knowledge files don't exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        results = check_knowledge_schemas(tmpdir)
        assert len(results) == 4  # one per file
        assert all(not passed for passed, _ in results)


def test_check_knowledge_schemas_all_valid():
    """All checks pass with valid cold-start schemas."""
    with tempfile.TemporaryDirectory() as tmpdir:
        from agent_trader.utils.knowledge_base import KnowledgeBase
        kb = KnowledgeBase(tmpdir)
        kb.ensure_cold_start_schemas()

        results = check_knowledge_schemas(tmpdir)
        failures = [(p, d) for p, d in results if not p]
        assert failures == [], f"Unexpected failures: {failures}"


def test_check_knowledge_schemas_prompt_managed_shapes():
    """Prompt-managed list/by-regime shapes are accepted."""
    with tempfile.TemporaryDirectory() as tmpdir:
        knowledge_dir = Path(tmpdir) / "knowledge"
        knowledge_dir.mkdir()
        (knowledge_dir / "lessons_learned.json").write_text(json.dumps(["lesson"]))
        (knowledge_dir / "patterns_library.json").write_text(json.dumps([{"name": "pattern"}]))
        (knowledge_dir / "strategy_effectiveness.json").write_text(json.dumps({
            "last_updated": "2026-03-22",
            "by_regime": {"risk_off": {"relative_strength": {"win_rate": 0.57}}},
        }))
        (knowledge_dir / "regime_library.json").write_text(json.dumps({
            "risk_on": {},
            "risk_off": {},
            "neutral": {},
        }))

        results = check_knowledge_schemas(tmpdir)
        failures = [(p, d) for p, d in results if not p]
        assert failures == [], f"Unexpected failures: {failures}"


def test_check_knowledge_schemas_invalid_json():
    """Corrupt JSON is detected and reported."""
    with tempfile.TemporaryDirectory() as tmpdir:
        knowledge_dir = Path(tmpdir) / "knowledge"
        knowledge_dir.mkdir()
        (knowledge_dir / "lessons_learned.json").write_text("NOT JSON {{}")

        results = check_knowledge_schemas(tmpdir)
        lessons_result = next((r for r in results if "lessons_learned" in r[1]), None)
        assert lessons_result is not None
        assert not lessons_result[0]  # should fail


def test_check_knowledge_schemas_handles_utf8_bom():
    """UTF-8 BOM from CLI-written JSON should not fail validation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        knowledge_dir = Path(tmpdir) / "knowledge"
        knowledge_dir.mkdir()
        (knowledge_dir / "lessons_learned.json").write_text(
            json.dumps(["lesson"]),
            encoding="utf-8-sig",
        )
        (knowledge_dir / "patterns_library.json").write_text(
            json.dumps([]),
            encoding="utf-8-sig",
        )
        (knowledge_dir / "strategy_effectiveness.json").write_text(
            json.dumps({"last_updated": "2026-03-22", "by_regime": {}}),
            encoding="utf-8-sig",
        )
        (knowledge_dir / "regime_library.json").write_text(
            json.dumps({"risk_on": {}, "risk_off": {}, "neutral": {}}),
            encoding="utf-8-sig",
        )

        results = check_knowledge_schemas(tmpdir)
        failures = [(p, d) for p, d in results if not p]
        assert failures == [], f"Unexpected failures: {failures}"


def test_check_prompt_placeholders_pass():
    """All prompt templates have their expected placeholders."""
    results = check_prompt_placeholders()
    failures = [(p, d) for p, d in results if not p]
    assert failures == [], f"Missing placeholders: {failures}"


def test_check_strategy_methods_pass():
    """All 8 strategy methods exist on StrategyAgent."""
    results = check_strategy_methods()
    failures = [(p, d) for p, d in results if not p]
    assert failures == [], f"Missing methods: {failures}"


def test_check_profile_structure_missing():
    """Checks fail when profile subdirs are missing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        results = check_profile_structure(tmpdir)
        assert any(not passed for passed, _ in results)


def test_check_profile_structure_pass():
    """All checks pass when required dirs exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        from agent_trader.utils.knowledge_base import KnowledgeBase
        kb = KnowledgeBase(tmpdir)
        for subdir in ["positions/active", "positions/closed", "cache", "journal"]:
            (Path(tmpdir) / subdir).mkdir(parents=True, exist_ok=True)

        results = check_profile_structure(tmpdir)
        failures = [(p, d) for p, d in results if not p]
        assert failures == [], f"Missing dirs: {failures}"


def test_check_imports_pass():
    """All agent modules import without errors."""
    results = check_imports()
    failures = [(p, d) for p, d in results if not p]
    assert failures == [], f"Import failures: {failures}"
