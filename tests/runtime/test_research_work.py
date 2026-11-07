import copy
import json
from datetime import timedelta

import pytest

from agent_trader.runtime.research_work import (
    MAX_REVISIONS,
    ResearchWorkReport,
    ResearchWorkReview,
    SourceReceipt,
    _context,
    accepted_context,
    evidence_packets,
    next_work,
    prepare_task,
    public_summary,
    record_analysis,
    record_failure,
    record_review,
    stale_source_leads,
)


def seed_account(store):
    store.set("account", {"cash": "29999.84", "equity": "29999.84", "status": "ACTIVE"})
    store.db.execute("UPDATE branches SET cash=9999.87 WHERE name='intraday'")


def seed_research(store, day="2026-11-06"):
    store.memory_put("research-one", "research_artifact", {
        "role": "research", "outcome": "applied", "day": day,
        "task_key": "research:" + day, "input_observed_at": day + "T14:45:00+00:00",
        "result": {"summary": "Event risk needs verification", "unknowns": ["Earnings date unknown"], "sources": [], "plans": []},
    })
    store.set("market_packet", {"focus_symbols": ["NVDA", "AMD", "TLT"]})


def draft_for(context):
    return {
        "work_id": context["work_id"], "topic": context["topic"],
        "summary": "An unresolved accounting or source gap requires a specific receipt.",
        "findings": [{"claim": "The supplied evidence cannot attribute the gap.",
                      "kind": "unknown", "evidence_refs": [context["evidence"]["records"][0]["id"]],
                      "qualification": "No fees, missing events or successful recovery are inferred."}],
        "sources": [], "proposals": [{"problem": "Unattributed gap", "requested_change": "Retain the missing receipt", "validation_plan": "Compare the receipt with the recorded evidence"}],
        "unresolved": ["Need the missing authoritative receipt"],
    }


def review_for(context, report, disposition="accepted"):
    return {
        "work_id": context["work_id"], "disposition": disposition,
        "rationale": "The claim is supported at its limited unknown scope.",
        "checked_evidence_refs": list({r for f in report["findings"] for r in f["evidence_refs"]}),
        "supported_findings": list(range(len(report["findings"]))),
        "sources": copy.deepcopy(report["sources"]),
        "corrections": ["Specify the exact missing receipt"] if disposition == "revise" else [],
    }


def complete(store, request, now, disposition="accepted"):
    context = request["context"]
    draft = draft_for(context)
    record_analysis(store, context, draft, now.date().isoformat(), now.isoformat())
    review = review_for(context, draft, disposition)
    record_review(store, context, review, now.date().isoformat(), now.isoformat())
    return draft, review


def test_empty_evidence_does_not_create_work_or_claim_completion(store, now):
    assert next_work(store, now) is None
    assert store.get("research_work_status")["state"] == "no_evidence"
    assert public_summary(store, now)["reports"] == []


def test_account_gap_has_two_stages_then_deduplicates_without_operational_mutation(store, now):
    seed_account(store)
    before = store.rows("SELECT * FROM branches")
    request = next_work(store, now)
    context = request["context"]
    assert request["role"] == "deep_research"
    assert context["topic"] == "accounting_attribution"
    prompt, schema = prepare_task(store, context)
    assert schema is ResearchWorkReport and "29999.84" in prompt
    draft = draft_for(context)
    record_analysis(store, context, draft, "2026-10-30", now.isoformat())
    request_review = next_work(store, now)
    assert request_review["role"] == "deep_research_review"
    prompt, schema = prepare_task(store, context, review=True)
    assert schema is ResearchWorkReview and "analyst_report" in prompt
    record_review(store, context, review_for(context, draft), "2026-10-30", now.isoformat())
    assert next_work(store, now) is None
    assert store.get("research_work_status")["state"] == "waiting_for_evidence"
    assert store.rows("SELECT * FROM branches") == before
    for table in ("plans", "orders", "experiments", "shadow"):
        assert not store.rows("SELECT * FROM " + table)
    assert store.rows("SELECT * FROM memory WHERE layer='improvement_proposal'")


