"""Calendar-indexed daily research inputs with immutable private source receipts.

These checks qualify future inputs; they never revise a frozen study or authorize
orders. A return needs its exact calendar endpoints, not invented intervening bars.
"""

from __future__ import annotations

import math
from collections import Counter
from datetime import date, datetime

from .config import ET
from .observation_audit import content_hash
from .store import dumps

VERSION = "calendar-daily-inputs-v1"
FIELDS = (
    "last_daily_close",
    "sma20",
    "return_1d",
    "return_3d",
    "return_5d",
    "preceding_20_close_high",
    "average_daily_volume_20_iex_only",
)


def _stamp(value):
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Daily input timestamps require a timezone")
    return result


def _finite(value, *, positive=False):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return result if math.isfinite(result) and (result > 0 if positive else result >= 0) else None


def _source_value(value):
    # Preserve provider nonfinite values explicitly without invalid JSON receipts.
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return {"invalid_type": type(value).__name__}


def calendar_dates(receipt, as_of, received_at):
    """A broker response with explicit bounds establishes session identities."""
    if date.fromisoformat(as_of).isoformat() != as_of:
        raise ValueError("Invalid daily-input date")
    if not isinstance(receipt, dict):
        raise ValueError("Required broker calendar is unavailable")
    sessions = receipt.get("sessions")
    if (
        not isinstance(sessions, list)
        or not sessions
        or receipt.get("sha256") != content_hash(sessions)
        or _stamp(receipt["observed_at"]) > _stamp(received_at)
        or receipt["requested_start"] > as_of
        or receipt["requested_end"] < as_of
    ):
        raise ValueError("Required broker-calendar receipt is incomplete")
    dates = []
    for session in sessions:
        day = session["date"]
        if date.fromisoformat(day).isoformat() != day:
            raise ValueError("Invalid broker session date")
        if not receipt["requested_start"] <= day <= receipt["requested_end"]:
            raise ValueError("Broker session falls outside requested calendar")
        opened = datetime.fromisoformat(day + "T" + session["open"])
        closed = datetime.fromisoformat(day + "T" + session["close"])
        if opened.tzinfo is not None or closed.tzinfo is not None or opened >= closed:
            raise ValueError("Invalid broker session times")
        dates.append(day)
    if len(dates) != len(set(dates)):
        raise ValueError("Ambiguous duplicate broker sessions")
    prior = sorted(day for day in dates if day < as_of)
    if not prior:
        raise ValueError("Broker calendar does not establish a previous session")
    return prior[-21:]


def _normalize(rows, dates):
    result, conflicts, excluded = {}, set(), Counter()
    if not isinstance(rows, list):
        return {}, {"malformed_symbol_rows": 1}
    for row in rows:
        try:
            at = _stamp(row["t"]).astimezone(ET)
            if (at.hour, at.minute, at.second, at.microsecond) != (0, 0, 0, 0):
                raise ValueError("Daily bar is not at an ET day boundary")
            day = at.date().isoformat()
            if day not in dates:
                continue
            prices = {key: _finite(row.get(key), positive=True) for key in ("o", "h", "l", "c")}
            prices_valid = all(value is not None for value in prices.values())
            if prices_valid:
                prices_valid = (
                    prices["l"]
                    <= min(prices["o"], prices["c"])
                    <= max(prices["o"], prices["c"])
                    <= prices["h"]
                )
            normalized = {
                "day": day,
                "timestamp": at.isoformat(),
                "close": prices["c"] if prices_valid else None,
                "volume": _finite(row.get("v")),
                "source_ohlcv": {
                    key: _source_value(row.get(key)) for key in ("t", "o", "h", "l", "c", "v")
                },
            }
            if day in result and result[day] != normalized:
                conflicts.add(day)
            result[day] = normalized
            if not prices_valid:
                excluded["invalid_ohlc"] += 1
            if normalized["volume"] is None:
                excluded["invalid_volume"] += 1
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
            excluded["invalid_daily_timestamp_or_row"] += 1
    for day in conflicts:
        result.pop(day, None)
    if conflicts:
        excluded["conflicting_daily_records"] = len(conflicts)
    return result, dict(excluded)


