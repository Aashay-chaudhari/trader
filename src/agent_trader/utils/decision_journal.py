"""Decision journal helpers for monitor-time evidence capture.

The normal trading journal is human-readable. This module writes a compact,
structured ledger of every monitor decision so evening and weekly reviews can
study skipped setups, approved setups, data quality, and calibration.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_trader.config.settings import get_settings
from agent_trader.utils.theory import build_regime_scorecard, normalize_stock_theory


def _as_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _latest_price(market_data: dict[str, Any], symbol: str) -> float | None:
    payload = market_data.get(symbol) if isinstance(market_data, dict) else None
    if not isinstance(payload, dict):
        return None
    return _as_float(
        payload.get("latest_price")
        or payload.get("price")
        or payload.get("current_price")
        or payload.get("close")
    )


def _price_delta_pct(price: float | None, reference: Any) -> float | None:
    ref = _as_float(reference)
    if price is None or ref in (None, 0):
        return None
    return round((price - ref) / ref * 100, 2)


def _decision_outcome(
    symbol: str,
    *,
    signals: list[dict[str, Any]],
    approved: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    executed: list[dict[str, Any]],
) -> str:
    executed_symbols = {str(item.get("symbol", "")).upper() for item in executed}
    approved_symbols = {str(item.get("symbol", "")).upper() for item in approved}
    rejected_symbols = {str(item.get("symbol", "")).upper() for item in rejected}
    signal_symbols = {str(item.get("symbol", "")).upper() for item in signals}
    upper = symbol.upper()
    if upper in executed_symbols:
        return "executed"
    if upper in approved_symbols:
        return "approved_not_executed"
    if upper in rejected_symbols:
        return "risk_rejected"
    if upper in signal_symbols:
        return "strategy_signal_only"
    return "skipped"


def build_decision_journal(
    *,
    run_id: str,
    symbols: list[str],
    morning_context: dict[str, Any] | None,
    monitor_research: dict[str, Any] | None,
    market_data: dict[str, Any] | None,
    market_context: dict[str, Any] | None,
    news_data: dict[str, Any] | None,
    source_stats: dict[str, Any] | None = None,
    provider_health: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
    signals: list[dict[str, Any]] | None = None,
    risk_data: dict[str, Any] | None = None,
    execution_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a structured snapshot of one monitor run."""

    morning = morning_context if isinstance(morning_context, dict) else {}
    monitor = monitor_research if isinstance(monitor_research, dict) else {}
    stocks = morning.get("stocks", {}) if isinstance(morning.get("stocks"), dict) else {}
    monitor_stocks = monitor.get("stocks", {}) if isinstance(monitor.get("stocks"), dict) else {}
    market = market_data if isinstance(market_data, dict) else {}
    news = news_data if isinstance(news_data, dict) else {}
    risk = risk_data if isinstance(risk_data, dict) else {}
    execution = execution_data if isinstance(execution_data, dict) else {}
    signal_list = list(signals or [])
    approved = list(risk.get("approved_trades") or [])
    rejected = list(risk.get("rejected_trades") or [])
    executed = list(execution.get("executed") or [])

    regime_scorecard = (
        market_context.get("regime_scorecard")
        if isinstance(market_context, dict) and isinstance(market_context.get("regime_scorecard"), dict)
        else build_regime_scorecard(
            market_context if isinstance(market_context, dict) else {},
            declared_regime=morning.get("market_regime"),
        )
    )

    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_symbol in symbols:
        symbol = str(raw_symbol).upper().strip()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)

        morning_stock = dict(stocks.get(symbol) or {})
        price = _latest_price(market, symbol)
        theory = normalize_stock_theory(morning_stock, current_price=price)
        monitor_stock = monitor_stocks.get(symbol) if isinstance(monitor_stocks, dict) else {}
        if not isinstance(monitor_stock, dict):
            monitor_stock = {}
        plan = theory.get("trade_plan", {}) if isinstance(theory.get("trade_plan"), dict) else {}
        headline_count = 0
        source_count = 0
        if isinstance(news.get(symbol), dict):
            headline_count = len(news[symbol].get("news_headlines") or [])
            source_count = int(news[symbol].get("source_count") or 0)

        entry = {
            "symbol": symbol,
            "outcome": _decision_outcome(
                symbol,
                signals=signal_list,
                approved=approved,
                rejected=rejected,
                executed=executed,
            ),
            "morning_recommendation": theory.get("recommendation", "watch"),
            "monitor_recommendation": monitor_stock.get("recommendation", "watch"),
            "ready_to_trade": bool(monitor_stock.get("ready_to_trade", False)),
            "setup_state": monitor_stock.get("setup_state") or theory.get("setup_state"),
            "watchlist_bucket": monitor_stock.get("watchlist_bucket") or theory.get("watchlist_bucket"),
            "top_blocker": monitor_stock.get("top_blocker") or theory.get("top_blocker"),
            "action_confidence": monitor_stock.get("action_confidence") or theory.get("action_confidence"),
            "confidence": monitor_stock.get("confidence", theory.get("confidence", 0.0)),
            "monitor_reason": monitor_stock.get("monitor_reason", ""),
            "matched_conditions": monitor_stock.get("matched_conditions", []),
            "failed_conditions": monitor_stock.get("failed_conditions", []),
            "execution_condition": monitor_stock.get(
                "execution_condition",
                theory.get("execution_condition", ""),
            ),
            "price": price,
            "entry": _as_float(plan.get("entry")),
            "stop_loss": _as_float(plan.get("stop_loss")),
            "target": _as_float(plan.get("target")),
            "pct_from_entry": _price_delta_pct(price, plan.get("entry")),
            "pct_from_stop": _price_delta_pct(price, plan.get("stop_loss")),
            "pct_from_target": _price_delta_pct(price, plan.get("target")),
            "headline_count": headline_count,
            "source_count": source_count,
        }
        entries.append(entry)

    return {
        "run_id": run_id,
        "phase": "monitor",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbols": [entry["symbol"] for entry in entries],
        "regime_scorecard": regime_scorecard,
        "news_quality": {
            "source_stats": source_stats or {},
            "provider_health": provider_health or {},
            "warnings": warnings or [],
        },
        "summary": {
            "symbols_reviewed": len(entries),
            "executed": sum(1 for entry in entries if entry["outcome"] == "executed"),
            "approved_not_executed": sum(
                1 for entry in entries if entry["outcome"] == "approved_not_executed"
            ),
            "risk_rejected": sum(1 for entry in entries if entry["outcome"] == "risk_rejected"),
            "skipped": sum(1 for entry in entries if entry["outcome"] == "skipped"),
        },
        "decisions": entries,
    }