def test_reports_and_reviews_are_immutable_and_idempotent(store, now):
    seed_account(store)
    request = next_work(store, now)
    draft, review = complete(store, request, now)
    context = request["context"]
    record_analysis(store, context, draft, now.date().isoformat())
    record_review(store, context, review, now.date().isoformat())
    assert len(store.rows("SELECT * FROM memory WHERE layer='research_work'")) == 2
    changed = {**draft, "summary": "Changed history"}
    with pytest.raises(ValueError, match="immutable"):
        record_analysis(store, context, changed, now.date().isoformat())
    with pytest.raises(ValueError, match="immutable"):
        record_review(store, context, {**review, "rationale": "Changed history"}, now.date().isoformat())


def test_review_keeps_original_evidence_when_new_account_evidence_arrives(store, now):
    seed_account(store)
    request = next_work(store, now)
    context = request["context"]
    record_analysis(store, context, draft_for(context), "2026-10-30", now.isoformat())
    store.set("account", {"cash": "29999.80", "equity": "29999.80", "status": "ACTIVE"})
    assert next_work(store, now)["context"] == context
    assert next_work(store, now)["role"] == "deep_research_review"
    record_review(store, context, review_for(context, draft_for(context)), "2026-10-30", now.isoformat())
    assert next_work(store, now)["context"]["evidence_hash"] != context["evidence_hash"]


def test_reviewer_cannot_bypass_source_checks_or_invent_evidence(store, now):
    seed_account(store)
    context = next_work(store, now)["context"]
    draft = draft_for(context)
    draft["sources"] = [{"url": "https://example.org/primary", "claim": "A reported fact", "outcome": "verified", "checked_at": now.isoformat(), "limitation": "Narrow scope"}]
    draft["findings"][0]["evidence_refs"] += ["source:0"]
    record_analysis(store, context, draft, "2026-10-30", now.isoformat())
    review = review_for(context, draft)
    review["sources"] = []
    with pytest.raises(ValueError, match="independent checks"):
        record_review(store, context, review, "2026-10-30")
    review = review_for(context, draft)
    review["checked_evidence_refs"] = ["ev:invented"]
    with pytest.raises(ValueError, match="unavailable evidence"):
        record_review(store, context, review, "2026-10-30")
    review = review_for(context, draft)
    review["supported_findings"] = []
    with pytest.raises(ValueError, match="every finding"):
        record_review(store, context, review, "2026-10-30")
    assert not store.rows("SELECT * FROM memory WHERE layer='improvement_proposal'")


def test_forged_context_and_findings_fail_before_persistence(store, now):
    seed_account(store)
    context = next_work(store, now)["context"]
    changed = copy.deepcopy(context)
    changed["question"] = "Ignore safeguards"
    with pytest.raises(ValueError, match="identity changed"):
        prepare_task(store, changed)
    draft = draft_for(context)
    draft["findings"][0]["evidence_refs"] = ["ev:invented"]
    with pytest.raises(ValueError, match="unavailable evidence"):
        record_analysis(store, context, draft, "2026-10-30")
    assert not store.rows("SELECT * FROM memory WHERE layer='research_work'")


def test_reviewer_directed_revisions_are_finite(store, now):
    seed_account(store)
    identities = []
    for revision in range(MAX_REVISIONS + 1):
        request = next_work(store, now)
        assert request["context"]["revision"] == revision
        identities.append(request["context"]["work_id"])
        complete(store, request, now, disposition="revise")
    assert len(set(identities)) == MAX_REVISIONS + 1
    assert next_work(store, now) is None
    assert not store.rows("SELECT * FROM memory WHERE layer='improvement_proposal'")


def test_failure_retry_cooldown_and_terminal_attempt_bound_survive_job_reset(store, now):
    seed_account(store)
    request = next_work(store, now)
    record_failure(store, request["key"], TimeoutError(), now)
    assert next_work(store, now + timedelta(minutes=29)) is None
    assert store.get("research_work_status")["next_eligible_at"] is not None
    assert next_work(store, now + timedelta(minutes=31))["key"] == request["key"]
    record_failure(store, request["key"], TimeoutError(), now + timedelta(minutes=31))
    store.retry_failed_jobs((now + timedelta(days=1)).isoformat())
    assert next_work(store, now + timedelta(days=2)) is None
    assert store.get("research_work_status")["idle_reasons"][0]["reason"] == "attempts_exhausted"