def _field(field, dates, rows):
    if field.startswith("return_"):
        lag = int(field.split("_")[1][:-1])
        required = [dates[-lag - 1], dates[-1]] if len(dates) > lag else []
    elif field == "last_daily_close":
        required = dates[-1:]
    elif field == "preceding_20_close_high":
        required = dates[-21:-1] if len(dates) >= 21 else []
    else:
        required = dates[-20:] if len(dates) >= 20 else []
    key = "volume" if field == "average_daily_volume_20_iex_only" else "close"
    sources = [{"day": day, "value": rows.get(day, {}).get(key)} for day in required]
    missing = [source["day"] for source in sources if source["value"] is None]
    value, reason = None, None
    if not required:
        reason = "insufficient_broker_calendar_history"
    elif missing:
        reason = "missing_or_invalid_required_" + key
    else:
        values = [source["value"] for source in sources]
        if field.startswith("return_"):
            value = values[-1] / values[0] - 1
        elif field in ("sma20", "average_daily_volume_20_iex_only"):
            value = math.fsum(number / len(values) for number in values)
        elif field == "preceding_20_close_high":
            value = max(values)
        else:
            value = values[0]
        if not math.isfinite(value):
            value, reason = None, "nonfinite_derived_value"
    return {
        "value": value,
        "status": "known" if reason is None else "unknown",
        "reason": reason,
        "required_dates": required,
        "missing_dates": missing,
        "sources": sources,
    }


def build_daily_inputs(
    store, bars, calendar_receipt, *, as_of, observed_at, received_at, source_metadata, symbols
):
    """Return indicators and a compact reference to exact private input lineage."""
    if _stamp(received_at) < _stamp(observed_at):
        raise ValueError("Daily input receipt precedes observation start")
    if _stamp(observed_at).astimezone(ET).date().isoformat() != as_of:
        raise ValueError("Daily input date differs from its observation date")
    if any(
        source_metadata.get(key) != value
        for key, value in (("feed", "iex"), ("adjustment", "all"), ("timeframe", "1Day"))
    ):
        raise ValueError("Daily input source does not match the declared feature basis")
    if (
        source_metadata.get("bars_requested_at") is not None
        or source_metadata.get("bars_received_at") is not None
    ):
        if not (
            _stamp(observed_at)
            <= _stamp(source_metadata["bars_requested_at"])
            <= _stamp(source_metadata["bars_received_at"])
            <= _stamp(received_at)
        ):
            raise ValueError("Daily bar acquisition interval is inconsistent")
    broker_receipt = source_metadata.get("broker_receipt")
    if broker_receipt is not None:
        params = broker_receipt.get("request_params", {})
        if (
            broker_receipt.get("complete") is not True
            or broker_receipt.get("response_sha256") != content_hash(bars)
            or any(
                params.get(key) != source_metadata[key]
                for key in ("feed", "adjustment", "timeframe")
            )
        ):
            raise ValueError("Daily bar request receipt does not match retained inputs")
        if not (
            _stamp(observed_at)
            <= _stamp(broker_receipt["requested_at"])
            <= _stamp(broker_receipt["received_at"])
            <= _stamp(received_at)
        ):
            raise ValueError("Daily broker receipt is outside the collection interval")
    calendar_error = None
    try:
        dates = calendar_dates(calendar_receipt, as_of, received_at)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as exc:
        dates, calendar_error = [], str(exc)[:200]
    details, indicators, missing_counts = {}, {}, Counter()
    for symbol in sorted(set(symbols)):
        rows, excluded = _normalize(bars.get(symbol, []) if isinstance(bars, dict) else [], dates)
        fields = {field: _field(field, dates, rows) for field in FIELDS}
        missing_counts.update(field for field, item in fields.items() if item["status"] != "known")
        details[symbol] = {"rows": rows, "fields": fields, "excluded": excluded}
        if rows:
            indicators[symbol] = {
                "asof": dates[-1],
                **{field: item["value"] for field, item in fields.items()},
            }
    payload = {
        "version": VERSION,
        "input_observed_at": observed_at,
        "received_at": received_at,
        "as_of": as_of,
        "expected_previous_session": dates[-1] if dates else None,
        "calendar": calendar_receipt,
        "calendar_error": calendar_error,
        "session_dates": dates,
        "source_metadata": source_metadata,
        "symbols": details,
    }
    digest = content_hash(payload)
    reference = "daily-inputs:" + digest
    receipt = {**payload, "sha256": digest}
    # An identical content-addressed receipt may be reused; never replace one.
    old = store.get(reference)
    if old is not None and old != receipt:
        raise ValueError("Daily input receipt is immutable")
    if old is None:
        store.db.execute("INSERT INTO kv VALUES(?,?)", (reference, dumps(receipt)))
    validation = {
        "version": VERSION,
        "as_of": as_of,
        "receipt_reference": reference,
        "sha256": digest,
        "expected_previous_session": dates[-1] if dates else None,
        "state": "unavailable" if not dates else "partial" if missing_counts else "ready",
        "field_missing_counts": dict(missing_counts),
        "calendar_error": calendar_error,
        "source": {key: source_metadata.get(key) for key in ("feed", "adjustment", "timeframe")},
    }
    return indicators, validation


