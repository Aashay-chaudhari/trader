"""Helpers for recording LLM runtime telemetry."""

from __future__ import annotations

import json
import os
import platform as platform_lib
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def build_runtime_metadata() -> dict[str, Any]:
    """Collect runtime details for the current execution environment."""
    repo = os.getenv("GITHUB_REPOSITORY", "")
    run_id = os.getenv("GITHUB_RUN_ID", "")
    run_url = (
        f"https://github.com/{repo}/actions/runs/{run_id}"
        if repo and run_id
        else None
    )

    return {
        "platform": "github_actions" if os.getenv("GITHUB_ACTIONS") == "true" else "local",
        "python_version": sys.version.split()[0],
        "os": platform_lib.platform(),
        "github": {
            "repository": repo or None,
            "workflow": os.getenv("GITHUB_WORKFLOW") or None,
            "event_name": os.getenv("GITHUB_EVENT_NAME") or None,
            "actor": os.getenv("GITHUB_ACTOR") or None,
            "run_id": run_id or None,
            "run_attempt": os.getenv("GITHUB_RUN_ATTEMPT") or None,
            "run_url": run_url,
            "sha": os.getenv("GITHUB_SHA") or None,
            "ref": os.getenv("GITHUB_REF") or None,
        },
    }


def record_llm_analytics(
    *,
    phase: str,
    symbols: list[str],
    llm_meta: dict[str, Any],
    data_dir: str = "data",
) -> str:
    """Persist a normalized view of the latest LLM call telemetry."""
    root = Path(data_dir) / "analytics"
    llm_dir = root / "llm"
    llm_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    time_slug = now.strftime("%H-%M-%SZ")

    payload = {
        "timestamp": now.isoformat(),
        "phase": phase,
        "symbols": symbols,
        "provider_preference": llm_meta.get("provider_preference"),
        "selected_provider": llm_meta.get("provider"),
        "selected_model": llm_meta.get("model"),
        "status": llm_meta.get("status", "unknown"),
        "quota_issue_detected": llm_meta.get("quota_issue_detected", False),
        "quota_note": llm_meta.get("quota_note"),
        "usage": llm_meta.get("usage", {}),
        "rate_limits": llm_meta.get("rate_limits", {}),
        "service_tier": llm_meta.get("service_tier"),
        "request_id": llm_meta.get("request_id"),
        "duration_ms": llm_meta.get("duration_ms"),
        "attempts": llm_meta.get("attempts", []),
        "runtime": llm_meta.get("runtime", {}),
    }

    dated_dir = llm_dir / date_str
    dated_dir.mkdir(parents=True, exist_ok=True)
    detail_path = dated_dir / f"{time_slug}_{phase}_llm_usage.json"
    detail_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    daily_log = llm_dir / f"{date_str}.jsonl"
    with daily_log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, default=str) + "\n")

    (root / "latest_llm.json").write_text(
        json.dumps(payload, indent=2, default=str),
        encoding="utf-8",
    )

    return str(detail_path)
