"""Shared helpers for turning trading theses into operational state.

These helpers deliberately avoid making API calls. They normalize whatever the
morning strategist produced and whatever market context is already available
into small, explicit fields the monitor can enforce.
"""

from __future__ import annotations

from typing import Any


REGIME_FACTOR_KEYS = (
    "sp500_trend",
    "qqq_trend",
    "small_cap_breadth",
    "vix_direction",
    "ten_year_yield",
    "sector_breadth",
    "candidate_relative_strength",
    "headline_risk",
)

SETUP_STATES = {
    "planned",
    "eligible",
    "triggered",
    "invalidated",
    "repair_watch",
    "retired",
}

WATCHLIST_BUCKETS = {
    "buy_today_if_confirmed",
    "repair_watch",
    "do_not_chase",
    "event_watch",
    "avoid_until_new_thesis",
}


def normalize_action_confidence(stock: dict[str, Any]) -> dict[str, float]:
    """Return separate confidence scores for thesis, entry, avoid, and data quality."""

    existing = stock.get("action_confidence")
    if isinstance(existing, dict):
        return {
            "long_thesis": _clamp(existing.get("long_thesis")),
            "entry": _clamp(existing.get("entry")),
            "avoid": _clamp(existing.get("avoid")),
            "data_quality": _clamp(existing.get("data_quality"), default=0.5),
        }

    confidence = _clamp(stock.get("confidence"), default=0.5)
    recommendation = str(stock.get("recommendation") or "watch").strip().lower()
    sentiment = str(stock.get("sentiment") or "neutral").strip().lower()
    thesis_conf = confidence if recommendation == "buy" or sentiment == "bullish" else min(confidence, 0.5)
    entry_conf = confidence if recommendation == "buy" else min(confidence, 0.35)
    avoid_conf = confidence if recommendation in {"watch", "hold"} else 1.0 - confidence
    return {
        "long_thesis": round(thesis_conf, 3),
        "entry": round(entry_conf, 3),
        "avoid": round(_clamp(avoid_conf), 3),
        "data_quality": 0.5,
    }


def determine_setup_state(
    stock: dict[str, Any],
    *,
    current_price: float | None = None,
) -> str:
    """Classify a setup lifecycle state from recommendation, plan, and price."""

    existing = str(stock.get("setup_state") or "").strip().lower()
    if existing in SETUP_STATES:
        return existing

    recommendation = str(stock.get("recommendation") or "watch").strip().lower()
    if recommendation == "hold":
        return "planned"
    if recommendation == "sell":
        return "eligible"

    plan = stock.get("trade_plan") if isinstance(stock.get("trade_plan"), dict) else {}
    entry = _to_float(plan.get("entry"))
    stop = _to_float(plan.get("stop_loss"))
    target = _to_float(plan.get("target"))
    price = _to_float(current_price)

    if price and stop and recommendation in {"buy", "watch"} and price <= stop:
        return "invalidated"
    if price and target and recommendation in {"buy", "watch"} and price >= target:
        return "triggered"
    if recommendation == "buy":
        if price and entry and abs(price - entry) / entry <= 0.03:
            return "eligible"
        return "planned"
    return "planned"


def classify_watchlist_bucket(stock: dict[str, Any], *, setup_state: str | None = None) -> str:
    """Place a stock into the operator-facing watchlist bucket taxonomy."""

    existing = str(stock.get("watchlist_bucket") or "").strip().lower()
    if existing in WATCHLIST_BUCKETS:
        return existing

    state = setup_state or determine_setup_state(stock)
    recommendation = str(stock.get("recommendation") or "watch").strip().lower()
    sentiment = str(stock.get("sentiment") or "neutral").strip().lower()
    thesis = stock.get("swing_thesis") if isinstance(stock.get("swing_thesis"), dict) else {}
    entry_quality = str(thesis.get("entry_quality") or "").strip().lower()
    crowding = str(thesis.get("crowding_risk") or "").strip().lower()
    catalysts = stock.get("catalysts") if isinstance(stock.get("catalysts"), list) else []

    if state in {"invalidated", "repair_watch"}:
        return "repair_watch"
    if sentiment == "bearish" and recommendation != "sell":
        return "avoid_until_new_thesis"
    if entry_quality in {"late", "chasing"} or crowding == "high":
        return "do_not_chase"
    if recommendation == "buy":
        return "buy_today_if_confirmed"
    if catalysts:
        return "event_watch"
    return "avoid_until_new_thesis"


