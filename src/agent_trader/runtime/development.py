"""Measure deployed research mechanics on later sessions without claiming an edge."""

from __future__ import annotations

import json
import math
from collections import Counter
from datetime import date, datetime, timedelta, timezone

from .config import ET
from .store import dumps, utc_now


def _time(value):
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return stamp.astimezone(timezone.utc) if stamp.tzinfo else None
    except (ValueError, TypeError):
        return None


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _session(store, day):
    calendar = store.get("calendar:" + day, [])
    try:
        row = next(r for r in calendar if r.get("date", day) == day)
        opened = datetime.fromisoformat(day + "T" + row["open"]).replace(tzinfo=ET)
        closed = datetime.fromisoformat(day + "T" + row["close"]).replace(tzinfo=ET)
        return (opened, closed) if closed > opened else None
    except (KeyError, ValueError, StopIteration, TypeError):
        return None


def _source_check(card):
    basis = card.get("evidence_basis", "external")
    urls = set(card.get("source_urls", [])) or {
        s.get("url") for s in card.get("sources", []) if s.get("url")
    }
    checked = set(card.get("checked_source_urls", []))
    external = card.get("source_check_status") == "verified" and bool(urls) and checked == urls
    local = (
        bool(card.get("observation_provenance_verified"))
        and card.get("method_check_status") == "reviewed"
    )
    if basis == "local_observation" and not urls:
        return local and card.get("source_check_status") == "not_applicable" and not checked
    return external and (local if basis in ("mixed", "local_observation") else True)


def _feature_check(inputs, opened, closed):
    metrics = {
        "research_packets": len(inputs),
        "packets_with_exact_daily_features": 0,
        "regular_session_packets": 0,
        "packets_with_fresh_completed_minutes": 0,
        "fresh_minute_symbols": 0,
        "daily_feature_symbols": 0,
    }
    for record in inputs:
        packet = record.get("packet", {})
        at = _time(packet.get("observed_at") or record.get("observed_at"))
        daily = packet.get("daily_indicators", {})
        complete = [
            symbol
            for symbol, item in daily.items()
            if _finite(item.get("return_1d")) and _finite(item.get("return_3d"))
        ]
        metrics["daily_feature_symbols"] += len(complete)
        metrics["packets_with_exact_daily_features"] += bool(complete)
        if not at or not opened + timedelta(minutes=5) <= at < closed:
            continue
        metrics["regular_session_packets"] += 1
        fresh = []
        for symbol, item in packet.get("intraday_indicators", {}).items():
            asof = _time(item.get("asof"))
            if (
                asof
                and opened < asof <= at
                and (at - asof).total_seconds() <= 120
                and _finite(item.get("last_completed_close"))
                and item["last_completed_close"] > 0
                and _finite(item.get("bar_vwap_iex"))
                and item["bar_vwap_iex"] > 0
                and item.get("opening_5m_complete")
                and item.get("missing_minute_intervals") == 0
            ):
                fresh.append(symbol)
        metrics["fresh_minute_symbols"] += len(fresh)
        metrics["packets_with_fresh_completed_minutes"] += bool(fresh)
    if not inputs:
        return (
            "awaiting_observation",
            metrics,
            "No full post-change research input packet is retained for this completed session.",
        )
    if metrics["packets_with_exact_daily_features"] < len(inputs):
        return (
            "needs_attention",
            metrics,
            "At least one research packet lacks any exact one-/three-session daily feature pair; inspect provider coverage and collection failures.",
        )
    if not metrics["regular_session_packets"]:
        return (
            "awaiting_observation",
            metrics,
            "Exact daily features were observed; no regular-session research packet yet tests live minute features.",
        )
    if metrics["packets_with_fresh_completed_minutes"] < metrics["regular_session_packets"]:
        return (
            "needs_attention",
            metrics,
            "At least one regular-session packet lacks usable fresh completed-minute context; this is an input gap, not a strategy verdict.",
        )
    return (
        "observed_mechanics",
        metrics,
        "Exact daily features and some fresh completed-minute context reached retained research packets. Coverage counts do not establish accuracy of decisions or profitability.",
    )


