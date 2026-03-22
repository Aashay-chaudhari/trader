"""Helpers for persisting and reloading LLM context artifacts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def build_recent_artifact_summary(data_dir: str = "data", limit: int = 3) -> str:
    """Summarize recent saved research artifacts for future prompts."""
    root = Path(data_dir)
    lines: list[str] = []

    watchlist_path = root / "cache" / "watchlist.json"
    if watchlist_path.exists():
        try:
            watchlist = json.loads(watchlist_path.read_text(encoding="utf-8-sig"))
            if watchlist:
                lines.append("CACHED WATCHLIST FROM PRIOR RUN:")
                lines.append(f"  {', '.join(watchlist[:10])}")
        except json.JSONDecodeError:
            pass

    research_dir = root / "research"
    if research_dir.exists():
        history_files = sorted(research_dir.glob("*.json"), reverse=True)[:limit]
        history_lines: list[str] = []

        for file in history_files:
            try:
                payload = json.loads(file.read_text(encoding="utf-8-sig"))
            except json.JSONDecodeError:
                continue

            phase = "unknown"
            stem = file.stem
            if "_research_" in stem:
                phase = "research"
            elif "_monitor_" in stem:
                phase = "monitor"
            elif "_weekly_review_" in stem:
                phase = "weekly_review"

            best = payload.get("best_opportunities", [])[:3]
            regime = payload.get("market_regime", "unknown")
            sentiment = payload.get("overall_sentiment", "unknown")
            market_summary = str(payload.get("market_summary", "")).replace("\n", " ").strip()

            strong_calls = []
            for symbol, analysis in payload.get("stocks", {}).items():
                rec = analysis.get("recommendation", "watch")
                conf = analysis.get("confidence", 0.0)
                if rec in {"buy", "sell"}:
                    strong_calls.append(f"{symbol} {rec} {conf:.0%}")

            label = stem.replace("_", " ")
            history_lines.append(
                f"- {label} [{phase}] sentiment={sentiment}, regime={regime}, "
                f"best={', '.join(best) if best else 'none'}"
            )
            if strong_calls:
                history_lines.append(f"  Strong calls: {', '.join(strong_calls[:3])}")
            if market_summary:
                history_lines.append(f"  Summary: {market_summary[:180]}")

        if history_lines:
            lines.append("RECENT SAVED RESEARCH ARTIFACTS:")
            lines.extend(history_lines)

    return "\n".join(lines) if lines else "No saved research artifacts yet."


def save_prompt_context_snapshot(
    *,
    phase: str,
    provider: str,
    model: str,
    symbols: list[str],
    prompt_sections: dict[str, Any],
    llm_meta: dict[str, Any] | None = None,
    data_dir: str = "data",
) -> str:
    """Persist the structured prompt inputs for auditability and reuse."""
    root = Path(data_dir) / "context"
    root.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    payload = {
        "timestamp": now.isoformat(),
        "phase": phase,
        "provider": provider,
        "model": model,
        "symbols": symbols,
        "prompt_sections": prompt_sections,
        "llm_meta": llm_meta or {},
    }

    filename = f"{now.strftime('%Y-%m-%d')}_{phase}_{now.strftime('%H%M%S')}.json"
    path = root / filename
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    (root / f"latest_{phase}.json").write_text(
        json.dumps(payload, indent=2, default=str),
        encoding="utf-8",
    )

    return str(path)