def normalize_stock_theory(
    stock: dict[str, Any],
    *,
    current_price: float | None = None,
) -> dict[str, Any]:
    """Return a copy of stock payload with operational theory fields populated."""

    normalized = dict(stock)
    setup_state = determine_setup_state(normalized, current_price=current_price)
    normalized["setup_state"] = setup_state
    normalized["watchlist_bucket"] = classify_watchlist_bucket(normalized, setup_state=setup_state)
    normalized["action_confidence"] = normalize_action_confidence(normalized)
    normalized.setdefault("top_blocker", _infer_top_blocker(normalized))
    return normalized


def build_watchlist_buckets(stocks: dict[str, Any]) -> dict[str, list[str]]:
    buckets = {bucket: [] for bucket in WATCHLIST_BUCKETS}
    for symbol, stock in sorted(stocks.items()):
        if not isinstance(stock, dict):
            continue
        bucket = str(stock.get("watchlist_bucket") or "").strip().lower()
        if bucket not in WATCHLIST_BUCKETS:
            bucket = classify_watchlist_bucket(stock)
        buckets[bucket].append(str(symbol).upper())
    return buckets


def build_regime_scorecard(
    market_context: dict[str, Any] | None,
    *,
    declared_regime: str | None = None,
) -> dict[str, Any]:
    """Build an eight-factor regime scorecard from already-fetched context."""

    ctx = market_context if isinstance(market_context, dict) else {}
    factors: dict[str, dict[str, Any]] = {
        key: {"state": "unknown", "score": 0, "evidence": "not available"}
        for key in REGIME_FACTOR_KEYS
    }

    sp = ctx.get("sp500") if isinstance(ctx.get("sp500"), dict) else {}
    sp_change = _to_float(sp.get("change_pct"))
    sp_trend = str(sp.get("trend") or "").lower()
    if sp_change is not None or sp_trend:
        factors["sp500_trend"] = _factor_from_change(
            sp_change,
            bullish_threshold=0.25,
            bearish_threshold=-0.25,
            evidence=f"SPY change={sp_change}, trend={sp_trend or 'unknown'}",
        )

    qqq = ctx.get("nasdaq") if isinstance(ctx.get("nasdaq"), dict) else {}
    qqq_change = _to_float(qqq.get("change_pct"))
    if qqq_change is not None:
        factors["qqq_trend"] = _factor_from_change(
            qqq_change,
            bullish_threshold=0.25,
            bearish_threshold=-0.25,
            evidence=f"QQQ change={qqq_change}",
        )

    breadth = ctx.get("breadth")
    if isinstance(breadth, dict):
        adv_pct = _to_float(breadth.get("advance_pct") or breadth.get("advancers_pct"))
        if adv_pct is not None:
            factors["small_cap_breadth"] = _factor_from_change(
                adv_pct - 50.0,
                bullish_threshold=5.0,
                bearish_threshold=-5.0,
                evidence=f"advance percentage={adv_pct}",
            )

    vix = ctx.get("vix") if isinstance(ctx.get("vix"), dict) else {}
    vix_level = str(vix.get("level") or "").lower()
    vix_change = _to_float(vix.get("change"))
    if vix_level or vix_change is not None:
        if vix_level in {"high", "extreme"} or (vix_change is not None and vix_change > 1.0):
            state, score = "bearish", -1
        elif vix_level in {"low", "normal"} and (vix_change is None or vix_change <= 0.5):
            state, score = "bullish", 1
        else:
            state, score = "neutral", 0
        factors["vix_direction"] = {
            "state": state,
            "score": score,
            "evidence": f"VIX level={vix_level or 'unknown'}, change={vix_change}",
        }

    tnx = ctx.get("treasury_10y") if isinstance(ctx.get("treasury_10y"), dict) else {}
    yld = _to_float(tnx.get("yield_pct"))
    yld_change = _to_float(tnx.get("change_pct") or tnx.get("change"))
    if yld is not None or yld_change is not None:
        if yld_change is not None:
            state = "bearish" if yld_change > 0.05 else "bullish" if yld_change < -0.05 else "neutral"
            score = -1 if state == "bearish" else 1 if state == "bullish" else 0
        else:
            state, score = "neutral", 0
        factors["ten_year_yield"] = {
            "state": state,
            "score": score,
            "evidence": f"10Y yield={yld}, change={yld_change}",
        }

    sectors = ctx.get("sector_performance") if isinstance(ctx.get("sector_performance"), dict) else {}
    if sectors:
        positives = 0
        negatives = 0
        for data in sectors.values():
            if not isinstance(data, dict):
                continue
            daily = _to_float(data.get("daily_pct"))
            if daily is None:
                continue
            positives += int(daily > 0)
            negatives += int(daily < 0)
        if positives or negatives:
            state = "bullish" if positives >= negatives + 2 else "bearish" if negatives >= positives + 2 else "neutral"
            score = 1 if state == "bullish" else -1 if state == "bearish" else 0
            factors["sector_breadth"] = {
                "state": state,
                "score": score,
                "evidence": f"{positives} sectors positive, {negatives} sectors negative",
            }

    declared = str(declared_regime or ctx.get("market_regime") or "").strip().lower()
    if declared in {"risk_on", "risk_off", "neutral", "cautious"}:
        if declared == "risk_on":
            state, score = "bullish", 1
        elif declared in {"risk_off", "cautious"}:
            state, score = "bearish", -1
        else:
            state, score = "neutral", 0
        factors["headline_risk"] = {
            "state": state,
            "score": score,
            "evidence": f"declared regime={declared}",
        }

    total = sum(int(factor["score"]) for factor in factors.values())
    bullish_count = sum(1 for factor in factors.values() if factor["state"] == "bullish")
    bearish_count = sum(1 for factor in factors.values() if factor["state"] == "bearish")
    unknown_count = sum(1 for factor in factors.values() if factor["state"] == "unknown")
    computed = "risk_on" if bullish_count >= 5 and bearish_count <= 1 else (
        "risk_off" if bearish_count >= 3 or total <= -2 else "neutral"
    )
    return {
        "computed_regime": computed,
        "declared_regime": declared or "unknown",
        "score": total,
        "bullish_factors": bullish_count,
        "bearish_factors": bearish_count,
        "unknown_factors": unknown_count,
        "factors": factors,
        "rule": "risk_on requires at least 5 bullish factors and no more than 1 bearish factor; otherwise use neutral/risk_off.",
    }