def assess_changes(store, day, persist=False):
    """Assess only completed actual sessions strictly after a dated fix receipt.

    Count coverage establishes retained mechanics, not causal treatment effects.
    Historical imports, manual probes, missing dates and still-open sessions never
    become evidence that a deployed change improved live research.
    """
    date.fromisoformat(day)
    now = _time(utc_now())
    session = _session(store, day)
    artifacts = [
        json.loads(r["payload"])
        for r in store.rows(
            "SELECT payload FROM memory WHERE layer='research_artifact' AND json_extract(payload,'$.day')=?",
            (day,),
        )
    ]
    usage = store.rows("SELECT at,role,payload FROM usage WHERE day=?", (day,))
    completed_calls = [
        r
        for r in usage
        if r["role"] == "research"
        and json.loads(r["payload"]).get("state", "completed") == "completed"
    ]
    live_research = [
        a
        for a in artifacts
        if a.get("role") == "research"
        and a.get("origin") == "live_task"
        and a.get("outcome") in ("applied", "rejected")
        and isinstance(a.get("result"), dict)
        and "summary" in a["result"]
        and "plans" in a["result"]
    ]
    changes = []
    for row in store.rows("SELECT key,value FROM kv WHERE key LIKE 'quality-fix:%' ORDER BY key"):
        identity = row["key"].split(":", 1)[1]
        receipt = json.loads(row["value"])
        fixed = _time(receipt.get("at"))
        proposal_id = "quality-proposal:" + identity
        original = store.rows("SELECT payload FROM memory WHERE id=?", (proposal_id,))
        proposal = json.loads(original[0]["payload"]) if original else {}
        result = {
            "id": identity,
            "state": "awaiting_observation",
            "assessed_day": day,
            "assessed_at": now.isoformat(),
            "fix_at": receipt.get("at"),
            "source_commit": receipt.get("source_commit"),
            "evidence_day": None,
            "baseline": {
                "evidence_day": proposal.get("baseline_evidence_day", proposal.get("evidence_day")),
                "problem": proposal.get("baseline_problem", proposal.get("problem")),
                "verification": receipt.get("verification"),
            },
            "metrics": {},
            "reason": "Awaiting a completed research session after the dated code change.",
            "scope": "Observed software/data mechanics only; not a measured investment improvement or a controlled causal comparison.",
        }
        eligible = bool(
            fixed
            and day > fixed.astimezone(ET).date().isoformat()
            and session
            and now >= session[1]
        )
        calls = [
            r for r in completed_calls if fixed and _time(r["at"]) and fixed < _time(r["at"]) <= now
        ]
        outputs = [
            a
            for a in live_research
            if fixed and _time(a.get("observed_at")) and fixed < _time(a["observed_at"]) <= now
        ]
        if not fixed:
            result["reason"] = (
                "Fix receipt lacks an aware deployment timestamp; no post-change effect can be attributed."
            )
        elif eligible and (calls or outputs):
            result["evidence_day"] = day
            if identity == "artifact_history":
                result["metrics"] = {
                    "completed_live_research_calls": len(calls),
                    "full_live_research_artifacts": len(outputs),
                    "applied": sum(a["outcome"] == "applied" for a in outputs),
                    "rejected": sum(a["outcome"] == "rejected" for a in outputs),
                    "legacy_or_nonlive_outputs_excluded": sum(
                        a.get("role") == "research" and a.get("origin") != "live_task"
                        for a in artifacts
                    ),
                }
                result["state"] = (
                    "observed_mechanics"
                    if calls and len(calls) == len(outputs)
                    else "needs_attention"
                )
                result["reason"] = (
                    "Completed research calls and full applied/rejected artifacts have matching counts; count coverage is not per-call identity proof."
                    if result["state"] == "observed_mechanics"
                    else "Completed research-call and retained-full-output counts differ; investigate missing capture or usage attribution."
                )
            elif identity == "source_verification":
                reviewed = [
                    c
                    for c in store.get("research_catalogue", [])
                    if c.get("state") == "reviewed_for_testing"
                ]
                weak = [c.get("id") for c in reviewed if not _source_check(c)]
                result["metrics"] = {
                    "current_reviewed_cards": len(reviewed),
                    "cards_missing_required_attestations": len(weak),
                    "weak_card_ids": weak[:12],
                    "catalogue_as_of": now.isoformat(),
                }
                result["state"] = (
                    "needs_attention"
                    if weak
                    else "observed_mechanics"
                    if reviewed
                    else "awaiting_observation"
                )
                result["reason"] = (
                    "Current reviewed catalogue satisfies required external-source or local-observation/method attestations. These are not automatic content authentication."
                    if reviewed and not weak
                    else "Reviewed catalogue is empty or required source/local-method attestations are missing."
                )
            elif identity == "missing_price_features":
                inputs = [
                    json.loads(r["payload"])
                    for r in store.rows(
                        "SELECT payload FROM memory WHERE layer='research_input' AND json_extract(payload,'$.day')=?",
                        (day,),
                    )
                ]
                linked = {_time(a.get("input_observed_at")) for a in outputs}
                inputs = [
                    r
                    for r in inputs
                    if _time(r.get("observed_at")) in linked
                    and _time(r.get("observed_at"))
                    and fixed < _time(r["observed_at"]) <= now
                ]
                result["state"], result["metrics"], result["reason"] = _feature_check(
                    inputs, *session
                )
            elif identity == "duplicate_period_reviews":
                derived = [
                    a
                    for a in artifacts
                    if a.get("origin") == "derived_period_review"
                    and a.get("role") in ("weekly", "monthly")
                ]
                valid = [
                    a
                    for a in derived
                    if a.get("result", {}).get("derived_from")
                    and a["result"].get("independent_model_review") is False
                    and a["result"].get("scope_note")
                ]
                result["metrics"] = {
                    "derived_rollups": len(derived),
                    "explicitly_labeled_derived_rollups": len(valid),
                }
                result["state"] = (
                    "needs_attention"
                    if len(valid) != len(derived)
                    else "observed_mechanics"
                    if valid
                    else "awaiting_observation"
                )
                result["reason"] = (
                    "Derived period rollups explicitly identify reuse and scope; this does not measure review quality or classify independent reviews as waste."
                    if valid
                    else "No derived rollup was observed; independent reviews may appropriately have broader evidence windows."
                )
            elif identity == "stale_pulses":
                pulses = [
                    a
                    for a in artifacts
                    if a.get("role") == "pulse"
                    and a.get("origin") == "live_task"
                    and a.get("outcome") == "applied"
                ]
                result["metrics"] = {
                    "applied_live_pulses": len(pulses),
                    "declared_material_changes": sum(
                        bool(a.get("result", {}).get("material_change")) for a in pulses
                    ),
                }
                result["reason"] = (
                    "Pulse usefulness and freshness need matched evidence review; a no-material-change answer or abstention is not classified as failure."
                )
            else:
                result["reason"] = (
                    "No deterministic effect criterion is registered for this change; developer review is required."
                )
        changes.append(result)
        if persist:
            previous = store.get("development-effect:" + identity, {})
            if (
                previous.get("fix_at") == receipt.get("at")
                and previous.get("assessed_day", "") > day
            ):
                continue  # Historical audits cannot overwrite a later effect receipt.
            store.set("development-effect:" + identity, result)
            if original:
                merged = {**proposal, "state": result["state"], "development_effect": result}
                merged.setdefault("state_before_effect_assessment", proposal.get("state"))
                store.db.execute(
                    "UPDATE memory SET payload=? WHERE id=?", (dumps(merged), proposal_id)
                )
    report = {
        "day": day,
        "as_of": now.isoformat(),
        "scope": "Post-change mechanics, evaluated only on completed later research sessions; no profitability claim.",
        "changes": changes,
        "state_counts": dict(Counter(c["state"] for c in changes)),
    }
    if persist:
        store.set("development-effects:" + day, report)
    return report
