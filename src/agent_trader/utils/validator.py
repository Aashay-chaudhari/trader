"""Validation pipeline — structural integrity checks for the trading system.

Run after implementing code changes from evolution proposals:
  python -m agent_trader validate          # Schema + structure checks
  python -m agent_trader validate --smoke  # + debug-mode smoke tests

Checks:
  1. Knowledge file schemas
  2. Prompt template placeholders
  3. Strategy agent methods
  4. Profile directory structure
  5. Agent module imports
  6. (--smoke) Full debug pipeline end-to-end
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import re
import traceback
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from agent_trader.config.settings import get_settings

console = Console()

# ── Expected schema shapes ──────────────────────────────────────


KNOWLEDGE_SCHEMAS: dict[str, dict[str, Any]] = {
    "lessons_learned.json": {
        "accepted_shapes": ("lessons_list", "lessons_dict"),
    },
    "patterns_library.json": {
        "accepted_shapes": ("patterns_list", "patterns_dict"),
    },
    "strategy_effectiveness.json": {
        "accepted_shapes": ("strategy_effectiveness",),
    },
    "regime_library.json": {
        "accepted_shapes": ("regime_library",),
    },
}

PROMPT_PLACEHOLDERS: dict[str, list[str]] = {
    "RESEARCH_PROMPT": [
        "performance_feedback", "learned_rules", "artifact_context",
        "knowledge_context", "observations_context", "swing_context",
        "market_context", "market_data", "news_context", "screener_context",
    ],
    "MONITOR_PROMPT": [
        "morning_plans", "current_state", "active_positions", "strategy_signals",
    ],
    "EVENING_REFLECTION_PROMPT": [
        "todays_trades", "market_regime_summary", "active_positions",
        "recent_observations", "today_date",
    ],
    "WEEKLY_CONSOLIDATION_PROMPT": [
        "performance_summary", "daily_observations", "current_knowledge",
        "trade_details", "week_start", "week_end",
    ],
    "MONTHLY_RETROSPECTIVE_PROMPT": [
        "performance_summary", "weekly_reviews", "current_knowledge", "month",
    ],
    "EVOLUTION_PROMPT": [
        "performance_summary", "strategy_effectiveness", "recent_observations",
        "strategy_list", "pending_proposals",
    ],
}

EXPECTED_STRATEGY_METHODS = [
    "_momentum_strategy",
    "_mean_reversion_strategy",
    "_trend_following_strategy",
    "_volume_breakout_strategy",
    "_support_resistance_strategy",
    "_vwap_strategy",
    "_relative_strength_strategy",
    "_news_catalyst_strategy",
]

REQUIRED_PROFILE_SUBDIRS = [
    "knowledge",
    "observations/daily",
    "observations/weekly",
    "observations/monthly",
    "positions/active",
    "positions/closed",
    "cache",
]

AGENT_MODULES = [
    "agent_trader.agents.data_agent",
    "agent_trader.agents.execution_agent",
    "agent_trader.agents.news_agent",
    "agent_trader.agents.research_agent",
    "agent_trader.agents.risk_agent",
    "agent_trader.agents.screener_agent",
    "agent_trader.agents.strategy_agent",
    "agent_trader.utils.knowledge_base",
    "agent_trader.utils.improvement_log",
    "agent_trader.utils.validator",
    "agent_trader.runner",
]


# ── Individual checks ────────────────────────────────────────────


def check_knowledge_schemas(data_dir: str) -> list[tuple[bool, str]]:
    """Verify all knowledge JSON files exist and match expected schemas."""
    results = []
    knowledge_dir = Path(data_dir) / "knowledge"

    for filename, schema in KNOWLEDGE_SCHEMAS.items():
        path = knowledge_dir / filename
        if not path.exists():
            results.append((False, f"Missing: {path}"))
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, OSError) as e:
            results.append((False, f"Invalid JSON in {filename}: {e}"))
            continue

        if _matches_knowledge_schema(filename, data, schema):
            results.append((True, f"Schema OK: {filename}"))
        else:
            results.append((False, f"{filename}: schema mismatch"))

    return results


def check_prompt_placeholders() -> list[tuple[bool, str]]:
    """Verify all expected placeholders exist in each prompt template."""
    results = []
    try:
        import agent_trader.agents.research_agent as ra
    except ImportError as e:
        return [(False, f"Cannot import research_agent: {e}")]

    for template_name, placeholders in PROMPT_PLACEHOLDERS.items():
        template = getattr(ra, template_name, None)
        if template is None:
            results.append((False, f"Missing template: {template_name}"))
            continue
        missing = [p for p in placeholders if f"{{{p}}}" not in template]
        if missing:
            results.append((False, f"{template_name}: missing placeholders: {missing}"))
        else:
            results.append((True, f"Placeholders OK: {template_name}"))

    return results


def check_strategy_methods() -> list[tuple[bool, str]]:
    """Verify all expected strategy methods exist on StrategyAgent."""
    results = []
    try:
        from agent_trader.agents.strategy_agent import StrategyAgent
    except ImportError as e:
        return [(False, f"Cannot import StrategyAgent: {e}")]

    for method in EXPECTED_STRATEGY_METHODS:
        if hasattr(StrategyAgent, method) and callable(getattr(StrategyAgent, method)):
            results.append((True, f"Strategy method OK: {method}"))
        else:
            results.append((False, f"Missing strategy method: {method}"))

    return results


def check_profile_structure(data_dir: str) -> list[tuple[bool, str]]:
    """Verify required subdirectories exist in the profile data dir."""
    results = []
    root = Path(data_dir)
    for subdir in REQUIRED_PROFILE_SUBDIRS:
        path = root / subdir
        if path.exists() and path.is_dir():
            results.append((True, f"Dir OK: {subdir}"))
        else:
            results.append((False, f"Missing dir: {data_dir}/{subdir}"))
    return results


def check_imports() -> list[tuple[bool, str]]:
    """Verify all agent modules import without error."""
    results = []
    for module in AGENT_MODULES:
        try:
            importlib.import_module(module)
            results.append((True, f"Import OK: {module}"))
        except Exception as e:
            results.append((False, f"Import failed: {module} — {e}"))
    return results


async def _smoke_phase(phase_cmd: list[str]) -> tuple[bool, str]:
    """Run a single CLI phase in debug mode and check for errors."""
    import subprocess
    import sys
    env_patch = {"RUN_MODE": "debug", "DEBUG_MODE": "true"}
    import os
    env = {**os.environ, **env_patch}
    try:
        result = subprocess.run(
            [sys.executable, "-m", "agent_trader"] + phase_cmd,
            capture_output=True, text=True, timeout=120, env=env
        )
        if result.returncode == 0:
            return True, f"Smoke OK: {' '.join(phase_cmd)}"
        return False, f"Smoke FAILED: {' '.join(phase_cmd)}\n{result.stderr[-500:]}"
    except Exception as e:
        return False, f"Smoke ERROR: {' '.join(phase_cmd)} — {e}"


async def run_smoke_tests() -> list[tuple[bool, str]]:
    """Run each pipeline phase in debug mode."""
    phases = [
        ["research"],
        ["monitor"],
        ["reflect"],
        ["weekly"],
        ["monthly"],
        ["evolve"],
    ]
    tasks = [_smoke_phase(p) for p in phases]
    return list(await asyncio.gather(*tasks))


# ── Main validator ───────────────────────────────────────────────


def run_validation(smoke: bool = False, data_dir: str | None = None) -> dict[str, Any]:
    """Run all validation checks and return a structured report."""
    from agent_trader.config.settings import reset_settings
    reset_settings()
    settings = get_settings()
    effective_data_dir = data_dir or settings.data_dir

    all_results: list[tuple[bool, str]] = []

    console.print("\n[bold]Agent Trader — Validation[/bold]\n")

    sections = [
        ("Knowledge Schemas", check_knowledge_schemas(effective_data_dir)),
        ("Prompt Templates", check_prompt_placeholders()),
        ("Strategy Methods", check_strategy_methods()),
        ("Profile Structure", check_profile_structure(effective_data_dir)),
        ("Agent Imports", check_imports()),
    ]

    if smoke:
        console.print("[yellow]Running smoke tests (this takes ~60s)...[/yellow]")
        smoke_results = asyncio.run(run_smoke_tests())
        sections.append(("Smoke Tests", smoke_results))

    table = Table(title="Validation Results", show_lines=True)
    table.add_column("Check", style="dim")
    table.add_column("Result")
    table.add_column("Detail")

    pass_count = 0
    fail_count = 0

    for section_name, results in sections:
        table.add_row(f"[bold]{section_name}[/bold]", "", "")
        for passed, detail in results:
            icon = "[green]PASS[/green]" if passed else "[red]FAIL[/red]"
            table.add_row("", icon, detail)
            all_results.append((passed, detail))
            if passed:
                pass_count += 1
            else:
                fail_count += 1

    console.print(table)
    console.print(f"\n[bold]Total: {pass_count} passed, {fail_count} failed[/bold]")

    # Save report
    report = {
        "data_dir": effective_data_dir,
        "smoke_tests": smoke,
        "total_checks": pass_count + fail_count,
        "passed": pass_count,
        "failed": fail_count,
        "results": [{"passed": p, "detail": d} for p, d in all_results],
    }
    report_path = Path(effective_data_dir) / "validation_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2))
    console.print(f"[dim]Report saved: {report_path}[/dim]\n")

    return report


def _matches_knowledge_schema(filename: str, data: Any, schema: dict[str, Any]) -> bool:
    """Accept both cold-start and prompt-managed knowledge-file shapes."""
    shapes = schema.get("accepted_shapes", ())

    if filename == "lessons_learned.json":
        return (
            "lessons_list" in shapes and isinstance(data, list)
        ) or (
            "lessons_dict" in shapes
            and isinstance(data, dict)
            and isinstance(data.get("lessons"), list)
        )

    if filename == "patterns_library.json":
        return (
            "patterns_list" in shapes and isinstance(data, list)
        ) or (
            "patterns_dict" in shapes
            and isinstance(data, dict)
            and isinstance(data.get("patterns"), list)
        )

    if filename == "strategy_effectiveness.json":
        return (
            isinstance(data, dict)
            and "last_updated" in data
            and (
                isinstance(data.get("by_regime"), dict)
                or any(
                    isinstance(value, dict)
                    for key, value in data.items()
                    if key != "last_updated"
                )
            )
        )

    if filename == "regime_library.json":
        if not isinstance(data, dict):
            return False
        if all(key in data for key in ("risk_on", "risk_off", "neutral")):
            return True
        regimes = data.get("regimes")
        return isinstance(regimes, dict) and all(
            key in regimes for key in ("risk_on", "risk_off", "neutral")
        )

    return False
