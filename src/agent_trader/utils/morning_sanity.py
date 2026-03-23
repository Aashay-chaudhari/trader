"""Sanity checks for locally generated morning research artifacts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yfinance as yf

from agent_trader.utils.runtime import configure_yfinance_cache

MAX_ENTRY_DEVIATION_PCT = 15.0
MAX_TARGET_DEVIATION_PCT = 35.0
MAX_EXECUTION_CONDITION_DEVIATION_PCT = 25.0
STRUCTURAL_RECOMMENDATIONS = {"buy", "sell", "hold", "watch"}


@dataclass
class MorningSanityResult:
    """Validation outcome for a morning research artifact."""

    errors: list[str]
    warnings: list[str]
    reference_prices: dict[str, float]

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_morning_research_file(
    data_dir: str | Path,
    *,
    reference_prices: dict[str, float] | None = None,
    max_entry_deviation_pct: float = MAX_ENTRY_DEVIATION_PCT,
) -> MorningSanityResult:
    """Validate a profile's morning research cache against recent market prices."""

    root = Path(data_dir)
    cache_path = root / "cache" / "morning_research.json"
    if not cache_path.exists():
        return MorningSanityResult(
            errors=[f"Morning research cache not found: {cache_path.as_posix()}"],
            warnings=[],
            reference_prices={},
        )

    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        return MorningSanityResult(
            errors=[f"Morning research JSON is invalid: {exc}"],
            warnings=[],
            reference_prices={},
        )

    symbols = sorted(
        symbol
        for symbol in (payload.get("stocks", {}) or {}).keys()
        if isinstance(symbol, str) and symbol.strip()
    )
    live_prices = dict(reference_prices or {})
    if symbols and not live_prices:
        try:
            live_prices = fetch_reference_prices(symbols)
        except Exception as exc:  # pragma: no cover - network issues are warned, not fatal
            return MorningSanityResult(
                errors=_validate_structure(payload),
                warnings=[f"Could not fetch reference prices for validation: {exc}"],
                reference_prices={},
            )

    errors, warnings = validate_morning_research_payload(
        payload,
        reference_prices=live_prices,
        max_entry_deviation_pct=max_entry_deviation_pct,
    )
    return MorningSanityResult(errors=errors, warnings=warnings, reference_prices=live_prices)


def validate_morning_research_payload(
    payload: dict[str, Any],
    *,
    reference_prices: dict[str, float] | None = None,
    max_entry_deviation_pct: float = MAX_ENTRY_DEVIATION_PCT,
) -> tuple[list[str], list[str]]:
    """Validate a parsed morning research payload."""

    errors = _validate_structure(payload)
    warnings: list[str] = []

    stocks = payload.get("stocks", {}) if isinstance(payload, dict) else {}
    if not isinstance(stocks, dict):
        return errors, warnings

    reference_prices = reference_prices or {}
    for symbol, stock_payload in stocks.items():
        if not isinstance(stock_payload, dict):
            continue

        recommendation = str(stock_payload.get("recommendation", "watch")).strip().lower()
        trade_plan = stock_payload.get("trade_plan", {})
        if not isinstance(trade_plan, dict):
            trade_plan = {}

        entry = _safe_float(trade_plan.get("entry"))
        stop = _safe_float(trade_plan.get("stop_loss"))
        target = _safe_float(trade_plan.get("target"))

        if recommendation in {"buy", "sell"}:
            errors.extend(
                _validate_trade_plan_geometry(
                    symbol=symbol,
                    recommendation=recommendation,
                    entry=entry,
                    stop=stop,
                    target=target,
                )
            )

            ref_price = _safe_float(reference_prices.get(symbol))
            if ref_price and entry:
                deviation_pct = abs(entry - ref_price) / ref_price * 100
                if deviation_pct > max_entry_deviation_pct:
                    errors.append(
                        (
                            f"{symbol}: entry {entry:.2f} is {deviation_pct:.1f}% away from "
                            f"recent market price {ref_price:.2f}"
                        )
                    )
                if target:
                    target_deviation_pct = abs(target - ref_price) / ref_price * 100
                    if target_deviation_pct > MAX_TARGET_DEVIATION_PCT:
                        warnings.append(
                            (
                                f"{symbol}: target {target:.2f} is {target_deviation_pct:.1f}% away "
                                f"from recent market price {ref_price:.2f}"
                            )
                        )

            execution_condition = str(stock_payload.get("execution_condition", "")).strip()
            execution_warning = _validate_execution_condition_prices(
                symbol=symbol,
                execution_condition=execution_condition,
                reference_price=ref_price,
            )
            if execution_warning:
                warnings.append(execution_warning)

    return errors, warnings