def validate_daily_inputs(store, packet, symbol, fields, expected_previous, *, available_by=None):
    """Verify prospective feature values against the exact archived source receipt."""
    validation = packet.get("daily_input_validation") or {}
    reference = validation.get("receipt_reference")
    if validation.get("version") != VERSION or not isinstance(reference, str):
        raise ValueError("Daily inputs lack current calendar-validation receipt")
    receipt = store.get(reference)
    if not isinstance(receipt, dict):
        raise ValueError("Daily input source receipt is missing")
    payload = {key: value for key, value in receipt.items() if key != "sha256"}
    digest = content_hash(payload)
    if (
        receipt.get("version") != VERSION
        or receipt.get("sha256") != digest
        or validation.get("sha256") != digest
        or reference != "daily-inputs:" + digest
        or receipt.get("input_observed_at") != packet.get("observed_at")
        or receipt.get("expected_previous_session") != expected_previous
        or validation.get("expected_previous_session") != expected_previous
        or validation.get("as_of") != receipt.get("as_of")
    ):
        raise ValueError("Daily input lineage or previous broker session does not match")
    if available_by is not None and _stamp(receipt["received_at"]) > _stamp(available_by):
        raise ValueError("Daily input receipt was unavailable when the packet was archived")
    indicators = packet.get("daily_indicators", {}).get(symbol, {})
    if indicators.get("asof") != expected_previous:
        raise ValueError("Daily indicator session does not match its source receipt")
    recorded = receipt.get("symbols", {}).get(symbol, {}).get("fields", {})
    result = {}
    for field in fields:
        item = recorded.get(field, {})
        if item.get("status") != "known" or item.get("value") is None:
            raise ValueError("Daily feature " + field + " unavailable: " + str(item.get("reason")))
        if indicators.get(field) != item["value"]:
            raise ValueError("Daily feature differs from retained source calculation")
        result[field] = item["value"]
    return result


def snapshot_projection(snapshot, *, as_of, previous_session):
    """Provider bars are latest/second-latest, not necessarily today/yesterday."""
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    trade, quote = snapshot.get("latestTrade"), snapshot.get("latestQuote")
    result = {
        "trade": {
            k: v for k, v in (trade if isinstance(trade, dict) else {}).items() if k in ("p", "t")
        },
        "quote": {
            k: v
            for k, v in (quote if isinstance(quote, dict) else {}).items()
            if k in ("bp", "ap", "t")
        },
        "current_session_bar_close": None,
        "current_session_bar_at": None,
        "prior_close": None,
        "prior_close_at": None,
        "bar_basis": "Provider snapshot raw IEX bars; prior date matched to broker calendar. Daily indicators separately use all corporate-action adjustments.",
    }
    by_day, conflicts = {}, set()
    for key in ("dailyBar", "prevDailyBar"):
        bar = snapshot.get(key)
        if not isinstance(bar, dict):
            continue
        try:
            at = _stamp(bar["t"]).astimezone(ET)
            if (at.hour, at.minute, at.second, at.microsecond) != (0, 0, 0, 0):
                continue
            day = at.date().isoformat()
            close = _finite(bar.get("c"), positive=True)
            if close is None:
                continue
            if day in by_day and by_day[day][0] != close:
                conflicts.add(day)
            by_day[day] = (close, bar["t"])
        except (ValueError, TypeError, KeyError, OverflowError):
            continue
    for day, (close, at) in by_day.items():
        if day in conflicts:
            continue
        if day == as_of:
            result.update(current_session_bar_close=close, current_session_bar_at=at)
        if previous_session and day == previous_session:
            result.update(prior_close=close, prior_close_at=at)
    return result


def acquisition_interval(started_at, completed_at, sessions=()):
    """Describe when collection crossed session boundaries without retiming data."""
    started, completed = _stamp(started_at), _stamp(completed_at)
    if completed < started:
        raise ValueError("Collection completion precedes its start")
    opened, closed = [], []
    try:
        for session in sessions:
            opened.append(
                datetime.fromisoformat(session["date"] + "T" + session["open"]).replace(tzinfo=ET)
            )
            closed.append(
                datetime.fromisoformat(session["date"] + "T" + session["close"]).replace(tzinfo=ET)
            )
    except (TypeError, ValueError, KeyError):
        opened, closed = [], []
    return {
        "started_at": started_at,
        "completed_at": completed_at,
        "crossed_et_date": started.astimezone(ET).date() != completed.astimezone(ET).date(),
        "crossed_regular_open": any(started < at <= completed for at in opened) if opened else None,
        "crossed_regular_close": any(started < at <= completed for at in closed)
        if closed
        else None,
    }
