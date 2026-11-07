"""Daily evidence-quality audit and durable development backlog; no order authority."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from datetime import datetime, timedelta

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
    "deep_research",
    "deep_research_review",
}

FEATURE_PATTERNS = {
    "price_structure": r"opening[ -]range|vwap|entry structure|entry level",
    "exact_daily_features": r"exact three|three-session|three.session return",
}


def _feature_language(result):
    """Text is reported language, never proof that an input was absent."""
    mentioned, unresolved, resolved = set(), set(), set()
    for paragraph in result.get("unknowns", []) + result.get("uncertainties", []):
        for text in re.split(r"\bbut\b|\bwhile\b|;\s*|(?<=[.!?])\s+", paragraph, flags=re.I):
            for category, pattern in FEATURE_PATTERNS.items():
                if not re.search(pattern, text, re.I):
                    continue
                mentioned.add(category)
                if re.search(
                    r"no longer.{0,25}(?:blocker|missing|unavailable)|"
                    r"(?:resolved|resolves).{0,50}(?:gap|missing)|"
                    r"(?:not missing|not unavailable)", text, re.I,
                ):
                    resolved.add(category)
                elif re.search(
                    r"unavailable|missing|absent|lack(?:s|ing)?|do(?:es)? not exist|unknown|"
                    r"not (?:supplied|available)|\bno\b.{0,100}\b(?:exist|available)", text, re.I,
                ):
                    unresolved.add(category)
    return mentioned, unresolved, resolved


def _input_phase(store, packet):
    """Use the retained input time and actual broker calendar, never wall-clock guesses."""
    try:
        at = datetime.fromisoformat(packet["observed_at"].replace("Z", "+00:00"))
        if at.tzinfo is None:
            return "unknown", None
        local = at.astimezone(ET)
        day = local.date().isoformat()
        calendar = store.get("calendar:" + day)
        if calendar == []:
            return "non_session", None
        if not calendar or calendar[0].get("date", day) != day:
            return "unknown", None
        opened = datetime.fromisoformat(day + "T" + calendar[0]["open"]).replace(tzinfo=ET)
        closed = datetime.fromisoformat(day + "T" + calendar[0]["close"]).replace(tzinfo=ET)
        if closed <= opened:
            return "unknown", None
        if local < opened:
            return "preopen", local - opened
        if local >= closed:
            return "after_close", local - opened
        return ("opening_minutes" if local < opened + timedelta(minutes=5) else "regular_session"), local - opened
    except (KeyError, TypeError, ValueError, IndexError):
        return "unknown", None


def feature_diagnostics(store, artifacts):
    """Match research to retained inputs and distinguish expected absence from gaps.

    Presence checks do not establish calculation accuracy, actionable price
    structure or complete feed coverage. Recorded input timestamps are linkage
    evidence; they do not reconstruct missing historical prompt transcripts.
    """
    records = []
    for artifact in artifacts:
        if artifact.get("role") != "research" or artifact.get("outcome") != "applied":
            continue
        result = artifact.get("result")
        if not isinstance(result, dict):
            continue
        mentioned, unresolved, resolved = _feature_language(result)
        stamp = artifact.get("input_observed_at")
        inputs = store.rows(
            "SELECT id,payload FROM memory WHERE layer='research_input' "
            "AND json_extract(payload,'$.observed_at')=? LIMIT 2", (stamp,),
        ) if stamp else []
        record = {
            "task_key": artifact.get("task_key"), "input_observed_at": stamp,
            "input_link": "matched_recorded_timestamp" if len(inputs) == 1 else "missing_or_ambiguous",
            "session_phase": "unknown", "state": "input_unmatched",
            "mentioned_features": sorted(mentioned), "reported_unresolved_features": sorted(unresolved),
            "reported_resolved_features": sorted(resolved),
            "expected_missing_count": None, "unexpected_missing_count": None,
            "missing_examples": [],
        }
        if len(inputs) == 1:
            retained = json.loads(inputs[0]["payload"])
            packet = retained.get("packet", {})
            record["input_record_id"] = inputs[0]["id"]
            phase, elapsed = _input_phase(store, packet)
            record["session_phase"] = phase
            selected = set(packet.get("focus_symbols", [])) | {"SPY", "QQQ", "TLT"}
            if not packet.get("focus_symbols"):
                selected |= set(list(packet.get("market", {}))[:3])
            daily_gaps, minute_gaps, expected = [], [], []
            daily_complete, minute_complete = 0, 0

            def present(value):
                return type(value) in (float, int) and math.isfinite(value)

            for symbol in sorted(selected):
                daily = packet.get("daily_indicators", {}).get(symbol, {})
                minute = packet.get("intraday_indicators", {}).get(symbol, {})
                daily_missing = [f for f in ("return_1d", "return_3d", "return_5d") if not present(daily.get(f))]
                daily_complete += not daily_missing
                daily_gaps += [symbol + ":" + f for f in daily_missing]
                minute_missing = [f for f in ("bar_vwap_iex", "opening_5m_high", "opening_5m_low") if not present(minute.get(f))]
                minute_complete += not minute_missing
                for field in minute_missing:
                    wait = 1 if field == "bar_vwap_iex" else 5
                    anticipated = phase in ("preopen", "after_close", "non_session") or (
                        phase == "opening_minutes" and elapsed < timedelta(minutes=wait)
                    )
                    (expected if anticipated else minute_gaps).append(symbol + ":" + field)
            gaps = daily_gaps + minute_gaps
            relevant_gaps = (daily_gaps if "exact_daily_features" in unresolved else []) + (
                minute_gaps if "price_structure" in unresolved else []
            )
            relevant_expected = expected if "price_structure" in unresolved else []
            record.update({
                "selected_symbols": sorted(selected),
                "daily_complete_symbols": daily_complete, "minute_complete_symbols": minute_complete,
                "expected_missing_count": len(expected),
                "unexpected_missing_count": len(gaps) if phase != "unknown" else None,
                "observed_missing_count": len(gaps) + len(expected),
                "missing_examples": (gaps + expected)[:4],
            })
            if not unresolved:
                record["state"] = "reported_resolved" if resolved else "no_reported_feature_blocker"
            elif phase == "unknown":
                record["state"] = "phase_unverified"
            elif relevant_gaps:
                record["state"] = "reported_blocker_with_input_gaps"
            elif relevant_expected:
                record["state"] = "expected_session_phase_absence"
            else:
                record["state"] = "reported_blocker_with_supplied_features"
        records.append(record)
    states = Counter(r["state"] for r in records)
    return {
        "research_reports": len(records),
        "matched_inputs": sum(r["input_link"] == "matched_recorded_timestamp" for r in records),
        "phase_counts": dict(Counter(r["session_phase"] for r in records)),
        "state_counts": dict(states),
        "records": records[-12:], "omitted_records": max(0, len(records) - 12),
        "scope": "Reported feature language plus field presence in the exactly timestamp-linked retained packet and broker session calendar. Expected preopen absence is not a collection fault; supplied fields do not prove correctness or an executable setup.",
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
        **FEATURE_PATTERNS,
        "event_coverage": r"earnings|event timing|calendar|release timing",
        "source_access": r"403|not independently|not.*verified|source.*unavailable",
        "stale_data": r"stale|two calendar days old",
    }
    blockers = Counter()
    mentions = Counter()
    urls = set()
    for a in artifacts:
        r = a["result"]
        if not isinstance(r, dict):
            continue
        text = " ".join(r.get("unknowns", []) + r.get("uncertainties", []))
        for name, pattern in patterns.items():
            if re.search(pattern, text, re.I):
                mentions[name] += 1
                if name not in FEATURE_PATTERNS:
                    blockers[name] += 1
        _, unresolved, _ = _feature_language(r)
        blockers.update(unresolved)
        urls.update(s["url"] for s in r.get("sources", []) if s.get("url"))
    catalogue = store.get("research_catalogue", [])
    reviewed = [c for c in catalogue if c.get("state") == "reviewed_for_testing"]
    unattested = [
        c["id"]
        for c in reviewed
        if c.get("source_check_status") != "verified"
        and not (
            c.get("evidence_basis") == "local_observation"
            and not c.get("source_urls")
            and c.get("source_check_status") == "not_applicable"
            and c.get("method_check_status") == "reviewed"
            and c.get("observation_provenance_verified")
        )
    ]
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
            json.loads(r["payload"]).get("state") in ("started", "failed")
            and not json.loads(r["payload"]).get("reply_usage_reported", False)
            for r in usage
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

    feature_checks = feature_diagnostics(store, artifacts)
    feature_states = feature_checks["state_counts"]
    if feature_states.get("reported_blocker_with_input_gaps"):
        finding(
            "missing_price_features",
            "An unresolved research feature report coincides with missing fields in its timestamp-linked input during a phase where they are expected.",
            "Inspect the named report/input and missing fields; distinguish unavailable IEX coverage from collection/calculation defects before repairing inputs.",
            "Verify exact packet linkage, broker session phase, completed bars, field calculations and subsequent research use; do not backfill observations.",
            "high",
        )
    if any(r["reported_unresolved_features"] and r["state"] in ("input_unmatched", "phase_unverified") for r in feature_checks["records"]):
        finding(
            "feature_input_lineage",
            "A reported feature gap cannot be classified because its exact input or session phase is unverified.",
            "Retain exact research-input and broker-calendar linkage; do not infer missing data from feature keywords or expected preopen absence.",
            "Match future research artifacts to the actual supplied packet and session; historical missing linkage stays explicit.",
        )
    if feature_states.get("reported_blocker_with_supplied_features"):
        finding(
            "feature_blocker_attribution",
            "Research describes a feature/setup blocker although the checked feature fields were supplied.",
            "Map each blocker to a specific symbol/field and distinguish sparse or stale coverage, unclear naming, unusable setup and failure to consume supplied evidence.",
            "Review the exact retained packet/output pair. Field presence alone establishes neither calculation accuracy nor an executable entry.",
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
        "reported_mentions": dict(mentions),
        "feature_diagnostics": feature_checks,
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
            "Textual mentions and reported blockers are not verified input failures. Feature diagnostics use recorded input linkage and session phase; field presence is not a correctness or trade-readiness check.",
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
                    **old,
                    **f,
                    "first_seen": old.get("first_seen", utc_now()),
                    "last_seen": utc_now(),
                    "evidence_day": day,
                    "baseline_evidence_day": old.get(
                        "baseline_evidence_day", old.get("evidence_day", day)
                    ),
                    "baseline_problem": old.get(
                        "baseline_problem", old.get("problem", f["problem"])
                    ),
                    "authority": "Developer proposal; automated maintenance remains filter-only",
                },
            )
    from .development import assess_changes

    effects = assess_changes(store, day, persist=persist)
    report["development_effects"] = {
        "scope": effects["scope"],
        "state_counts": effects["state_counts"],
        "changes": [
            {k: effect.get(k) for k in ("id", "state", "evidence_day", "metrics", "reason")}
            for effect in effects["changes"]
        ],
    }
    if persist:
        store.set("quality-audit:" + day, report)
        store.set("quality_audit", report)
    return report


def digest(store, day):
    r = daily_audit(store, day)
    result = {
        k: r[k]
        for k in (
            "day",
            "measured_usage",
            "artifact_counts",
            "legacy_snapshot_artifacts",
            "reported_blockers",
            "reported_mentions",
            "reviewed_without_explicit_source_attestation",
            "findings",
            "limits",
            "development_effects",
        )
    }
    feature = r["feature_diagnostics"]
    result["feature_diagnostics"] = {
        k: feature[k] for k in ("research_reports", "matched_inputs", "phase_counts", "state_counts", "scope")
    }
    result["feature_diagnostics"]["recent_records"] = [
        {k: row[k] for k in ("task_key", "input_link", "session_phase", "state", "expected_missing_count", "unexpected_missing_count")}
        for row in feature["records"][-2:]
    ]
    return result


def pulse_prompt(context, store):
    from .research import BASE
    from .intelligence import observation_context

    p = {
        "now": utc_now(),
        "brief_recorded_at": store.get("brief_recorded_at"),
        "baseline_summary": context.get("brief", {}).get("summary", "")[:800],
        "events": context.get("brief", {}).get("events", [])[:6],
        "symbols": context.get("symbols", []),
        "observed_questions": observation_context(store, max_chars=1600),
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