def fetch_reference_prices(symbols: list[str]) -> dict[str, float]:
    """Fetch the most recent close for a set of symbols."""

    configure_yfinance_cache()
    prices: dict[str, float] = {}
    for symbol in symbols:
        ticker = yf.Ticker(symbol)
        history = ticker.history(period="7d", interval="1d", auto_adjust=False)
        if history.empty:
            continue
        close_series = history.get("Close")
        if close_series is None or close_series.empty:
            continue
        try:
            price = float(close_series.dropna().iloc[-1])
        except Exception:
            continue
        if price > 0:
            prices[symbol] = round(price, 4)
    return prices


def _validate_structure(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["Morning research payload must be a JSON object."]

    overall_sentiment = str(payload.get("overall_sentiment", "")).strip().lower()
    if overall_sentiment not in {"bullish", "bearish", "neutral"}:
        errors.append("overall_sentiment must be one of bullish/bearish/neutral")

    market_regime = str(payload.get("market_regime", "")).strip().lower()
    if market_regime not in {"risk_on", "risk_off", "neutral"}:
        errors.append("market_regime must be one of risk_on/risk_off/neutral")

    stocks = payload.get("stocks", {})
    if not isinstance(stocks, dict) or not stocks:
        errors.append("stocks must be a non-empty object")
        return errors

    for symbol, stock_payload in stocks.items():
        if not isinstance(stock_payload, dict):
            errors.append(f"{symbol}: stock payload must be an object")
            continue
        recommendation = str(stock_payload.get("recommendation", "")).strip().lower()
        if recommendation not in STRUCTURAL_RECOMMENDATIONS:
            errors.append(f"{symbol}: recommendation must be one of buy/sell/hold/watch")
        confidence = _safe_float(stock_payload.get("confidence"))
        if confidence is None or not 0.0 <= confidence <= 1.0:
            errors.append(f"{symbol}: confidence must be between 0.0 and 1.0")
        trade_plan = stock_payload.get("trade_plan", {})
        if not isinstance(trade_plan, dict):
            errors.append(f"{symbol}: trade_plan must be an object")
    return errors


def _validate_trade_plan_geometry(
    *,
    symbol: str,
    recommendation: str,
    entry: float | None,
    stop: float | None,
    target: float | None,
) -> list[str]:
    errors: list[str] = []
    if not entry or not stop or not target:
        errors.append(f"{symbol}: buy/sell recommendations require entry, stop_loss, and target")
        return errors

    if recommendation == "buy":
        if not (stop < entry < target):
            errors.append(f"{symbol}: buy plan must satisfy stop_loss < entry < target")
    elif recommendation == "sell":
        if not (target < entry < stop):
            errors.append(f"{symbol}: sell plan must satisfy target < entry < stop_loss")

    risk = abs(entry - stop)
    reward = abs(target - entry)
    if risk <= 0 or reward <= 0:
        errors.append(f"{symbol}: trade plan risk/reward must be positive")
    return errors


def _validate_execution_condition_prices(
    *,
    symbol: str,
    execution_condition: str,
    reference_price: float | None,
) -> str | None:
    if not execution_condition or not reference_price:
        return None

    dollar_values = [
        float(match.group(1).replace(",", ""))
        for match in re.finditer(r"\$([0-9][0-9,]*(?:\.[0-9]{1,2})?)", execution_condition)
    ]
    if not dollar_values:
        return None

    near_values = [
        value
        for value in dollar_values
        if abs(value - reference_price) / reference_price * 100 <= MAX_EXECUTION_CONDITION_DEVIATION_PCT
    ]
    if near_values:
        return None

    return (
        f"{symbol}: execution_condition dollar anchors {', '.join(f'${value:.2f}' for value in dollar_values[:4])} "
        f"do not align with recent market price {reference_price:.2f}"
    )


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
