"""One prospective, read-only indicative-options coverage probe. No order authority."""

from __future__ import annotations

import math
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from .config import ET
from .observation_audit import content_hash
from .store import owner_is_dead, process_owner

VERSION = "etf-options-coverage-v1"
UNDERLYINGS = ("SPY", "QQQ")
GREEKS = ("delta", "gamma", "rho", "theta", "vega")
PROTOCOL = {
    "version": VERSION,
    "authority": "Coverage only; no orders, activation, promotion, fills or profitability inference.",
    "session": "First retained broker-calendar regular-session open strictly after registration; no rescheduling or backfill.",
    "windows": "Open+30m through +32m exclusive and open+45m through +47m exclusive; both send and receipt must be in window.",
    "denominator": "SPY and QQQ, one call and one put each, at both captures: eight expected observations even if selection fails.",
    "selection": "Initial fresh ordered positive IEX quote midpoint S; explicit7–14 calendar-day expiry and0.99*S..1.01*S strike band; complete metadata max2pages of1000 per ETF. Verified standard active tradable100-share contracts only. Earliest eligible expiry, nearest paired call/put strike to S, lower-strike tie. No later-expiry fallback; selection never uses IV/option quotes. Same pair retained at second capture.",
    "standardness": "Exact root/underlying and OCC symbol, size100, multiplier100, one equity deliverable of100 matching underlying, allocation100 and delayed_settlement=false. Missing fields are unknown, never assumed standard.",
    "requests": "At most12 lifetime HTTP attempts. First capture: underlying before1, metadata up to4, selected snapshots1, underlying after1, legacy chains2. Second: underlying before1, same selected snapshots1, underlying after1. Each slot reserved before sending; failures and unknown outcomes consume slots; no retries or transport retry.",
    "legacy": "Freeze the existing historical packet summary at registration. Optional slots are fixed here as enabled: first15 of each limit30 indicative chain during capture1, retained separately; never replace the historical packet.",
    "checks": "Quote finite0<bid<=ask, age at receipt−5..90seconds; report spread without equity0.5% gate. Match option quote to nearest bracketing underlying quote timestamp, earlier tie; gap<=30seconds reported separately. IV missing/nonfinite/zero/negative/positive are distinct; IV as-of is unknown. Positive-IV-with-quote-checks is coverage, not valid synchronized valuation.",
    "feed": "Alpaca free indicative options quotes are modified, not actual OPRA executable quotes; trades delayed. Underlying quotes IEX only. No paid feed fallback.",
}
PROTOCOL_SHA256 = content_hash(PROTOCOL)
REGISTRATION_KEY = "options_coverage_registration"


def _stamp(value):
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timestamp requires timezone")
    return result


def _number(value):
    if isinstance(value, bool) or value is None:
        raise ValueError("Missing numeric value")
    return float(value)


def _json_safe(value):
    # Preserve nonfinite provider values explicitly without invalid JSON storage.
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def iv_category(value):
    if value is None:
        return "missing"
    try:
        number = _number(value)
    except (TypeError, ValueError):
        return "invalid"
    if not math.isfinite(number):
        return "nonfinite"
    return "positive" if number > 0 else "negative" if number < 0 else "zero"