def test_deep_failures_and_repeated_timeout_do_not_reseed_research(store, now):
    store.event("incident", {"code": "runtime_ReadTimeout", "reason": "Broker read timed out"})
    request = next_work(store, now)
    complete(store, request, now)
    store.event("agent_task_failed", {"role": "deep_research", "attempt_id": "new", "error_type": "TimeoutError"})
    store.event("incident", {"code": "agent_deep_research_review", "reason": "Review failed"})
    store.event("incident", {"code": "runtime_ReadTimeout", "reason": "Broker read timed out"})
    assert next_work(store, now + timedelta(days=1)) is None
    store.event("incident", {"code": "runtime_BrokerError", "reason": "New category"})
    assert next_work(store, now + timedelta(days=1)) is not None


def test_precise_source_work_covers_ten_symbols_and_three_macro_sources(store, now):
    seed_research(store)
    packets = evidence_packets(store)
    symbols = [key for key in packets if key.startswith("symbol_events:")]
    macros = [key for key in packets if key.startswith("macro_events:")]
    assert len(symbols) == 10 and len(macros) == 3
    assert symbols[:3] == ["symbol_events:NVDA", "symbol_events:AMD", "symbol_events:TLT"]
    assert all(len(str(packet)) < 14000 for packet in packets.values())


def test_feature_lineage_prioritizes_exact_focus_inputs_over_large_prose(store, now):
    seed_research(store)
    store.memory_put("input-one", "research_input", {
        "day": "2026-11-06", "observed_at": "2026-11-06T14:45:00+00:00",
        "packet": {"focus_symbols": ["NVDA"], "universe": ["SPY", "NVDA"],
                   "daily_indicators": {"NVDA": {"return_3d": -0.02}},
                   "intraday_indicators": {"NVDA": {"bar_vwap_iex": 100.5}}},
    })
    packet = evidence_packets(store)["feature_lineage"]
    first = packet["records"][0]
    assert first["kind"] == "exact_input"
    assert first["value"]["focus"] == ["NVDA"]
    assert first["value"]["minute"]["NVDA"]["bar_vwap_iex"] == 100.5


def test_only_unexpired_accepted_results_reach_research_context(store, now):
    seed_research(store)
    request = next_work(store, now)
    complete(store, request, now)
    assert accepted_context(store, now=now)
    assert not accepted_context(store, now=now + timedelta(hours=25))
    assert not accepted_context(store, max_chars=10, now=now)


def test_public_summary_is_read_only_and_excludes_frozen_private_packets(store, now):
    seed_account(store)
    complete(store, next_work(store, now), now)
    before = store.db.total_changes
    summary = public_summary(store, now)
    assert store.db.total_changes == before
    assert summary["reports"]
    assert "context" not in summary["reports"][0]
    assert "evidence" not in summary["reports"][0]


def test_review_packet_fails_explicitly_instead_of_truncating_evidence(store, now):
    seed_account(store)
    context = next_work(store, now)["context"]
    draft = draft_for(context)
    draft["unresolved"] = ["x" * 10001]
    with pytest.raises(ValueError, match="bounded review budget"):
        record_analysis(store, context, draft, "2026-10-30")


def test_near_max_revision_context_still_fits_independent_review_budget(store, now):
    evidence = {"records": [{"id": "ev:large", "kind": "receipt", "value": "x" * 12200}], "omitted_records": 0}
    prior_review = {"work_id": "prior", "disposition": "revise", "rationale": "r" * 1600,
                    "corrections": ["c" * 1200] * 6, "sources": [], "supported_findings": [], "checked_evidence_refs": []}
    context = _context("accounting_attribution", evidence, 1, prior_review)
    prompt, _ = prepare_task(store, context)
    assert len(prompt) < 28000 and "prior" in prompt
    draft = draft_for(context)
    draft["summary"] = "s" * 1400
    draft["unresolved"] = ["u" * 1100] * 6
    record_analysis(store, context, draft, "2026-10-30", now.isoformat())
    prompt, _ = prepare_task(store, context, review=True)
    assert len(prompt) < 28000
    assert "previous_review" not in prompt


def test_pending_review_is_not_hidden_by_two_hundred_old_completed_analyses(store, now):
    seed_account(store)
    request = next_work(store, now)
    for i in range(205):
        work_id = "old-" + str(i)
        context = {"work_id": work_id}
        for stage in ("analysis", "review"):
            store.memory_put("research-work:" + work_id + ":" + stage, "research_work", {
                "stage": stage, "context": context, "result": {}, "observed_at": now.isoformat(),
            })
    context = request["context"]
    record_analysis(store, context, draft_for(context), "2026-10-30", now.isoformat())
    store.set("account", {"cash": "29999", "equity": "29999", "status": "ACTIVE"})
    assert next_work(store, now)["context"] == context