def format_regime_scorecard(scorecard: dict[str, Any] | None) -> str:
    if not isinstance(scorecard, dict) or not scorecard:
        return "No regime scorecard available."
    lines = [
        (
            f"Computed regime: {scorecard.get('computed_regime', 'unknown')} "
            f"(score={scorecard.get('score', 0)}, bullish={scorecard.get('bullish_factors', 0)}, "
            f"bearish={scorecard.get('bearish_factors', 0)}, unknown={scorecard.get('unknown_factors', 0)})."
        ),
        f"Rule: {scorecard.get('rule', '')}",
    ]
    factors = scorecard.get("factors") if isinstance(scorecard.get("factors"), dict) else {}
    for name in REGIME_FACTOR_KEYS:
        factor = factors.get(name) if isinstance(factors.get(name), dict) else {}
        lines.append(
            f"- {name}: {factor.get('state', 'unknown')} "
            f"({factor.get('score', 0)}); {factor.get('evidence', 'not available')}"
        )
    return "\n".join(lines)


def format_watchlist_buckets(buckets: dict[str, list[str]] | None) -> str:
    if not isinstance(buckets, dict) or not buckets:
        return "No structured watchlist buckets available."
    return "\n".join(
        f"- {bucket}: {', '.join(symbols) if symbols else '(none)'}"
        for bucket, symbols in sorted(buckets.items())
    )


def _infer_top_blocker(stock: dict[str, Any]) -> str:
    state = str(stock.get("setup_state") or "").lower()
    if state in {"invalidated", "repair_watch"}:
        return "setup invalidated; require repair before any long entry"
    thesis = stock.get("swing_thesis") if isinstance(stock.get("swing_thesis"), dict) else {}
    if str(thesis.get("entry_quality") or "").lower() in {"late", "chasing"}:
        return "entry quality is late/chasing"
    if str(thesis.get("crowding_risk") or "").lower() == "high":
        return "crowding risk is high"
    if str(stock.get("recommendation") or "").lower() != "buy":
        return "not a buy candidate"
    return "awaiting execution-condition confirmation"


def _factor_from_change(
    value: float | None,
    *,
    bullish_threshold: float,
    bearish_threshold: float,
    evidence: str,
) -> dict[str, Any]:
    if value is None:
        return {"state": "unknown", "score": 0, "evidence": evidence}
    if value >= bullish_threshold:
        return {"state": "bullish", "score": 1, "evidence": evidence}
    if value <= bearish_threshold:
        return {"state": "bearish", "score": -1, "evidence": evidence}
    return {"state": "neutral", "score": 0, "evidence": evidence}


def _clamp(value: Any, *, default: float = 0.0) -> float:
    number = _to_float(value)
    if number is None:
        number = default
    return round(max(0.0, min(1.0, number)), 3)


def _to_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
