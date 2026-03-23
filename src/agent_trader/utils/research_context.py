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
    prompt_text: str | None = None,
    prompt_source: str | None = None,
    tool: str | None = None,
    response_payload: dict[str, Any] | None = None,
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
        "prompt_text": prompt_text or "",
        "prompt_source": prompt_source or "",
        "llm_meta": llm_meta or {},
    }

    filename = f"{now.strftime('%Y-%m-%d')}_{phase}_{now.strftime('%H%M%S')}.json"
    path = root / filename
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    (root / f"latest_{phase}.json").write_text(
        json.dumps(payload, indent=2, default=str),
        encoding="utf-8",
    )

    _write_interaction_archive(
        timestamp=now,
        data_dir=Path(data_dir),
        phase=phase,
        tool=tool or provider or "api",
        prompt_text=prompt_text or "",
        prompt_source=prompt_source or "",
        llm_meta=llm_meta or {},
        context_path=path,
        response_payload=response_payload or {},
    )

    return str(path)


def _write_interaction_archive(
    *,
    timestamp: datetime,
    data_dir: Path,
    phase: str,
    tool: str,
    prompt_text: str,
    prompt_source: str,
    llm_meta: dict[str, Any],
    context_path: Path,
    response_payload: dict[str, Any],
) -> None:
    """Mirror API-driven phases into the shared interaction archive layout."""
    interactions_root = data_dir / "interactions" / timestamp.strftime("%Y-%m-%d")
    interactions_root.mkdir(parents=True, exist_ok=True)

    slug = timestamp.strftime("%H%M%S")
    safe_phase = str(phase or "unknown").strip().lower().replace(" ", "_")
    prompt_path = interactions_root / f"{slug}_{safe_phase}_prompt.md"
    transcript_path = interactions_root / f"{slug}_{safe_phase}_transcript.txt"
    metadata_path = interactions_root / f"{slug}_{safe_phase}_interaction.json"

    prompt_body = prompt_text.strip() or "(No raw prompt text captured for this phase.)"
    prompt_path.write_text(prompt_body + "\n", encoding="utf-8")

    transcript_lines = _build_response_transcript(
        phase=safe_phase,
        llm_meta=llm_meta,
        response_payload=response_payload,
    )
    transcript_path.write_text("\n".join(transcript_lines).strip() + "\n", encoding="utf-8")

    payload = {
        "timestamp": timestamp.isoformat(),
        "profile": data_dir.name,
        "phase": safe_phase,
        "tool": tool,
        "status": _interaction_status(llm_meta),
        "prompt_source": prompt_source,
        "prompt_file": prompt_path.as_posix(),
        "transcript_file": transcript_path.as_posix(),
        "context_file": context_path.as_posix(),
        "raw_log_file": "",
        "summary": _interaction_summary(safe_phase, llm_meta, response_payload),
    }
    metadata_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    latest_root = interactions_root.parent
    (latest_root / "latest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (latest_root / f"latest_{safe_phase}.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )


def _interaction_status(llm_meta: dict[str, Any]) -> str:
    status = str(llm_meta.get("status", "")).strip().lower()
    execution_mode = str(llm_meta.get("execution_mode", "")).strip().lower()
    provider = str(llm_meta.get("provider", "")).strip().lower()
    if provider == "monitor-skip":
        return "skipped"
    if status in {"success", "failed", "error", "skipped"}:
        return "failed" if status == "error" else status
    if execution_mode == "none":
        return "skipped"
    return "success"


def _interaction_summary(
    phase: str,
    llm_meta: dict[str, Any],
    response_payload: dict[str, Any],
) -> str:
    provider = str(llm_meta.get("provider", "")).strip()
    model = str(llm_meta.get("model", "")).strip()
    quota_note = str(llm_meta.get("quota_note", "")).strip()
    bits: list[str] = []

    if phase == "monitor":
        stocks = response_payload.get("stocks", {}) if isinstance(response_payload, dict) else {}
        ready = [
            symbol
            for symbol, payload in stocks.items()
            if isinstance(payload, dict) and payload.get("ready_to_trade")
        ]
        candidates = list(stocks.keys())[:4]
        if ready:
            bits.append(f"Ready: {', '.join(ready[:3])}")
        elif candidates:
            bits.append(f"Evaluated: {', '.join(candidates[:3])}")
        market_summary = str(response_payload.get("market_summary", "")).strip()
        if market_summary:
            bits.append(market_summary[:180])
    else:
        market_summary = str(response_payload.get("market_summary", "")).strip()
        if market_summary:
            bits.append(market_summary[:180])

    if provider or model:
        bits.append(" / ".join(part for part in (provider, model) if part))
    if not bits and quota_note:
        bits.append(quota_note[:180])
    return " | ".join(bit for bit in bits if bit)


def _build_response_transcript(
    *,
    phase: str,
    llm_meta: dict[str, Any],
    response_payload: dict[str, Any],
) -> list[str]:
    provider = str(llm_meta.get("provider", "")).strip() or "unknown"
    model = str(llm_meta.get("model", "")).strip() or "unknown"
    status = _interaction_status(llm_meta)
    lines = [
        f"Phase: {phase}",
        f"Provider: {provider}",
        f"Model: {model}",
        f"Status: {status}",
    ]

    usage = llm_meta.get("usage", {}) if isinstance(llm_meta, dict) else {}
    total_tokens = usage.get("total_tokens")
    if total_tokens is not None:
        lines.append(f"Total tokens: {total_tokens}")

    market_summary = str(response_payload.get("market_summary", "")).strip()
    if market_summary:
        lines.extend(["", "Market Summary:", market_summary])

    stocks = response_payload.get("stocks", {}) if isinstance(response_payload, dict) else {}
    if isinstance(stocks, dict) and stocks:
        lines.extend(["", "Stocks:"])
        for symbol, payload in list(stocks.items())[:8]:
            if not isinstance(payload, dict):
                continue
            ready = payload.get("ready_to_trade")
            reason = str(payload.get("monitor_reason", "")).strip()
            recommendation = str(payload.get("recommendation", "")).strip()
            marker = "ready" if ready else recommendation or "watch"
            entry = f"- {symbol}: {marker}"
            if reason:
                entry += f" | {reason}"
            lines.append(entry)

    lines.extend(["", "Response JSON:", json.dumps(response_payload, indent=2, default=str)])
    return lines