@pytest.mark.parametrize("url", ["https://localhost/x", "https://127.0.0.1/x", "https://192.168.1.1/x", "https://metadata.internal/x", "https://user:secret@example.org/x"])
def test_source_receipts_reject_private_hosts_and_embedded_credentials(url, now):
    with pytest.raises(ValueError):
        SourceReceipt(url=url, claim="fact", outcome="verified", checked_at=now.isoformat(), limitation="limited")


def test_future_source_receipts_cannot_be_recorded_as_observed(store, now):
    seed_account(store)
    context = next_work(store, now)["context"]
    draft = draft_for(context)
    draft["sources"] = [{"url": "https://example.org/primary", "claim": "fact", "outcome": "verified", "checked_at": (now + timedelta(days=1)).isoformat(), "limitation": "limited"}]
    with pytest.raises(ValueError, match="after the artifact"):
        record_analysis(store, context, draft, "2026-10-30", now.isoformat())


def test_application_failure_has_safe_code_and_counts_without_bad_reference_text(store, now):
    seed_account(store)
    request = next_work(store, now)
    draft = draft_for(request["context"])
    draft["findings"][0]["evidence_refs"] = ["private-reference-do-not-publish"]
    with pytest.raises(ValueError) as error:
        record_analysis(store, request["context"], draft, "2026-10-30", now.isoformat())
    assert error.value.validation_code == "unknown_evidence_reference"
    receipt = record_failure(store, request["key"], error.value, now)
    assert receipt["validation_details"] == {"invalid_reference_count": 1}
    assert "private-reference" not in str(receipt)


def test_partial_source_cannot_alone_support_an_accepted_factual_finding(store, now):
    seed_account(store)
    context = next_work(store, now)["context"]
    draft = draft_for(context)
    draft["sources"] = [{"url": "https://example.org/primary", "claim": "Unverified timing", "outcome": "partial", "checked_at": now.isoformat(), "limitation": "Exact timing unavailable"}]
    draft["findings"][0]["kind"] = "observation"
    draft["findings"][0]["evidence_refs"] = ["source:0"]
    record_analysis(store, context, draft, "2026-10-30", now.isoformat())
    with pytest.raises(ValueError) as error:
        record_review(store, context, review_for(context, draft), "2026-10-30", now.isoformat())
    assert error.value.validation_code == "unverified_source_claim"


def prompt_packet(prompt):
    return json.loads(prompt[prompt.index('{"'):])


def quota_at(now, used=2):
    return {"ordinary_usage_allowed": True, "at": now.isoformat(), "windows": [
        {"usedPercent": used, "windowDurationMins": 10080,
         "resetsAt": int((now + timedelta(days=4)).timestamp())},
    ]}


def test_retry_feedback_preserves_fingerprint_and_excludes_private_invalid_reference(store, now):
    seed_account(store)
    request = next_work(store, now)
    original = copy.deepcopy(request["context"])
    draft = draft_for(original)
    draft["findings"][0]["evidence_refs"] = ["private-invalid-url-or-title"]
    with pytest.raises(ValueError) as error:
        record_analysis(store, original, draft, "2026-10-30", now.isoformat())
    record_failure(store, request["key"], error.value, now)
    key = "research-work-failure:" + request["key"]
    receipt = store.get(key)
    receipt["validation_details"]["raw_private_failure"] = "private-invalid-url-or-title"
    receipt["error_text"] = "private model output"
    store.set(key, receipt)
    prompt, _ = prepare_task(store, original)
    packet = prompt_packet(prompt)
    assert packet["prior_application_failure"]["validation_code"] == "unknown_evidence_reference"
    assert packet["prior_application_failure"]["validation_details"] == {"invalid_reference_count": 1}
    assert "private-invalid" not in prompt and "private model output" not in prompt
    assert original == request["context"]
    assert packet["evidence_hash"] == original["evidence_hash"]
    assert next_work(store, now + timedelta(minutes=31))["context"] == original


