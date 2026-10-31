"""Daily evidence-quality audit and durable development backlog; no order authority."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime

from .config import ET
from .store import utc_now

ROLES = {
    "research",
    "pulse",
    "exploration",
    "research_validation",
    "retrospective",
    "weekly",
    "monthly",
}


def record_artifact(
    store, day, role, result, task_key, outcome="applied", origin="live_task", observed_at=None
):
    if role not in ROLES:
        return
    captured_at = observed_at or utc_now()
    identity = hashlib.sha256((task_key + ":" + outcome + ":" + captured_at).encode()).hexdigest()[
        :24
    ]
    store.memory_put(
        "research-artifact:" + identity,
        "research_artifact",
        {
            "id": identity,
            "day": day,
            "role": role,
            "task_key": task_key,
            "outcome": outcome,
            "origin": origin,
            "observed_at": captured_at,
            "result": result,
            "input_observed_at": store.get("market_packet", {}).get("observed_at")
            if role == "research"
            else None,
        },
    )


def import_legacy_snapshots(store, day):
    """Import only surviving outputs, never invent overwritten research history."""
    if store.get("quality-legacy-import:" + day):
        return
    if store.get("brief_day") == day and store.get("brief"):
        brief = store.get("brief")
        rows = store.rows(
            "SELECT at FROM events WHERE kind='research_completed' AND json_extract(payload,'$.summary')=? ORDER BY id DESC LIMIT 1",
            (brief.get("summary"),),
        )
        record_artifact(
            store,
            day,
            "research",
            brief,
            "legacy:brief:" + day,
            origin="legacy_latest_snapshot",
            observed_at=rows[0]["at"] if rows else None,
        )
    for p in store.get("pulses", []):
        if p.get("at") and datetime.fromisoformat(p["at"]).astimezone(ET).date().isoformat() == day:
            record_artifact(
                store,
                day,
                "pulse",
                p,
                "legacy:pulse:" + p["at"],
                origin="legacy_snapshot",
                observed_at=p["at"],
            )
    report = store.get("exploration_report", {})
    if report.get("day") == day:
        record_artifact(
            store,
            day,
            "exploration",
            report,
            "legacy:exploration:" + day,
            origin="legacy_snapshot",
            observed_at=report.get("validated_at"),
        )
        if report.get("validation"):
            record_artifact(
                store,
                day,
                "research_validation",
                report["validation"],
                "legacy:validation:" + day,
                origin="legacy_snapshot",
                observed_at=report.get("validated_at"),
            )
    store.set("quality-legacy-import:" + day, True)


def daily_audit(store, day, persist=False):
    artifacts = [
        json.loads(r["payload"])
        for r in store.rows(
            "SELECT payload FROM memory WHERE layer='research_artifact' AND json_extract(payload,'$.day')=? ORDER BY at",
            (day,),
        )
    ]
    usage = store.rows(
        "SELECT role,input_tokens,cached_tokens,output_tokens,payload FROM usage WHERE day=?",
        (day,),
    )
    calls = Counter(r["role"] for r in usage)
    role_outputs = Counter(a["role"] for a in artifacts if a["outcome"] == "applied")
    patterns = {
        "price_structure": r"opening range|vwap|entry structure|entry level",
        "exact_daily_features": r"exact three|three-session|three.session return",
        "event_coverage": r"earnings|event timing|calendar|release timing",
        "source_access": r"403|not independently|not.*verified|source.*unavailable",
        "stale_data": r"stale|two calendar days old",
    }
    blockers = Counter()
    urls = set()
    for a in artifacts:
        r = a["result"]
        if not isinstance(r, dict):
            continue
        text = " ".join(r.get("unknowns", []) + r.get("uncertainties", []))
        for name, pattern in patterns.items():
            if re.search(pattern, text, re.I):
                blockers[name] += 1
        urls.update(s["url"] for s in r.get("sources", []) if s.get("url"))
    catalogue = store.get("research_catalogue", [])
    reviewed = [c for c in catalogue if c.get("state") == "reviewed_for_testing"]
    unattested = [c["id"] for c in reviewed if c.get("source_check_status") != "verified"]
    known_no_plan = sum(
        a["role"] == "research"
        and a["outcome"] == "applied"
        and isinstance(a["result"], dict)
        and not a["result"].get("plans")
        for a in artifacts
    )
    pulse_outputs = [
        a
        for a in artifacts
        if a["role"] == "pulse" and a["outcome"] == "applied" and isinstance(a["result"], dict)
    ]
    no_verified_delta = sum(not a["result"].get("material_change") for a in pulse_outputs)
    raw_tokens = sum(r["input_tokens"] for r in usage)
    measured = {
        "calls": len(usage),
        "by_role": dict(calls),
        "input_tokens": raw_tokens,
        "cached_input_tokens": sum(r["cached_tokens"] for r in usage),
        "output_tokens": sum(r["output_tokens"] for r in usage),
        "web_actions": sum(json.loads(r["payload"]).get("searches", 0) for r in usage),
        "unreported_attempts": sum(
            json.loads(r["payload"]).get("state") in ("started", "failed") for r in usage
        ),
    }
    candidates = []

    def finding(identity, problem, change, validation, priority="normal"):
        fix = store.get("quality-fix:" + identity)
        candidates.append(
            {
                "id": identity,
                "priority": priority,
                "problem": problem,
                "requested_change": change,
                "validation_plan": validation,
                "state": "code_changed_awaiting_observation" if fix else "proposed",
                "code_receipt": fix,
            }
        )

    if blockers["price_structure"] or blockers["exact_daily_features"]:
        finding(
            "missing_price_features",
            "Research reports missing price structure or exact daily inputs.",
            "Supply exact completed daily returns and timestamped IEX minute-bar ranges/volume/VWAP with missingness.",
            "Verify calculations, exclusion of incomplete/future bars, pagination and use in actual next-session research.",
            "high",
        )
    if unattested:
        finding(
            "source_verification",
            "Reviewed catalogue cards lack explicit independent source-check attestations: "
            + str(len(unattested)),
            "Require explicit verified source status and checked URLs; hold incomplete checks and re-review legacy cards.",
            "Confirm unverified/partial/missing attestations cannot authorize research reuse or new experiment registration.",
            "high",
        )
    if len(pulse_outputs) >= 2 and no_verified_delta == len(pulse_outputs):
        finding(
            "stale_pulses",
            "All archived intraday pulses reported no verified material update.",
            "Give pulses current time, latest verified updates and focused symbols; reduce no-exposure repetition.",
            "Compare verified deltas, explicit unknowns, prompt length and actual web actions over matched sessions.",
        )
    if calls["research"] > role_outputs["research"]:
        finding(
            "artifact_history",
            "Full research outputs available: "
            + str(role_outputs["research"])
            + " for "
            + str(calls["research"])
            + " measured research calls.",
            "Archive every future full research/review output with applied/rejected outcome and capture provenance.",
            "Match each completed live task to one immutable full artifact; do not fabricate old missing outputs.",
        )
    if calls["weekly"] and calls["monthly"]:
        from .project import session_coverage

        if session_coverage(store)["complete_sessions"] <= 1:
            finding(
                "duplicate_period_reviews",
                "Weekly/monthly reviews consumed separate calls on at most one observed session.",
                "Reuse the daily review for warm-up period rollups when their actual evidence windows are identical.",
                "Label derived rollups, consume no model call, retain independent period reviews once multiple sessions exist.",
            )
    report = {
        "day": day,
        "as_of": utc_now(),
        "scope": "Diagnostic patterns in archived outputs and measured telemetry; not a truth score, strategy grade or profitability estimate.",
        "measured_usage": measured,
        "artifact_counts": dict(role_outputs),
        "legacy_snapshot_artifacts": sum(a["origin"].startswith("legacy") for a in artifacts),
        "derived_period_reviews": sum(a["origin"] == "derived_period_review" for a in artifacts),
        "reported_blockers": dict(blockers),
        "unique_cited_urls": len(urls),
        "known_no_plan_research_outputs": known_no_plan,
        "pulse_outputs": len(pulse_outputs),
        "pulses_without_verified_delta": no_verified_delta,
        "reviewed_cards": len(reviewed),
        "catalogue_cards": len(catalogue),
        "catalogue_scope": "Current catalogue state at audit time; not a reconstruction of historical acceptance.",
        "reviewed_without_explicit_source_attestation": len(unattested),
        "findings": candidates,
        "limits": [
            "No claim that citations were automatically authenticated or their statements are true.",
            "Historical overwritten outputs cannot be reconstructed from summaries.",
            "No-material-change is not evidence that no market event occurred.",
            "Code receipts do not demonstrate improved research quality before subsequent observations.",
        ],
    }
    if persist:
        store.set("quality-audit:" + day, report)
        store.set("quality_audit", report)
        for f in candidates:
            key = "quality-proposal:" + f["id"]
            old = store.rows("SELECT payload FROM memory WHERE id=?", (key,))
            old = json.loads(old[0]["payload"]) if old else {}
            store.memory_put(
                key,
                "improvement_proposal",
                {
                    **f,
                    "first_seen": old.get("first_seen", utc_now()),
                    "last_seen": utc_now(),
                    "evidence_day": day,
                    "authority": "Developer proposal; automated maintenance remains filter-only",
                },
            )
    return report


def digest(store, day):
    r = daily_audit(store, day)
    return {
        k: r[k]
        for k in (
            "day",
            "measured_usage",
            "artifact_counts",
            "legacy_snapshot_artifacts",
            "reported_blockers",
            "reviewed_without_explicit_source_attestation",
            "findings",
            "limits",
        )
    }


def pulse_prompt(context, store):
    from .research import BASE

    p = {
        "now": utc_now(),
        "brief_recorded_at": store.get("brief_recorded_at"),
        "baseline_summary": context.get("brief", {}).get("summary", "")[:800],
        "events": context.get("brief", {}).get("events", [])[:6],
        "symbols": context.get("symbols", []),
        "recent_updates": [
            {
                "at": u.get("at"),
                "summary": u.get("summary", "")[:500],
                "sources": [s["url"] for s in u.get("sources", [])[:2]],
            }
            for u in store.get("pulses", [])[:2]
        ],
        "instruction": "Verify one material development since the latest supplied update, preferably an actual newly due release/result or issuer statement. Use at most one search and one source check. Avoid repeating an old calendar when the release itself is due. With no holdings/plans, research market context only and do not invent affected positions. Missing verification means unknown, not proof that nothing changed. Return Pulse JSON; no price plans.",
    }
    return BASE + "\nROLE: focused market-event update.\n" + json.dumps(p, separators=(",", ":"))


def derive_period(store, role, day):
    """Reuse a review only when the broader window adds no retained evidence."""
    from datetime import timedelta, timezone

    current = datetime.fromisoformat(day).date()
    week = current - timedelta(days=current.weekday())
    beginning = week if role == "weekly" else current.replace(day=1)
    source_begin = current if role == "weekly" else week
    source_key = "review" if role == "weekly" else "weekly:" + day
    source = store.get(source_key)
    if not source or (role == "weekly" and store.get("review_day") != day):
        return None

    def utc(d):
        return (
            datetime.combine(d, datetime.min.time(), tzinfo=ET).astimezone(timezone.utc).isoformat()
        )

    # Even an unsuccessful earlier session is substantive evidence; never hide it.
    prior = store.rows(
        "SELECT count(*) n FROM events WHERE at>=? AND at<? AND kind NOT IN ('agent_task','period_review','notification_sent','release')",
        (utc(beginning), utc(source_begin)),
    )[0]["n"]
    old_equity = store.rows(
        "SELECT count(*) n FROM equity WHERE day>=? AND day<?",
        (beginning.isoformat(), source_begin.isoformat()),
    )[0]["n"]
    old_orders = store.rows(
        "SELECT count(*) n FROM orders WHERE at>=? AND at<?", (utc(beginning), utc(source_begin))
    )[0]["n"]
    if prior or old_equity or old_orders:
        return None
    result = json.loads(json.dumps(source))
    result.update(
        {
            "summary": "Derived "
            + role
            + " record: no earlier retained evidence beyond the source review window. "
            + source.get("summary", ""),
            "derived_from": ("daily:" + day if role == "weekly" else "weekly:" + day),
            "independent_model_review": False,
            "recorded_at": utc_now(),
            "scope_note": "Reuses an identical retained evidence window; does not imply a full week/month of observations.",
        }
    )
    return result
