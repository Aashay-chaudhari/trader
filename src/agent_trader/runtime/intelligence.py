"""Observation-led research and objective accounting, with no trading authority.

Leads are deterministic descriptions of captured evidence, not causal conclusions
or profitable signals. Their immutable IDs can be cited before a new test starts.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from datetime import date, datetime, timezone

from .config import ET
from .store import dumps, utc_now

LEAD_LAYER = "market_observation_lead"
INITIAL_CAPITAL = 30000.0


def _time(value):
    try:
        result = (
            value
            if isinstance(value, datetime)
            else datetime.fromisoformat(value.replace("Z", "+00:00"))
        )
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except (ValueError, TypeError, AttributeError):
        return None


def _number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) and not isinstance(value, bool) else None
    except (ValueError, TypeError):
        return None


def _day(value, cutoff, completed=False):
    try:
        result = date.fromisoformat(value)
        return value if result < cutoff or (not completed and result == cutoff) else None
    except (ValueError, TypeError):
        return None


def _insert(store, identity, layer, payload, at):
    cursor = store.db.execute(
        "INSERT OR IGNORE INTO memory(id,layer,expires,payload,at) VALUES(?,?,NULL,?,?)",
        (identity, layer, dumps(payload), at),
    )
    return bool(cursor.rowcount)


def capture_observations(store, packet, now=None):
    """Capture a small fixed selection; identical inputs never become new evidence.

    ``observed_at`` is local capture time, while ``input_observed_at`` and
    ``event_asof`` retain source timing. Old packets are never backdated into a
    record that could have been cited before capture. Macro differences require a
    genuinely earlier local capture, not a historical series reconstructed later.
    """
    captured = _time(now or utc_now())
    observed = _time(packet.get("observed_at"))
    if not captured or not observed or observed > captured:
        return []
    cutoff = observed.astimezone(ET).date()
    stamp = captured.isoformat()
    feed = str(packet.get("data_feed", "unspecified feed"))[:160]
    records = []
    input_ref = "research-input:" + packet["observed_at"]
    if not store.rows("SELECT id FROM memory WHERE id=?", (input_ref,)):
        input_ref = None

    def save(
        kind, subject, event_asof, values, question, alternatives, source, identity_basis=None
    ):
        evidence = {
            "kind": kind,
            "subject": subject,
            "event_asof": event_asof,
            "values": values,
            "source": source,
        }
        digest = hashlib.sha256(
            json.dumps(identity_basis or evidence, sort_keys=True, allow_nan=False).encode()
        ).hexdigest()[:24]
        identity = "observation:" + digest
        record = {
            "id": identity,
            "kind": kind,
            "subject": subject,
            "observed_at": stamp,
            "input_observed_at": observed.isoformat(),
            "event_asof": event_asof,
            "values": values,
            "provenance": {
                "source": source,
                "input_ref": input_ref,
                "capture_mode": packet.get("capture_mode", "market_packet"),
            },
            "question": question,
            "alternatives": alternatives,
            "authority": "Research lead only; selected descriptively, not independent evidence or a trade signal.",
        }
        if _insert(store, identity, LEAD_LAYER, record, stamp):
            records.append(record)

    daily = packet.get("daily_indicators") or {}
    spy = daily.get("SPY", {})
    spy_return = _number(spy.get("return_1d"))
    daily_candidates = []
    if spy_return is not None and _day(spy.get("asof"), cutoff, completed=True):
        for symbol, item in daily.items():
            value = _number(item.get("return_1d"))
            if symbol != "SPY" and value is not None and item.get("asof") == spy["asof"]:
                relative = value - spy_return
                if abs(relative) >= 0.01:
                    daily_candidates.append((abs(relative), symbol, value, relative, item))
    for _, symbol, value, relative, item in sorted(daily_candidates, reverse=True)[:3]:
        save(
            "daily_relative_move",
            symbol,
            item["asof"],
            {
                "return_1d": value,
                "spy_return_1d": spy_return,
                "relative_return_1d": relative,
                "return_3d": _number(item.get("return_3d")),
                "last_daily_close": _number(item.get("last_daily_close")),
                "selection_rule": "Largest absolute one-session difference from SPY, at least 1 percentage point; maximum three.",
            },
            "Does this observed relative move persist or reverse on new sessions, and what observable information distinguishes those outcomes?",
            [
                "Company-specific news or sector exposure",
                "Market beta/volatility and ordinary noise",
                "Single-exchange or adjusted-data effects",
            ],
            feed + "; completed daily bars, same date for SPY and subject",
        )

    # Quotes already fetched by the order loop can supply new intraday evidence
    # without a model call or an extra data request. Preserve the first qualifying
    # captured quote in each fixed symbol/time bucket rather than rewriting it.
    from .engine import quote_values

    current_day = captured.astimezone(ET).date()
    current_quotes = {}
    for symbol, snapshot in (packet.get("market") or {}).items():
        quote = snapshot.get("latestQuote") or {}
        prior = daily.get(symbol, {})
        prior_close = _number(prior.get("last_daily_close"))
        quote_at = _time(quote.get("t"))
        if (
            not prior_close
            or prior_close <= 0
            or not _day(prior.get("asof"), current_day, completed=True)
        ):
            continue
        if not quote_at or quote_at > captured or quote_at.astimezone(ET).date() != current_day:
            continue
        try:
            bid, ask = quote_values(quote, captured)
        except (ValueError, TypeError, KeyError):
            continue
        midpoint = (bid + ask) / 2
        current_quotes[symbol] = {
            "bid": bid,
            "ask": ask,
            "quote_at": quote_at.isoformat(),
            "midpoint": midpoint,
            "prior_close": prior_close,
            "prior_close_date": prior["asof"],
            "change_from_prior_close": midpoint / prior_close - 1,
        }
    current_spy = current_quotes.get("SPY")
    current_candidates = []
    if current_spy:
        for symbol, item in current_quotes.items():
            if symbol == "SPY" or item["prior_close_date"] != current_spy["prior_close_date"]:
                continue
            difference = item["change_from_prior_close"] - current_spy["change_from_prior_close"]
            if abs(difference) >= 0.005:
                current_candidates.append((abs(difference), symbol, item, difference))
    bucket = (
        captured.astimezone(ET)
        .replace(minute=captured.astimezone(ET).minute // 15 * 15, second=0, microsecond=0)
        .isoformat()
    )
    for _, symbol, item, difference in sorted(current_candidates, reverse=True)[:3]:
        save(
            "intraday_relative_move",
            symbol,
            item["quote_at"],
            {
                **item,
                "spy": current_spy,
                "relative_change": difference,
                "capture_bucket": bucket,
                "selection_rule": "Largest absolute prior-close-relative difference from SPY, at least 0.5 percentage points; maximum three, first capture per symbol per 15-minute bucket.",
            },
            "What new verified information could explain this current relative movement, and which prospective observation would distinguish continuation from reversal?",
            [
                "Different market/sector exposures",
                "Company-specific repricing",
                "Temporary noise or feed effects; midpoint movement is not a fill",
            ],
            feed
            + "; fresh two-sided quotes versus completed daily close; midpoint descriptive only",
            {"kind": "intraday_relative_move", "symbol": symbol, "bucket": bucket, "feed": feed},
        )

    macro_candidates = []
    for series, item in sorted((packet.get("macro_daily_delayed") or {}).items()):
        value = _number(item.get("value"))
        event_day = _day(item.get("observation_date"), cutoff)
        if value is None or not event_day:
            continue
        key = "observation-macro-baseline:" + series
        prior = store.get(key)
        prior_time = (
            _time(prior.get("input_observed_at", prior.get("observed_at"))) if prior else None
        )
        if prior_time and observed <= prior_time:
            continue
        if prior and event_day < prior["event_asof"]:
            continue
        if prior and value != prior["value"]:
            revised = event_day == prior["event_asof"]
            macro_candidates.append((series, item, prior, value, event_day, revised))
        store.set(
            key,
            {
                "observed_at": stamp,
                "input_observed_at": observed.isoformat(),
                "event_asof": event_day,
                "value": value,
            },
        )
    for series, item, prior, value, event_day, revised in macro_candidates[:3]:
        save(
            "macro_revision" if revised else "macro_observed_change",
            series,
            event_day,
            {
                "value": value,
                "previous_value": prior["value"],
                "difference": value - prior["value"],
                "previous_event_asof": prior["event_asof"],
                "previous_observed_at": prior["observed_at"],
                "previous_input_observed_at": prior.get("input_observed_at", prior["observed_at"]),
                "unit": "provider series units; yield/credit series in percentage points, VIX in index points",
            },
            "Is this a source revision rather than new market information?"
            if revised
            else "Does this newly captured delayed macro change coincide with a distinct future equity response?",
            [
                "Delayed or revised release, not contemporaneous news",
                "Shared economic drivers rather than a causal effect",
                "Ordinary day-to-day variation",
            ],
            str(item.get("source") or "FRED daily delayed series")[:240],
        )

    minute_candidates = []
    for symbol, item in (packet.get("intraday_indicators") or {}).items():
        asof = _time(item.get("asof"))
        close, vwap = _number(item.get("last_completed_close")), _number(item.get("bar_vwap_iex"))
        if (
            asof
            and 0 <= (captured - asof).total_seconds() <= 120
            and close is not None
            and close > 0
            and vwap is not None
            and vwap > 0
            and item.get("opening_5m_complete")
            and item.get("missing_minute_intervals") == 0
        ):
            difference = close / vwap - 1
            if abs(difference) >= 0.003:
                minute_candidates.append((abs(difference), symbol, item, difference))
    for _, symbol, item, difference in sorted(minute_candidates, reverse=True)[:2]:
        save(
            "intraday_vwap_distance",
            symbol,
            item["asof"],
            {
                "last_completed_close": _number(item["last_completed_close"]),
                "bar_vwap_iex": _number(item["bar_vwap_iex"]),
                "distance": difference,
                "observed_minute_bars": item.get("observed_minute_bars"),
                "selection_rule": "Largest absolute completed-close distance from IEX bar VWAP, at least 0.3%; maximum two.",
            },
            "Under which verified conditions does this deviation continue or revert over a predeclared forward horizon?",
            [
                "Trending price discovery",
                "Temporary imbalance or noise",
                "IEX coverage differs from consolidated trading",
            ],
            "Alpaca free IEX completed-minute bars; complete observed interval coverage",
        )

    missing = sorted(set(packet.get("universe", [])) - set(daily))
    problems = [
        str(x)[:180] for x in packet.get("unknowns", []) if "unavailable" in str(x).lower()
    ][:4]
    if missing or problems:
        save(
            "data_gap",
            "research_inputs",
            cutoff.isoformat(),
            {"missing_daily_symbols": missing[:40], "reported_unavailable": problems},
            "Is a missing observation causing repeated research abstention, and which free input repair would resolve it?",
            [
                "Provider coverage or transient failure",
                "Insufficient completed history",
                "Missing data says nothing about market attractiveness",
            ],
            feed + "; availability diagnostic, not a price observation",
        )
    return records


def observation_ids_valid(store, ids, *, before=None):
    """Validate genuine captured IDs and a strict pre-draft observation cutoff."""
    if not isinstance(ids, (list, tuple)) or not ids or len(ids) > 12:
        return False
    if any(not isinstance(identity, str) for identity in ids) or len(set(ids)) != len(ids):
        return False
    cutoff = _time(before) if before is not None else None
    if before is not None and cutoff is None:
        return False
    for identity in ids:
        rows = store.rows(
            "SELECT payload FROM memory WHERE id=? AND layer=?", (identity, LEAD_LAYER)
        )
        if not rows:
            return False
        stamp = _time(json.loads(rows[0]["payload"]).get("observed_at"))
        if not stamp or (cutoff is not None and stamp > cutoff):
            return False
    return True


def observation_context(store, max_chars=4500):
    rows = store.rows(
        "SELECT payload FROM memory WHERE layer=? ORDER BY at DESC,id LIMIT 30", (LEAD_LAYER,)
    )
    records = [json.loads(row["payload"]) for row in rows]
    total = store.rows("SELECT count(*) n FROM memory WHERE layer=?", (LEAD_LAYER,))[0]["n"]
    context = {
        "as_of": utc_now(),
        "records": records,
        "total_records": total,
        "omitted": total - len(records),
        "scope": "Immutable local observations, selected descriptively. Dates and alternatives matter; history is context, not new evidence. No causal or profitability claim.",
    }
    while records and max_chars is not None and len(dumps(context)) > max_chars:
        records.pop()
        context["omitted"] += 1
    return context


def record_reconciled_equity(store, now=None):
    """Append verified account marks prospectively; never certify legacy history."""
    current = _time(now or utc_now())
    stamp = _time(store.get("last_reconciled"))
    equity = _number(store.get("account", {}).get("equity"))
    if (
        not store.get("reconciled")
        or not stamp
        or not current
        or stamp > current
        or equity is None
        or equity < 0
    ):
        return False
    payload = {
        "at": stamp.isoformat(),
        "equity": equity,
        "basis": "Broker account equity at successful local ledger reconciliation",
    }
    return _insert(
        store,
        "reconciled-equity:" + stamp.isoformat(),
        "reconciled_equity",
        payload,
        stamp.isoformat(),
    )


def objective_scorecard(store, now=None):
    """Read-only progress toward net returns; no conversion of shadow means to P&L."""
    current = _time(now or utc_now()) or datetime.now(timezone.utc)
    reconciled = bool(store.get("reconciled"))
    equity = _number(store.get("account", {}).get("equity")) if reconciled else None
    reconciled_at = _time(store.get("last_reconciled"))
    if not reconciled_at or reconciled_at > current:
        reconciled, equity = False, None
    verified = store.rows(
        "SELECT min(at) first_at,count(*) n,max(dd) drawdown FROM ("
        "SELECT at,1.0-json_extract(payload,'$.equity')/max(30000.0,"
        "max(json_extract(payload,'$.equity')) OVER (ORDER BY at ROWS UNBOUNDED PRECEDING)) dd "
        "FROM memory WHERE layer='reconciled_equity')"
    )[0]
    fills = store.rows("SELECT count(*) n FROM events WHERE kind='fill'")[0]["n"]
    experiments = store.rows(
        "SELECT e.id,e.state,count(s.id) samples FROM experiments e LEFT JOIN shadow s "
        "ON s.experiment=e.id AND s.state='closed' GROUP BY e.id"
    )
    catalogue = store.get("research_catalogue", [])
    adaptive = []
    if store.rows(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='adaptive_contracts'"
    ):
        adaptive = store.rows("SELECT id,state,payload FROM adaptive_contracts")
    tested_hypotheses = {json.loads(r["payload"])["hypothesis_id"] for r in adaptive}
    lesson_states = Counter(
        json.loads(r["payload"]).get("state", "unknown")
        for r in store.rows("SELECT payload FROM memory WHERE layer='lesson'")
    )
    proposals = [
        json.loads(r["payload"])
        for r in store.rows("SELECT payload FROM memory WHERE layer='improvement_proposal'")
    ]
    latest_input = _time(store.get("market_packet", {}).get("observed_at"))
    input_age = (
        max(0, (current - latest_input).total_seconds() / 3600)
        if latest_input and latest_input <= current
        else None
    )
    latest_lead = store.rows(
        "SELECT max(at) at,count(*) n FROM memory WHERE layer=?", (LEAD_LAYER,)
    )[0]
    active = [e for e in experiments if e["state"] == "shadow"]
    funnel = {
        "observation_leads": latest_lead["n"],
        "catalogue_cards": len(catalogue),
        "reviewed_hypotheses": sum(c.get("state") == "reviewed_for_testing" for c in catalogue),
        "held_hypotheses": sum(c.get("state") != "reviewed_for_testing" for c in catalogue),
        "registered_experiments": len(experiments),
        "active_shadow_experiments": len(active),
        "experiments_with_samples": sum(e["samples"] > 0 for e in experiments),
        "closed_shadow_samples": sum(e["samples"] for e in experiments),
        "promoted_experiments": sum(e["state"] == "promoted" for e in experiments),
        "planned_entries": store.rows(
            "SELECT count(*) n FROM plans WHERE state IN ('planned','approved')"
        )[0]["n"],
        "adaptive_studies": len(adaptive),
        "reviewed_without_implemented_test": sum(
            c.get("state") == "reviewed_for_testing"
            and not c.get("experiment_ids")
            and c.get("id") not in tested_hypotheses
            for c in catalogue
        ),
    }
    diagnostics = []
    from .engine import current_execution_verified

    if not current_execution_verified(store.get("readiness", {})):
        diagnostics.append(
            {
                "id": "execution_unverified",
                "state": "pending",
                "detail": "A reconciled entry-and-exit fill cycle is still required before strategy execution.",
            }
        )
    if active and not any(e["samples"] for e in active):
        diagnostics.append(
            {
                "id": "experiment_sample_starvation",
                "state": "observed",
                "detail": "Active filter challengers have no completed samples. A catalogue or fixed-cohort count does not test these filters.",
            }
        )
    if latest_input is None or input_age is None or input_age > 18:
        diagnostics.append(
            {
                "id": "input_age",
                "state": "context",
                "detail": "No recent captured market packet; check the actual session calendar before classifying this as a fault.",
            }
        )
    if lesson_states["proposed"] and not lesson_states["tested"]:
        diagnostics.append(
            {
                "id": "untested_lessons",
                "state": "observed",
                "detail": "Persisted lessons are proposed process knowledge; none is marked tested. Repetition does not strengthen evidence.",
            }
        )
    references = []
    extra_friction = (
        sum(r["notional"] for r in store.rows("SELECT notional FROM orders WHERE filled>0")) * 0.001
    )
    benchmarks = store.get("benchmarks", {})
    for symbol in ("SPY", "QQQ", "TLT"):
        item = benchmarks.get(symbol, {})
        if _number(item.get("return")) is not None:
            references.append(
                {
                    "symbol": symbol,
                    "return": _number(item["return"]),
                    "as_of": item.get("at"),
                    "started_at": benchmarks.get("starts", {}).get(symbol, {}).get("at"),
                }
            )
    return {
        "as_of": current.isoformat(),
        "objective": "Positive paper portfolio return that survives explicit cost stress and controlled drawdown, then independently verified transferability; research activity alone is not success.",
        "portfolio": {
            "initial_capital": INITIAL_CAPITAL,
            "equity": equity,
            "net_pnl": equity - INITIAL_CAPITAL if equity is not None else None,
            "total_return": equity / INITIAL_CAPITAL - 1 if equity is not None else None,
            "extra_friction_assumption": "Additional 10bp per recorded buy/sell notional; illustrative stress, not actual measured execution cost.",
            "assumed_extra_friction": extra_friction,
            "return_after_extra_friction": (equity - extra_friction) / INITIAL_CAPITAL - 1
            if equity is not None
            else None,
            "max_drawdown": max(0, verified["drawdown"]) if verified["n"] else None,
            "drawdown_observed_since": verified["first_at"],
            "verified_equity_marks": verified["n"],
            "reconciled": reconciled,
            "as_of": reconciled_at.isoformat() if reconciled_at else None,
            "confirmed_fill_events": fills,
            "filled_orders": store.rows("SELECT count(*) n FROM orders WHERE filled>0")[0]["n"],
            "execution_verified": bool(store.get("readiness", {}).get("execution_verified")),
            "current_execution_verified": current_execution_verified(store.get("readiness", {})),
            "cash_comparator_return": 0.0,
            "market_references": references,
            "basis": "Latest reconciled broker account equity versus $30,000. Drawdown uses only prospective verified marks; legacy marks lack reconciliation flags. Cash comparator assumes zero yield.",
        },
        "research_funnel": funnel,
        "learning": {
            "proposed_lessons": lesson_states["proposed"],
            "tested_lessons": lesson_states["tested"],
            "latest_input_at": latest_input.isoformat() if latest_input else None,
            "input_age_hours": input_age,
            "latest_observation_at": latest_lead["at"],
        },
        "development": {
            "total_proposals": len(proposals),
            "stage_counts": dict(Counter(p.get("state", "unknown") for p in proposals)),
            "automated_scope": "Pure entry-filter candidates only; broader application repairs require the development release workflow.",
        },
        "diagnostics": diagnostics,
        "limits": [
            "No return target or profitability is guaranteed.",
            "Quote-based shadow units and correlated observations are not portfolio P&L or independent trials.",
            "Market references may start at different times and carry no portfolio alpha claim.",
            "Paper fills and costs do not establish live execution quality.",
            "Unavailable or unreconciled equity stays unknown, never a zero-loss success.",
        ],
    }