def test_reviewer_reference_list_uses_analyst_source_count_not_schema_maximum(store, now):
    seed_account(store)
    context = next_work(store, now)["context"]
    local = [r["id"] for r in context["evidence"]["records"]]
    prompt, _ = prepare_task(store, context)
    assert prompt_packet(prompt)["allowed_evidence_refs"] == local + [f"source:{i}" for i in range(8)]
    draft = draft_for(context)
    draft["sources"] = [{"url": "https://example.org/source", "claim": "Narrow receipt", "outcome": "verified", "checked_at": now.isoformat(), "limitation": "Incomplete coverage"}]
    record_analysis(store, context, draft, "2026-10-30", now.isoformat())
    prompt, _ = prepare_task(store, context, review=True)
    assert prompt_packet(prompt)["allowed_evidence_refs"] == local + ["source:0"]
    review = review_for(context, draft)
    review["checked_evidence_refs"].append("source:1")
    with pytest.raises(ValueError) as error:
        record_review(store, context, review, "2026-10-30", now.isoformat())
    assert error.value.validation_code == "unknown_evidence_reference"


def test_queue_ignores_old_budget_denial_when_current_allowance_is_fresh(store, now):
    seed_account(store)
    next_work(store, now)
    store.set("quota", quota_at(now))
    store.set("background_budget", {"at": (now - timedelta(days=1)).isoformat(), "allowed": False, "reason": "20% account reserve reached"})
    before = store.db.total_changes
    status = public_summary(store, now)["status"]
    assert status["state"] == "eligible"
    assert status["last_budget_decision"]["allowed"] is False
    assert status["last_budget_decision"]["at"] != now.isoformat()
    assert store.db.total_changes == before


def test_queue_reports_current_account_gate_and_earliest_recheck(store, now):
    seed_account(store)
    next_work(store, now)
    quota = quota_at(now, used=80)
    store.set("quota", quota)
    status = public_summary(store, now)["status"]
    assert status["state"] == "blocked_by_account_allowance"
    assert status["reason"] == "20% account reserve reached"
    assert status["next_eligible_at"] == (now + timedelta(days=4)).isoformat()
    assert "not a promised start" in status["eligibility_scope"]
    quota["at"] = (now - timedelta(minutes=16)).isoformat()
    store.set("quota", quota)
    status = public_summary(store, now)["status"]
    assert status["reason"] == "Account quota observation is stale"
    assert status["next_eligible_at"] is None


def test_queue_does_not_claim_completed_or_failed_selected_stage_remains_eligible(store, now):
    seed_account(store)
    request = next_work(store, now)
    store.set("quota", quota_at(now))
    record_failure(store, request["key"], TimeoutError(), now)
    status = public_summary(store, now)["status"]
    assert status["state"] == "retry_cooldown"
    assert status["next_eligible_at"] == (now + timedelta(minutes=30)).isoformat()
    later = now + timedelta(minutes=31)
    record_analysis(store, request["context"], draft_for(request["context"]), "2026-10-30", later.isoformat())
    status = public_summary(store, later)["status"]
    assert status["state"] == "awaiting_queue_refresh"
    assert status["next_eligible_at"] is None


def test_queue_daily_ceiling_uses_local_midnight_and_does_not_expose_usage_payload(store, now):
    from agent_trader.runtime.budget import DEEP_CALL_CEILING

    seed_account(store)
    next_work(store, now)
    store.set("quota", quota_at(now))
    store.db.executemany("INSERT INTO usage(day,role,payload) VALUES(?,?,?)", [
        ("2026-10-30", "deep_research", '{"task_key":"private-key"}')
    ] * DEEP_CALL_CEILING)
    status = public_summary(store, now)["status"]
    assert status["state"] == "blocked_by_daily_attempt_limit"
    assert status["next_eligible_at"] == "2026-10-31T00:00:00-04:00"
    assert "private-key" not in str(status)


@pytest.mark.parametrize("role,expected", [("research", "waiting_for_primary_task"), ("deep_research_review", "running")])
def test_queue_active_task_only_exposes_allowlisted_fields_and_ignores_completed_job(store, now, role, expected):
    seed_account(store)
    next_work(store, now)
    store.set("quota", quota_at(now))
    store.job_start("private-task-key")
    store.set("active_task", {"key": "private-task-key", "role": role, "started": now.isoformat(), "context": "private-context"})
    status = public_summary(store, now)["status"]
    assert status["state"] == expected
    assert status["active_task"] == {"role": role, "started": now.isoformat()}
    assert "private-" not in str(status)
    store.job_end("private-task-key", True, {})
    status = public_summary(store, now)["status"]
    assert "active_task" not in status
    assert status["state"] == "eligible"