def write_decision_journal(
    decision_journal: dict[str, Any],
    *,
    data_dir: str | None = None,
) -> str:
    """Persist one monitor decision journal and return the path."""

    settings = get_settings()
    root = Path(data_dir or settings.data_dir)
    timestamp = str(decision_journal.get("timestamp") or datetime.now(timezone.utc).isoformat())
    date_slug = timestamp[:10]
    time_slug = timestamp[11:19].replace(":", "-") if len(timestamp) >= 19 else "unknown"
    journal_dir = root / "decision_journal" / date_slug
    journal_dir.mkdir(parents=True, exist_ok=True)
    path = journal_dir / f"{time_slug}_{decision_journal.get('run_id', 'monitor')}.json"
    path.write_text(json.dumps(decision_journal, indent=2, default=str), encoding="utf-8")
    return str(path)


def load_recent_decision_journals(
    *,
    data_dir: str | None = None,
    date: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Load recent decision journal entries for reflection prompts."""

    root = Path(data_dir or get_settings().data_dir)
    date_slug = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    journal_dir = root / "decision_journal" / date_slug
    if not journal_dir.exists():
        return []
    payloads: list[dict[str, Any]] = []
    for path in sorted(journal_dir.glob("*.json"), reverse=True)[:limit]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            payloads.append(payload)
    return list(reversed(payloads))


def format_decision_journals_for_prompt(payloads: list[dict[str, Any]], *, limit: int = 40) -> str:
    """Render monitor decisions as compact reflection context."""

    if not payloads:
        return "No monitor decision journal entries were captured today."

    lines = ["Monitor decision evidence:"]
    count = 0
    for payload in payloads:
        run_id = payload.get("run_id", "unknown")
        regime = (payload.get("regime_scorecard") or {}).get("computed_regime", "unknown")
        summary = payload.get("summary") or {}
        lines.append(
            f"- Run {run_id}: regime={regime}, reviewed={summary.get('symbols_reviewed', 0)}, "
            f"executed={summary.get('executed', 0)}, skipped={summary.get('skipped', 0)}"
        )
        for entry in payload.get("decisions", []) or []:
            if count >= limit:
                lines.append(f"  - ... truncated after {limit} decisions")
                return "\n".join(lines)
            action_conf = entry.get("action_confidence") or {}
            lines.append(
                "  - "
                f"{entry.get('symbol')}: outcome={entry.get('outcome')}, "
                f"state={entry.get('setup_state')}, bucket={entry.get('watchlist_bucket')}, "
                f"entry_conf={action_conf.get('entry', 'n/a')}, "
                f"avoid_conf={action_conf.get('avoid', 'n/a')}, "
                f"price={entry.get('price', 'n/a')}, "
                f"from_entry={entry.get('pct_from_entry', 'n/a')}%, "
                f"blocker={entry.get('top_blocker') or 'none'}"
            )
            count += 1
    return "\n".join(lines)
