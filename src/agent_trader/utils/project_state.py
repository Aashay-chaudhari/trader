"""Helpers for clearing generated runtime state."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from agent_trader.config.settings import get_settings
from agent_trader.utils.profiles import build_profile_metadata


TOP_LEVEL_DATA_DIRS = (
    "analytics",
    "cache",
    "context",
    "feedback",
    "journal",
    "research",
    "snapshots",
    "staging",
)

# Dirs preserved when --keep-knowledge is used.
KNOWLEDGE_DIRS = (
    "knowledge",
    "observations",
    "positions",
    "voice",
)

TOP_LEVEL_DATA_FILES = (
    "portfolio_state.json",
    "profile.json",
)

# Files preserved when --keep-knowledge is used.
KNOWLEDGE_FILES = (
    "IMPROVEMENT_PROPOSALS.md",
    "improvement_proposals.json",
)


def reset_project_state(
    *,
    data_dir: str | None = None,
    docs_dir: str | None = None,
    all_profiles: bool = False,
    include_docs: bool = False,
    keep_knowledge: bool = False,
) -> dict[str, Any]:
    """Reset generated runtime state for one profile or the whole project.

    When *keep_knowledge* is True, knowledge/, observations/, positions/,
    and improvement-proposal files are preserved — only runtime artifacts
    (cache, journal, analytics, staging, context, snapshots) are cleared.
    """
    settings = get_settings()
    configured_root = Path(data_dir or settings.data_dir)
    base_data_root = _base_data_root(configured_root)
    removed: list[str] = []

    if all_profiles:
        _reset_top_level_data_root(base_data_root, removed)
        profiles_root = base_data_root / "profiles"
        if keep_knowledge:
            # Walk each profile and reset selectively.
            if profiles_root.exists():
                for profile_dir in profiles_root.iterdir():
                    if profile_dir.is_dir():
                        _reset_profile_root(profile_dir, removed, keep_knowledge=True)
                        _write_profile_metadata(profile_dir)
        else:
            _remove_path(profiles_root, removed)
    else:
        if _is_profile_root(configured_root):
            _reset_profile_root(configured_root, removed, keep_knowledge=keep_knowledge)
            _write_profile_metadata(configured_root)
        else:
            _reset_top_level_data_root(configured_root, removed)
            _write_profile_metadata(configured_root)

    if include_docs:
        _reset_docs_root(Path(docs_dir or "docs"), removed)

    return {
        "data_root": str(configured_root),
        "all_profiles": all_profiles,
        "keep_knowledge": keep_knowledge,
        "include_docs": include_docs,
        "removed": removed,
    }


def _base_data_root(root: Path) -> Path:
    if root.name == "profiles":
        return root.parent
    if root.parent.name == "profiles":
        return root.parent.parent
    return root


def _is_profile_root(root: Path) -> bool:
    return root.parent.name == "profiles"


def _reset_profile_root(
    root: Path, removed: list[str], *, keep_knowledge: bool = False,
) -> None:
    if root.exists():
        preserved = set(KNOWLEDGE_DIRS) | {f.split(".")[0] for f in KNOWLEDGE_FILES}
        for child in root.iterdir():
            if keep_knowledge and child.name in KNOWLEDGE_DIRS:
                continue
            if keep_knowledge and child.name in KNOWLEDGE_FILES:
                continue
            _remove_path(child, removed)
    root.mkdir(parents=True, exist_ok=True)


def _reset_top_level_data_root(root: Path, removed: list[str]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for name in TOP_LEVEL_DATA_DIRS:
        _remove_path(root / name, removed)
    for name in TOP_LEVEL_DATA_FILES:
        _remove_path(root / name, removed)
    for path in root.glob("news_collection_*.md"):
        _remove_path(path, removed)


def _reset_docs_root(root: Path, removed: list[str]) -> None:
    _remove_path(root / "data", removed)
    _remove_path(root / "index.html", removed)
    root.mkdir(parents=True, exist_ok=True)


def _remove_path(path: Path, removed: list[str]) -> None:
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    removed.append(path.as_posix())


def _write_profile_metadata(root: Path) -> None:
    settings = get_settings()
    payload = build_profile_metadata(settings)
    payload["data_dir"] = root.as_posix()
    root.mkdir(parents=True, exist_ok=True)
    (root / "profile.json").write_text(
        json.dumps(payload, indent=2, default=str),
        encoding="utf-8",
    )