def test_queue_does_not_call_a_proven_dead_worker_running_or_mutate_its_job(store, now):
    from agent_trader.runtime.store import process_owner

    seed_account(store)
    next_work(store, now)
    store.job_start("private-dead-task")
    store.db.execute("UPDATE jobs SET owner=? WHERE key=?", (
        json.dumps({**process_owner(), "boot_id": "previous-boot"}), "private-dead-task",
    ))
    store.set("active_task", {"key": "private-dead-task", "role": "deep_research", "started": now.isoformat()})
    changes = store.db.total_changes
    status = public_summary(store, now)["status"]
    assert status["state"] == "awaiting_job_recovery"
    assert "active_task" not in status and "private-dead-task" not in str(status)
    assert store.db.total_changes == changes
    assert store.rows("SELECT state FROM jobs WHERE key='private-dead-task'")[0]["state"] == "running"


def test_accounting_packet_tracks_fee_facts_but_not_refreshed_timestamps_or_private_receipts(store, now):
    from agent_trader.runtime.accounting import Accounting

    seed_account(store)
    accounting = Accounting(store)
    receipt = [{"id": "private-fee-id", "activity_type": "FEE", "activity_sub_type": "REG", "date": "2026-10-30", "currency": "USD", "status": "executed", "net_amount": "-0.02", "description": "private account detail"}]
    accounting.record(receipt, complete_history=True)
    original = evidence_packets(store)["accounting_attribution"]
    bridge = next(r["value"] for r in original["records"] if r["kind"] == "broker_activity_bridge")
    assert bridge["fees"][0]["category"] == "REG"
    assert bridge["fees"][0]["amount"] == "-0.02"
    assert bridge["receipt_hash"] == store.get("account_activity_receipt")["receipt_hash"]
    assert "private-fee-id" not in str(original) and "private account detail" not in str(original)
    store.set("last_reconciled", (now + timedelta(minutes=1)).isoformat())
    accounting.record(receipt, complete_history=True)
    refreshed = evidence_packets(store)["accounting_attribution"]
    assert _context("accounting_attribution", refreshed)["evidence_hash"] == _context("accounting_attribution", original)["evidence_hash"]
    receipt.append({**receipt[0], "id": "private-new-fee-id", "net_amount": "-0.03"})
    accounting.record(receipt, complete_history=True)
    assert evidence_packets(store)["accounting_attribution"] != original


def accepted_with_sources(store, now, outcomes=("verified", "partial")):
    seed_research(store)
    request = next_work(store, now)
    context = request["context"]
    draft = draft_for(context)
    draft["sources"] = [
        {"url": f"https://example.org/source-{i}", "claim": "Stale event claim must not carry forward", "outcome": outcome, "checked_at": now.isoformat(), "limitation": "Limited calendar scope"}
        for i, outcome in enumerate(outcomes)
    ]
    record_analysis(store, context, draft, "2026-10-30", now.isoformat())
    record_review(store, context, review_for(context, draft), "2026-10-30", now.isoformat())
    return context


def test_expired_source_handoff_preserves_only_verified_locators_and_never_reseeds_work(store, now):
    context = accepted_with_sources(store, now)
    packets = evidence_packets(store)
    assert accepted_context(store, now=now)
    assert stale_source_leads(store, now=now) == []
    later = now + timedelta(hours=25)
    assert accepted_context(store, now=later) == []
    leads = stale_source_leads(store, now=later)
    assert leads == [{"topic": context["topic"], "url": "https://example.org/source-0", "last_checked": now.isoformat(), "requires_recheck": True}]
    assert "claim" not in str(leads) and "clearance" not in str(leads)
    assert stale_source_leads(store, max_chars=10, now=later) == []
    assert evidence_packets(store) == packets


def test_morning_research_receives_expired_urls_with_mandatory_recheck_instruction(store, now):
    from agent_trader.runtime.research import research_prompt

    accepted_with_sources(store, now)
    prompt = research_prompt("2026-11-09", {"focus_symbols": ["NVDA"], "market": {}, "daily_indicators": {}, "intraday_indicators": {}}, store)
    packet = json.loads(prompt.split("CONTEXT:\n", 1)[1])
    assert packet["independently_reviewed_research"] == []
    assert packet["stale_source_leads"][0]["requires_recheck"] is True
    assert "Reopen them" in prompt and len(prompt) <= 27500