def quote_diagnostic(quote, received_at):
    result = {
        "status": "missing",
        "quote_at": None,
        "age_seconds": None,
        "finite_positive_ordered": False,
        "fresh": False,
        "spread_fraction": None,
    }
    if not isinstance(quote, dict):
        return result
    result["quote_at"] = quote.get("t")
    try:
        bid, ask = _number(quote.get("bp")), _number(quote.get("ap"))
        if not (math.isfinite(bid) and math.isfinite(ask) and 0 < bid <= ask):
            result["status"] = "invalid_prices"
            return result
        midpoint = bid + (ask - bid) / 2
        result.update(
            finite_positive_ordered=True, midpoint=midpoint, spread_fraction=(ask - bid) / midpoint
        )
        age = (_stamp(received_at) - _stamp(quote["t"])).total_seconds()
        result.update(
            age_seconds=age,
            fresh=-5 <= age <= 90,
            status="valid" if -5 <= age <= 90 else "outside_age_window",
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        result["status"] = "invalid_timestamp_or_prices"
    return result


def _symbol_parts(symbol):
    match = re.fullmatch(r"(SPY|QQQ)(\d{6})([CP])(\d{8})", str(symbol))
    if not match:
        return None
    try:
        return {
            "underlying": match[1],
            "expiry": datetime.strptime(match[2], "%y%m%d").date().isoformat(),
            "type": "call" if match[3] == "C" else "put",
            "strike": Decimal(match[4]) / 1000,
        }
    except ValueError:
        return None


def _coverage_counts(rows, observed_at):
    counts = {
        "contracts": len(rows),
        "call_count": 0,
        "put_count": 0,
        "same_day_expiry_count": 0,
        "valid_quotes": 0,
        "iv_categories": {},
        "finite_greek_fields": {key: 0 for key in GREEKS},
        "contracts_with_any_finite_greek": 0,
        "contracts_with_all_five_finite_greeks": 0,
    }
    try:
        day = _stamp(observed_at).astimezone(ET).date().isoformat()
    except (TypeError, ValueError):
        day = None
    categories = Counter()
    for row in rows:
        parts = _symbol_parts(row.get("symbol"))
        if parts:
            counts[parts["type"] + "_count"] += 1
            counts["same_day_expiry_count"] += parts["expiry"] == day
        quote = row.get("quote", row.get("latestQuote"))
        counts["valid_quotes"] += quote_diagnostic(quote, observed_at)["finite_positive_ordered"]
        categories[
            iv_category(
                row.get("impliedVolatility")
                if "impliedVolatility" in row
                else row.get("implied_volatility")
            )
        ] += 1
        greek_count = 0
        greeks = row.get("greeks") or {}
        for key in GREEKS:
            try:
                valid = math.isfinite(_number(greeks.get(key)))
            except (TypeError, ValueError, AttributeError):
                valid = False
            counts["finite_greek_fields"][key] += valid
            greek_count += valid
        counts["contracts_with_any_finite_greek"] += greek_count > 0
        counts["contracts_with_all_five_finite_greeks"] += greek_count == len(GREEKS)
    counts["iv_categories"] = dict(categories)
    counts["ordered_positive_quotes"] = counts["valid_quotes"]
    counts["valid_quotes_scope"] = (
        "Finite positive ordered prices only; historical freshness is not certified."
    )
    return counts


def register(store, calendar_receipt, *, registered_at, review):
    """Explicit reviewed one-time registration using retained broker-calendar evidence."""
    now = _stamp(registered_at)
    if (
        review.get("approved") is not True
        or review.get("protocol_sha256") != PROTOCOL_SHA256
        or not review.get("reviewer")
        or not review.get("validation")
    ):
        raise ValueError("Reviewed approval of the exact coverage protocol is required")
    sessions = calendar_receipt.get("sessions")
    if (
        not isinstance(sessions, list)
        or not sessions
        or calendar_receipt.get("sha256") != content_hash(sessions)
        or _stamp(calendar_receipt["observed_at"]) > now
        or calendar_receipt["requested_start"] > now.astimezone(ET).date().isoformat()
    ):
        raise ValueError("Complete retained broker-calendar evidence required")
    dates, future = set(), []
    for session in sessions:
        day = datetime.fromisoformat(session["date"]).date().isoformat()
        if day in dates or day != session["date"]:
            raise ValueError("Ambiguous broker calendar")
        dates.add(day)
        opened = datetime.fromisoformat(day + "T" + session["open"]).replace(tzinfo=ET)
        closed = datetime.fromisoformat(day + "T" + session["close"]).replace(tzinfo=ET)
        if closed <= opened:
            raise ValueError("Invalid broker session")
        if opened > now and closed > opened + timedelta(minutes=47):
            future.append((opened, closed))
    if not future:
        raise ValueError("No future eligible regular session in retained calendar")
    opened, closed = min(future)
    if calendar_receipt["requested_end"] < opened.date().isoformat():
        raise ValueError("Calendar coverage does not include selected session")
    old = store.get(REGISTRATION_KEY)
    if old:
        if (
            old.get("registered_at") == registered_at
            and old.get("review") == review
            and old.get("protocol_sha256") == PROTOCOL_SHA256
            and old.get("calendar_evidence") == calendar_receipt
        ):
            return old
        raise ValueError("Options coverage registration is immutable; no automatic extension")
    baseline = store.get("options_research", {})
    baseline_rows = baseline.get("contracts", [])
    baseline_summary = {
        "observed_at": baseline.get("observed_at"),
        "packet_sha256": content_hash(_json_safe(baseline)),
        **_coverage_counts(baseline_rows, baseline.get("observed_at")),
        "scope": "Historical sampler evidence only; original packet preserved.",
    }
    payload = {
        "version": VERSION,
        "registered_at": registered_at,
        "review": review,
        "protocol": PROTOCOL,
        "protocol_sha256": PROTOCOL_SHA256,
        "calendar_evidence": calendar_receipt,
        "session_day": opened.date().isoformat(),
        "opened": opened.isoformat(),
        "closed": closed.isoformat(),
        "baseline": baseline_summary,
        "captures": [
            {
                "slot": index + 1,
                "scheduled_at": (opened + timedelta(minutes=minute)).isoformat(),
                "deadline": (opened + timedelta(minutes=minute + 2)).isoformat(),
            }
            for index, minute in enumerate((30, 45))
        ],
    }
    receipt = {**payload, "registration_id": content_hash(payload)}
    with store.transaction():
        if store.get(REGISTRATION_KEY):
            raise ValueError("Coverage registration already exists")
        store.set(REGISTRATION_KEY, receipt)
        store.event(
            "options_coverage_registered",
            {
                "registration_id": receipt["registration_id"],
                "session_day": receipt["session_day"],
                "protocol_sha256": PROTOCOL_SHA256,
                "execution_eligible": False,
            },
        )
    return receipt


def _registration(store):
    receipt = store.get(REGISTRATION_KEY)
    if not receipt:
        return None
    if (
        receipt.get("protocol_sha256") != PROTOCOL_SHA256
        or content_hash(receipt.get("protocol")) != PROTOCOL_SHA256
        or content_hash({k: v for k, v in receipt.items() if k != "registration_id"})
        != receipt.get("registration_id")
    ):
        raise ValueError("Coverage protocol or immutable registration differs")
    return receipt


def _prefix(registration):
    return "options-coverage:" + registration["registration_id"] + ":"


def _requests(store, registration):
    import json

    return [
        json.loads(r["value"])
        for r in store.rows(
            "SELECT value FROM kv WHERE key LIKE ? ORDER BY key",
            (_prefix(registration) + "request:%",),
        )
    ]


def _request(store, registration, capture, slot, operation, call, clock):
    key = _prefix(registration) + "request:" + slot
    now = clock()
    with store.transaction():
        old = store.get(key)
        if old is not None:
            return old  # Reserved/failed outcomes cannot spend this slot again.
        if not _stamp(capture["scheduled_at"]) <= now < _stamp(capture["deadline"]):
            return None
        if len(_requests(store, registration)) >= 12:
            return None
        reserved = {
            "slot": slot,
            "capture": capture["slot"],
            "state": "reserved",
            "reserved_at": now.isoformat(),
            "requested_at": None,
            "operation": operation,
        }
        store.set(key, reserved)
    dispatch = clock()
    if not _stamp(capture["scheduled_at"]) <= dispatch < _stamp(capture["deadline"]):
        result = {**reserved, "state": "not_dispatched", "reason": "window_closed_before_dispatch"}
        with store.transaction():
            if store.get(key) != reserved:
                raise ValueError("Coverage request reservation changed")
            store.set(key, result)
        return result
    try:
        response = _json_safe(call())
        received = clock()
        result = {
            **reserved,
            "state": "received",
            "requested_at": dispatch.isoformat(),
            "received_at": received.isoformat(),
            "in_window": dispatch <= received < _stamp(capture["deadline"]),
            "response": response,
            "response_sha256": content_hash(response),
        }
    except Exception as exc:
        received = clock()
        result = {
            **reserved,
            "state": "error",
            "requested_at": dispatch.isoformat(),
            "received_at": received.isoformat(),
            "error_type": type(exc).__name__,
        }
    with store.transaction():
        current = store.get(key)
        if current != reserved:
            raise ValueError("Coverage request receipt changed while in flight")
        store.set(key, result)
    return result


def _received(receipt):
    return bool(
        receipt
        and receipt.get("state") == "received"
        and receipt.get("response_sha256") == content_hash(receipt.get("response"))
    )


def _usable(receipt):
    return bool(_received(receipt) and receipt.get("in_window"))


def _standard(contract, underlying, low, high, first_expiry, last_expiry):
    required = (
        "root_symbol",
        "underlying_symbol",
        "status",
        "tradable",
        "size",
        "multiplier",
        "deliverables",
        "symbol",
        "type",
        "strike_price",
        "expiration_date",
    )
    if not isinstance(contract, dict) or any(
        key not in contract or contract[key] is None for key in required
    ):
        return None, "standardness_unknown"
    try:
        strike = Decimal(str(contract["strike_price"]))
        deliverables = contract["deliverables"]
        if not isinstance(deliverables, list) or len(deliverables) != 1:
            return None, "nonstandard_deliverable"
        deliverable = deliverables[0]
        if not all(
            key in deliverable and deliverable[key] is not None
            for key in ("type", "symbol", "amount", "allocation_percentage", "delayed_settlement")
        ):
            return None, "standardness_unknown"
        parts = _symbol_parts(contract["symbol"])
        if (
            contract["root_symbol"] != underlying
            or contract["underlying_symbol"] != underlying
            or contract["status"] != "active"
            or contract["tradable"] is not True
            or Decimal(str(contract["size"])) != 100
            or Decimal(str(contract["multiplier"])) != 100
            or deliverable["type"] != "equity"
            or deliverable["symbol"] != underlying
            or Decimal(str(deliverable["amount"])) != 100
            or Decimal(str(deliverable["allocation_percentage"])) != 100
            or deliverable["delayed_settlement"] is not False
        ):
            return None, "not_verified_standard_eligible"
        if (
            not strike.is_finite()
            or not low <= strike <= high
            or not parts
            or parts
            != {
                "underlying": underlying,
                "expiry": contract["expiration_date"],
                "type": contract["type"],
                "strike": strike,
            }
            or not first_expiry <= contract["expiration_date"] <= last_expiry
        ):
            return None, "metadata_identity_or_scope_mismatch"
        return {
            "symbol": contract["symbol"],
            "type": contract["type"],
            "expiry": contract["expiration_date"],
            "strike": str(strike),
        }, None
    except (TypeError, ValueError, KeyError, InvalidOperation):
        return None, "standardness_unknown"


def _select(store, broker, registration, capture, underlying, before, clock):
    key = _prefix(registration) + "selection:" + underlying
    old = store.get(key)
    if old is not None:
        return old
    result = {
        "underlying": underlying,
        "state": "unavailable",
        "reason": "initial_underlying_quote_unavailable",
    }
    quote = (
        before.get("response", {}).get(underlying)
        if _usable(before) and isinstance(before.get("response"), dict)
        else None
    )
    diagnostic = quote_diagnostic(quote, before.get("received_at") if before else None)
    if diagnostic["status"] == "valid":
        price = Decimal(str(diagnostic["midpoint"]))
        low, high = price * Decimal(".99"), price * Decimal("1.01")
        day = datetime.fromisoformat(registration["session_day"]).date()
        first, last = (day + timedelta(days=7)).isoformat(), (day + timedelta(days=14)).isoformat()
        result.update(
            selection_underlying_mid=float(price),
            selection_quote_at=quote["t"],
            metadata_exclusions={},
        )
        contracts, tokens, symbols, complete = [], set(), set(), False
        token = None
        for page in (1, 2):
            receipt = _request(
                store,
                registration,
                capture,
                f"metadata:{underlying}:{page}",
                {
                    "method": "GET",
                    "path": "/v2/options/contracts",
                    "underlying": underlying,
                    "page": page,
                    "expiration_date_gte": first,
                    "expiration_date_lte": last,
                    "strike_price_gte": str(low),
                    "strike_price_lte": str(high),
                },
                lambda: broker.option_contracts_page(
                    underlying, first, last, str(low), str(high), page_token=token
                ),
                clock,
            )
            if not _usable(receipt):
                result["reason"] = "metadata_request_unknown_failed_or_late"
                break
            payload = receipt["response"]
            rows = payload.get("option_contracts") if isinstance(payload, dict) else None
            if not isinstance(rows, list) or len(rows) > 1000 or "next_page_token" not in payload:
                result["reason"] = "metadata_malformed"
                break
            if any(
                not isinstance(row, dict)
                or not isinstance(row.get("symbol"), str)
                or row["symbol"] in symbols
                for row in rows
            ):
                result["reason"] = "metadata_duplicate_or_missing_identity"
                break
            if len({row["symbol"] for row in rows}) != len(rows):
                result["reason"] = "metadata_duplicate_or_missing_identity"
                break
            symbols.update(row["symbol"] for row in rows)
            contracts.extend(rows)
            token = payload.get("next_page_token")
            if token is None or token == "":
                complete = True
                break
            if not isinstance(token, str) or token in tokens:
                result["reason"] = "metadata_pagination_invalid"
                break
            tokens.add(token)
            result["reason"] = "metadata_pagination_incomplete"
        if complete:
            eligible, exclusions = [], Counter()
            for contract in contracts:
                item, reason = _standard(contract, underlying, low, high, first, last)
                if item:
                    eligible.append(item)
                else:
                    exclusions[reason] += 1
            result.update(
                metadata_complete=True,
                metadata_contracts=len(contracts),
                metadata_exclusions=dict(exclusions),
            )
            if not eligible:
                result["reason"] = "no_verified_standard_contracts"
            else:
                expiry = min(row["expiry"] for row in eligible)
                pairs = {}
                for row in eligible:
                    if row["expiry"] == expiry:
                        pairs.setdefault(Decimal(row["strike"]), {})[row["type"]] = row["symbol"]
                paired = [strike for strike, pair in pairs.items() if set(pair) == {"call", "put"}]
                if not paired:
                    result.update(expiry=expiry, reason="earliest_expiry_has_no_paired_strike")
                else:
                    strike = min(paired, key=lambda value: (abs(value - price), value))
                    result.update(
                        state="selected",
                        reason="metadata_only_selection",
                        expiry=expiry,
                        strike=str(strike),
                        call=pairs[strike]["call"],
                        put=pairs[strike]["put"],
                    )
    if clock() >= _stamp(capture["deadline"]) and result["state"] == "selected":
        result = {
            "underlying": underlying,
            "state": "unavailable",
            "reason": "selection_deadline_missed",
        }
    with store.transaction():
        if store.get(key) is not None:
            return store.get(key)
        store.set(key, {**result, "selected_at": clock().isoformat()})
    return store.get(key)


def _observations(selection, snapshots, before, after):
    rows = []
    payload = snapshots.get("response", {}) if _received(snapshots) else {}
    requested = {
        selected[kind]
        for selected in selection.values()
        if selected.get("state") == "selected"
        for kind in ("call", "put")
    }
    complete = (
        isinstance(payload, dict)
        and not payload.get("next_page_token")
        and isinstance(payload.get("snapshots"), dict)
        and set(payload["snapshots"]) <= requested
    )
    for underlying in UNDERLYINGS:
        selected = selection.get(underlying, {})
        for kind in ("call", "put"):
            symbol = selected.get(kind) if selected.get("state") == "selected" else None
            item = payload["snapshots"].get(symbol) if complete and symbol else None
            present = isinstance(item, dict)
            item = item if isinstance(item, dict) else {}
            quote = item.get("latestQuote")
            diag = quote_diagnostic(quote, snapshots.get("received_at") if snapshots else None)
            candidates = []
            for source in (before, after):
                if _usable(source) and isinstance(source.get("response"), dict):
                    underlying_quote = source["response"].get(underlying)
                    check = quote_diagnostic(underlying_quote, source["received_at"])
                    try:
                        gap = abs(
                            (_stamp(diag["quote_at"]) - _stamp(check["quote_at"])).total_seconds()
                        )
                        candidates.append((gap, _stamp(check["quote_at"]), check))
                    except (ValueError, TypeError):
                        pass
            matched = (
                min(candidates, key=lambda value: (value[0], value[1])) if candidates else None
            )
            iv = iv_category(item.get("impliedVolatility")) if present else "unobserved"
            checks = bool(
                complete
                and _usable(snapshots)
                and _usable(before)
                and _usable(after)
                and diag["status"] == "valid"
                and matched
                and matched[0] <= 30
                and matched[2]["status"] == "valid"
            )
            rows.append(
                {
                    "underlying": underlying,
                    "type": kind,
                    "symbol": symbol,
                    "quote_status": "late_receipt"
                    if present and not _usable(snapshots)
                    else diag["status"],
                    "quote_value_status": diag["status"],
                    "receipt_in_window": _usable(snapshots),
                    "quote_at": diag["quote_at"],
                    "receipt_at": snapshots.get("received_at") if snapshots else None,
                    "quote_age_seconds": diag["age_seconds"],
                    "spread_fraction": diag["spread_fraction"],
                    "underlying_quote_at": matched[2]["quote_at"] if matched else None,
                    "timestamp_gap_seconds": matched[0] if matched else None,
                    "bracketing_underlying_receipts_complete": _usable(before) and _usable(after),
                    "iv_category": iv,
                    "iv_asof": "unknown_not_provided_by_provider",
                    "positive_iv_with_quote_checks": iv == "positive" and checks,
                    "snapshot_present": present,
                    "reason": selected.get("reason")
                    if not symbol
                    else (
                        "coverage_only"
                        if complete and _usable(snapshots)
                        else "snapshot_request_unknown_failed_late_or_incomplete"
                    ),
                }
            )
    return rows


def _capture_result(store, registration, capture, now, state, reason=None):
    prefix = _prefix(registration)
    slot = capture["slot"]
    selection = {
        u: store.get(
            prefix + "selection:" + u,
            {
                "underlying": u,
                "state": "unavailable",
                "reason": "first_capture_selection_unavailable",
            },
        )
        for u in UNDERLYINGS
    }
    snapshots = store.get(prefix + f"request:{slot}:selected_snapshots")
    before = store.get(prefix + f"request:{slot}:underlying_before")
    after = store.get(prefix + f"request:{slot}:underlying_after")
    observations = _observations(selection, snapshots, before, after)
    comparator = []
    if slot == 1:
        for underlying in UNDERLYINGS:
            receipt = store.get(prefix + "request:legacy:" + underlying)
            if (
                _usable(receipt)
                and isinstance(receipt["response"], dict)
                and isinstance(receipt["response"].get("snapshots"), dict)
            ):
                rows = [
                    {"symbol": symbol, **item}
                    for symbol, item in list(receipt["response"]["snapshots"].items())[:15]
                    if isinstance(item, dict)
                ]
                comparator.append(
                    {
                        "underlying": underlying,
                        "scope": "First15 of limit30 legacy chain; intentionally incomplete sampler comparator.",
                        "received_at": receipt["received_at"],
                        **_coverage_counts(rows, receipt["received_at"]),
                    }
                )
    return {
        **capture,
        "state": state,
        "reason": reason,
        "completed_at": now.isoformat(),
        "expected_contracts": 4,
        "received_snapshots": sum(row["snapshot_present"] for row in observations),
        "observations": observations,
        "iv_categories": dict(Counter(row["iv_category"] for row in observations)),
        "legacy_comparator": comparator,
    }


def due_capture(store, now):
    registration = _registration(store)
    if not registration:
        return None
    for capture in registration["captures"]:
        key = _prefix(registration) + "capture:" + str(capture["slot"])
        with store.transaction():
            old = store.get(key)
            if old and old.get("state") in ("completed", "missed", "interrupted"):
                continue
            if now >= _stamp(capture["deadline"]):
                if not old or old.get("state") != "running" or owner_is_dead(old.get("owner")):
                    state = "interrupted" if old else "missed"
                    store.set(
                        key,
                        _capture_result(
                            store,
                            registration,
                            capture,
                            now,
                            state,
                            "capture_deadline_missed_no_backfill",
                        ),
                    )
                continue
            if now >= _stamp(capture["scheduled_at"]):
                return capture["slot"]
    return None


def session_confirmation_reason(store, registration, now):
    if now.astimezone(ET).date().isoformat() != registration["session_day"]:
        return "session_day_mismatch"
    if store.get("market_open") is not True:
        return "broker_session_not_confirmed"
    calendar = store.get("calendar:" + registration["session_day"], [])
    if len(calendar) != 1:
        return "calendar_incompatibility"
    try:
        current_open = datetime.fromisoformat(
            registration["session_day"] + "T" + calendar[0]["open"]
        ).replace(tzinfo=ET)
        current_close = datetime.fromisoformat(
            registration["session_day"] + "T" + calendar[0]["close"]
        ).replace(tzinfo=ET)
        if current_open != _stamp(registration["opened"]) or current_close != _stamp(
            registration["closed"]
        ):
            return "calendar_incompatibility"
        rows = store.rows(
            "SELECT at FROM session_health WHERE day=? AND broker_confirmed=1 ORDER BY at DESC LIMIT 1",
            (registration["session_day"],),
        )
        return (
            None
            if rows and 0 <= (now - _stamp(rows[0]["at"])).total_seconds() <= 90
            else "broker_confirmation_stale_or_missing"
        )
    except (KeyError, TypeError, ValueError):
        return "calendar_incompatibility"


def capture_admission(store, now):
    registration = _registration(store)
    slot = due_capture(store, now)
    if slot is None:
        return None
    reason = session_confirmation_reason(store, registration, now)
    if reason in ("calendar_incompatibility", "session_day_mismatch"):
        capture = registration["captures"][slot - 1]
        key = _prefix(registration) + "capture:" + str(slot)
        with store.transaction():
            old = store.get(key)
            if not old or old.get("state") != "running" or owner_is_dead(old.get("owner")):
                store.set(key, _capture_result(store, registration, capture, now, "missed", reason))
        return None
    return slot if reason is None else None


def _collect_capture(store, broker, registration, capture, clock):
    slot = capture["slot"]
    prefix = _prefix(registration)
    if slot == 2 and not any(
        store.get(prefix + "selection:" + u, {}).get("state") == "selected" for u in UNDERLYINGS
    ):
        return  # No first-window selection: no replacement pair or dependent requests.
    before = _request(
        store,
        registration,
        capture,
        f"{slot}:underlying_before",
        {"method": "GET", "path": "/v2/stocks/quotes/latest", "feed": "iex"},
        lambda: broker.quotes(UNDERLYINGS),
        clock,
    )
    selection = {}
    for underlying in UNDERLYINGS:
        if slot == 1:
            selection[underlying] = _select(
                store, broker, registration, capture, underlying, before, clock
            )
        else:
            selection[underlying] = store.get(
                prefix + "selection:" + underlying,
                {
                    "underlying": underlying,
                    "state": "unavailable",
                    "reason": "first_capture_selection_unavailable",
                },
            )
    symbols = sorted(
        selected[kind]
        for selected in selection.values()
        if selected.get("state") == "selected"
        for kind in ("call", "put")
    )
    if symbols:
        _request(
            store,
            registration,
            capture,
            f"{slot}:selected_snapshots",
            {
                "method": "GET",
                "path": "/v1beta1/options/snapshots",
                "feed": "indicative",
                "symbols": symbols,
            },
            lambda: broker.option_snapshots(symbols),
            clock,
        )
        _request(
            store,
            registration,
            capture,
            f"{slot}:underlying_after",
            {"method": "GET", "path": "/v2/stocks/quotes/latest", "feed": "iex"},
            lambda: broker.quotes(UNDERLYINGS),
            clock,
        )
    if slot == 1:
        for underlying in UNDERLYINGS:
            _request(
                store,
                registration,
                capture,
                "legacy:" + underlying,
                {
                    "method": "GET",
                    "path": "/v1beta1/options/snapshots/:underlying",
                    "underlying": underlying,
                    "feed": "indicative",
                    "limit": 30,
                },
                lambda: broker.option_chain(underlying),
                clock,
            )


def run_capture(store, broker, slot, *, clock=None):
    clock = clock or (lambda: datetime.now(timezone.utc))
    registration = _registration(store)
    if not registration or slot not in (1, 2):
        raise ValueError("Registered capture required")
    capture = registration["captures"][slot - 1]
    now = clock()
    if not _stamp(capture["scheduled_at"]) <= now < _stamp(capture["deadline"]):
        due_capture(store, now)
        return public_summary(store)
    key = _prefix(registration) + "capture:" + str(slot)
    run_id = str(uuid4())
    with store.transaction():
        old = store.get(key)
        if old and (
            old.get("state") in ("completed", "missed", "interrupted")
            or (old.get("state") == "running" and not owner_is_dead(old.get("owner")))
        ):
            return public_summary(store)
        confirmation_reason = session_confirmation_reason(store, registration, now)
        if confirmation_reason:
            store.set(
                key,
                _capture_result(store, registration, capture, now, "missed", confirmation_reason),
            )
            return public_summary(store)
        store.set(
            key,
            {
                **capture,
                "state": "running",
                "owner": process_owner("options_coverage"),
                "run_id": run_id,
            },
        )
    state, reason = "completed", None
    try:
        _collect_capture(store, broker, registration, capture, clock)
    except Exception as exc:
        state, reason = "interrupted", "capture_error:" + type(exc).__name__
    result = _capture_result(store, registration, capture, clock(), state, reason)
    with store.transaction():
        current = store.get(key)
        if current.get("run_id") != run_id:
            raise ValueError("Coverage capture ownership changed")
        store.set(key, result)
        store.event(
            "options_coverage_captured",
            {
                "slot": slot,
                "expected_contracts": 4,
                "received_snapshots": result["received_snapshots"],
                "execution_eligible": False,
            },
        )
    return public_summary(store)


def public_summary(store):
    try:
        registration = _registration(store)
    except (KeyError, ValueError, TypeError, AttributeError):
        return {
            "registered": False,
            "status": "invalid_registration",
            "scope": "coverage_only",
            "execution_eligible": False,
            "promotion_eligible": False,
            "limitations": ["Immutable registration validation failed; collection is held."],
        }
    if not registration:
        return {
            "registered": False,
            "scope": "coverage_only",
            "execution_eligible": False,
            "promotion_eligible": False,
        }
    requests = _requests(store, registration)
    selections = []
    for underlying in UNDERLYINGS:
        row = store.get(
            _prefix(registration) + "selection:" + underlying,
            {"underlying": underlying, "state": "awaiting_selection"},
        )
        selections.append({**row, "selection_sha256": content_hash(row)})
    captures = []
    for capture in registration["captures"]:
        row = store.get(
            _prefix(registration) + "capture:" + str(capture["slot"]),
            {**capture, "state": "pending", "expected_contracts": 4},
        )
        row = {key: value for key, value in row.items() if key not in ("owner", "run_id")}
        captures.append({**row, "capture_sha256": content_hash(row)})
    return {
        "registered": True,
        "version": VERSION,
        "protocol_sha256": PROTOCOL_SHA256,
        "registration_id": registration["registration_id"],
        "registered_at": registration["registered_at"],
        "session_day": registration["session_day"],
        "scope": "coverage_only",
        "execution_eligible": False,
        "promotion_eligible": False,
        "request_budget": {
            "limit": 12,
            "reserved": len(requests),
            "remaining": 12 - len(requests),
            "unknown_outcomes": sum(r["state"] == "reserved" for r in requests),
            "failed": sum(r["state"] == "error" for r in requests),
            "late": sum(r["state"] == "received" and not r["in_window"] for r in requests),
        },
        "expected_observations": 8,
        "baseline": registration["baseline"],
        "selection": selections,
        "captures": captures,
        "limitations": [
            PROTOCOL["authority"],
            PROTOCOL["feed"],
            "IV and Greek as-of timestamps are not supplied; quote checks cannot certify synchronized valuation.",
            "Missing or late observations are unknown, never zeros or reconstructed observations.",
        ],
    }
