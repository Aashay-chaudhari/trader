"""Post-run check: report which analysis mode was used (template vs API).

Run as: python -m agent_trader.utils.check_mode
"""

from __future__ import annotations

import json
import os
from glob import glob
from pathlib import Path
from typing import Any

from agent_trader.config.settings import get_settings


def _mode_from_meta(meta: dict[str, Any]) -> str:
    execution_mode = str(meta.get("execution_mode", "")).strip().lower()
    if execution_mode in {"cli", "api", "none", "template"}:
        return execution_mode
    provider = str(meta.get("provider", "")).strip().lower()
    if provider.startswith("cli:"):
        return "cli"
    if provider.startswith("template:"):
        return "template"
    if provider:
        return "api"
    return "unknown"


def _format_attempt(attempt: dict[str, Any], index: int) -> str:
    mode = str(attempt.get("execution_mode", "")).strip().lower() or "unknown"
    provider = str(attempt.get("provider", "?"))
    model = str(attempt.get("model", "?"))
    status = str(attempt.get("status", "unknown"))
    duration = attempt.get("duration_ms")
    duration_text = f"{duration}ms" if duration is not None else "n/a"
    error = str(attempt.get("error", "")).strip()
    suffix = f" | {error[:140]}" if error else ""
    return (
        f"Attempt {index}: mode={mode} provider={provider} model={model} "
        f"status={status} duration={duration_text}{suffix}"
    )


def _write_github_summary(
    *,
    data_file: str,
    mode: str,
    provider: str,
    model: str,
    status: str,
    attempts: list[dict[str, Any]],
) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY", "").strip()
    if not summary_path:
        return

    lines = [
        "## Analysis Mode Report",
        "",
        f"- Data file: `{data_file}`",
        f"- Execution mode: `{mode}`",
        f"- Provider: `{provider}`",
        f"- Model: `{model}`",
        f"- Status: `{status}`",
    ]
    if attempts:
        lines.append("- Attempts:")
        for index, attempt in enumerate(attempts, start=1):
            lines.append(f"  - `{_format_attempt(attempt, index)}`")
    lines.append("")

    Path(summary_path).write_text("\n".join(lines), encoding="utf-8", errors="replace")


def main() -> None:
    settings = get_settings()
    data_root = Path(settings.data_dir)
    print("=" * 60)
    print("ANALYSIS MODE REPORT")
    print("=" * 60)
    print(f"RUN_MODE={os.environ.get('RUN_MODE', 'unset')}")
    print(f"LLM_PROVIDER={os.environ.get('LLM_PROVIDER', 'unset')}")
    print(f"DATA_DIR={settings.data_dir}")

    research_files = [Path(path) for path in glob(str(data_root / "research" / "*.json"))]
    research_files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    if not research_files:
        print("No research output files found.")
        print("=" * 60)
        return

    latest = str(research_files[0])
    print(f"Latest research: {latest}")

    try:
        payload = json.loads(Path(latest).read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"Could not parse latest research JSON: {exc}")
        print("=" * 60)
        return

    meta = payload.get("_meta", {}) if isinstance(payload, dict) else {}
    mode = _mode_from_meta(meta)
    provider = str(meta.get("provider", "unknown"))
    model = str(meta.get("model", "unknown"))
    status = str(meta.get("status", "unknown"))
    duration = meta.get("duration_ms")

    print(f"Execution Mode : {mode}")
    print(f"Provider       : {provider}")
    print(f"Model          : {model}")
    print(f"Status         : {status}")
    print(f"Duration       : {duration}ms" if duration is not None else "Duration       : n/a")

    attempts = meta.get("attempts", [])
    attempts_list = attempts if isinstance(attempts, list) else []
    if attempts_list:
        print("")
        print("Attempts:")
        for index, attempt in enumerate(attempts_list, start=1):
            if isinstance(attempt, dict):
                print(f"- {_format_attempt(attempt, index)}")

    if mode == "template":
        print("")
        print("TEMPLATE MODE CONFIRMED (NO MODEL TOKENS USED)")
    elif mode == "api":
        print("")
        print("DIRECT API MODE CONFIRMED")
    else:
        print("")
        print("MODE COULD NOT BE DETERMINED")

    _write_github_summary(
        data_file=latest,
        mode=mode,
        provider=provider,
        model=model,
        status=status,
        attempts=[a for a in attempts_list if isinstance(a, dict)],
    )

    print("=" * 60)


if __name__ == "__main__":
    main()
