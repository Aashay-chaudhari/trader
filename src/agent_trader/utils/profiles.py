"""Helpers for profile-aware strategist runs."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from agent_trader.config.settings import Settings, get_settings


DEFAULT_PROFILE_LABELS = {
    "default": "Primary Strategist",
    "claude": "Claude Strategist",
    "codex": "Codex Strategist",
}


def normalize_profile_id(value: str | None) -> str:
    """Return a stable filesystem-safe profile identifier."""
    raw = (value or "default").strip().lower()
    normalized = re.sub(r"[^a-z0-9_-]+", "-", raw).strip("-")
    return normalized or "default"


def get_profile_id(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    return normalize_profile_id(settings.agent_profile)


def get_profile_label(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    if settings.agent_label.strip():
        return settings.agent_label.strip()
    return DEFAULT_PROFILE_LABELS.get(get_profile_id(settings), get_profile_id(settings).replace("-", " ").title())


def build_profile_metadata(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    profile_id = get_profile_id(settings)
    return {
        "id": profile_id,
        "label": get_profile_label(settings),
        "data_dir": settings.data_dir,
        "llm_provider": settings.llm_provider,
        "use_cli_agent": settings.use_cli_agent,
        "cli_agent_provider": settings.cli_agent_provider,
        "cli_agent_max_turns": settings.cli_agent_max_turns,
        "cli_agent_timeout": settings.cli_agent_timeout,
        "dry_run": settings.is_dry_run,
        "paper_portfolio_value": settings.paper_portfolio_value,
    }


def ensure_profile_metadata(settings: Settings | None = None) -> str:
    """Persist profile metadata alongside other strategist artifacts."""
    settings = settings or get_settings()
    root = Path(settings.data_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = root / "profile.json"
    path.write_text(
        json.dumps(build_profile_metadata(settings), indent=2, default=str),
        encoding="utf-8",
    )
    return str(path)
