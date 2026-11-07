import copy
import json
from datetime import timedelta

from agent_trader.runtime.research_work import (
    _context,
    reviewed_context,
    stale_source_leads,
    record_analysis,
    record_review,
)
from agent_trader.runtime.store import dumps
from tests.runtime.test_research_work import draft_for, review_for


def retain(store, context, report, now, disposition="accepted"):
    record_analysis(store, context, report, now.date().isoformat(), now.isoformat())
    record_review(store, context, review_for(context, report, disposition), now.date().isoformat(), now.isoformat())


def event_report(now):
    context = _context("event_coverage", {"records": [{"id": "ev:scope", "kind": "research", "value": {"focus": ["NVDA", "AMD"]}}], "omitted_records": 0}, 0, None)
    report = draft_for(context)
    report["summary"] = "NVDA and AMD appointments are individually verified, while comprehensive event clearance remains unresolved. " * 7
    urls = [
        "https://www.nyse.com/trade/hours-calendars",
        "https://investor.nvidia.com/news/press-release-details/2026/NVIDIA-Sets-Conference-Call-for-Third-Quarter-Financial-Results/default.aspx",
        "https://ir.amd.com/news-events/ir-calendar",
        "https://ir.amd.com/news-events/press-releases",
        "https://www.federalreserve.gov/newsevents/2026-november.htm",
        "https://www.bls.gov/schedule/2026/11_sched.htm",
        "https://www.newyorkfed.org/research/calendars/nationalecon_cal",
        "https://www.census.gov/economic-indicators/calendar-listview.html",
    ]
    report["sources"] = [{"url": url, "claim": "A narrow, checked source claim.", "outcome": "partial" if i == 7 else "verified", "checked_at": now.isoformat(), "limitation": "This source does not establish complete event coverage."} for i, url in enumerate(urls)]
    report["findings"] = [
        {"claim": "The next scheduled session is Monday November 9, 09:30 to 16:00 ET.", "kind": "inference", "evidence_refs": ["source:0"], "qualification": "Scheduled hours do not exclude extraordinary closures."},
        {"claim": "NVDA schedules November 17 results at approximately 16:20 ET and its call at 17:00 ET.", "kind": "observation", "evidence_refs": ["source:1", "ev:scope"], "qualification": "Results timing is approximate. Other company events before the session remain unverified."},
        {"claim": "AMD's index timestamps results November 3 at 16:15 EST; December conference entries omit times.", "kind": "observation", "evidence_refs": ["source:2", "source:3"], "qualification": "Publication timestamps are not independently measured dissemination; omissions do not exclude filings."},
        {"claim": "The Fed lists a November 9 Bowman discussion at 08:40 without timezone. BLS lists November 10 CPI at 08:30 ET, and NYFed lists November 9 wholesale trade and expectations survey.", "kind": "observation", "evidence_refs": ["source:4", "source:5", "source:6"], "qualification": "Board update metadata are inconsistent. Census confirmation is missing; selected calendars are not comprehensive clearance."},
        {"claim": "Comprehensive event clearance remains unknown.", "kind": "unknown", "evidence_refs": ["ev:scope", "source:7"], "qualification": "The Census response was the wrong year; failed checks and calendar omissions do not establish absence."},
    ]
    report["unresolved"] = ["Missing a dated primary receipt for filings, event times and coverage boundaries. " * 4] * 4
    return context, report


def test_oversized_event_summary_yields_complete_focus_and_macro_findings_before_newer_audit(store, now):
    context, report = event_report(now)
    retain(store, context, report, now)
    diagnostic = _context("evidence_integrity", {"records": [{"id": "ev:study", "kind": "study", "value": "cohort conflict"}], "omitted_records": 0}, 0, None)
    retain(store, diagnostic, draft_for(diagnostic), now + timedelta(seconds=10))
    old_projection = {"summary": report["summary"], "unresolved": report["unresolved"], "sources": [{k: s[k] for k in ("url", "checked_at", "outcome")} for s in report["sources"]]}
    assert len(dumps([old_projection])) > 1800
    before = store.db.total_changes
    projected = reviewed_context(store, 3000, now + timedelta(seconds=15), focus_symbols=["NVDA", "AMD"])
    assert store.db.total_changes == before
    assert projected[0]["topic"] == "event_coverage"
    indexes = {f["index"] for f in projected[0]["findings"]}
    assert {1, 3} <= indexes  # Company and macro coverage both survive.
    assert len(dumps(projected)) <= 3000
    assert projected[0]["omitted_findings"] == len(report["findings"]) - len(indexes)
    source_refs = {s["ref"] for s in projected[0]["sources"]}
    for finding in projected[0]["findings"]:
        assert {k: v for k, v in finding.items() if k != "index"} == report["findings"][finding["index"]]
        assert {r for r in finding["evidence_refs"] if r.startswith("source:")} <= source_refs
    assert all(s["limitation"] for s in projected[0]["sources"])
    assert reviewed_context(store, 10, now, focus_symbols=["NVDA"]) == []


def test_expired_leads_prioritize_focus_and_distinct_macro_hosts_over_duplicate_ir_and_exchange_pages(store, now):
    context, report = event_report(now)
    retain(store, context, report, now)
    leads = stale_source_leads(store, 1000, now + timedelta(hours=25), focus_symbols=["NVDA", "AMD"])
    urls = {r["url"] for r in leads}
    assert report["sources"][1]["url"] in urls
    assert report["sources"][2]["url"] in urls
    assert {report["sources"][i]["url"] for i in (4, 5, 6)} <= urls
    assert report["sources"][0]["url"] not in urls
    assert report["sources"][3]["url"] not in urls
    assert report["sources"][7]["url"] not in urls
    assert len(dumps(leads)) <= 1000
    assert all(set(r) == {"topic", "url", "last_checked", "requires_recheck"} for r in leads)


def test_a_later_review_cannot_renew_old_source_checks(store, now):
    context, report = event_report(now)
    for source in report["sources"]:
        source["checked_at"] = (now - timedelta(days=2)).isoformat()
    retain(store, context, report, now)
    assert reviewed_context(store, now=now, focus_symbols=["NVDA"]) == []
    assert stale_source_leads(store, now=now, focus_symbols=["NVDA"])


def test_newer_generation_suppresses_older_conflicting_conclusions_even_if_held(store, now):
    context, report = event_report(now)
    retain(store, context, report, now)
    changed = copy.deepcopy(context["evidence"])
    changed["records"][0]["value"]["new_conflict"] = "Issuer timing changed"
    updated = _context("event_coverage", changed, 0, None)
    revised = draft_for(updated)
    retain(store, updated, revised, now + timedelta(minutes=1), disposition="held")
    assert reviewed_context(store, now=now + timedelta(minutes=2)) == []
    assert stale_source_leads(store, now=now + timedelta(days=2)) == []
    assert len(store.rows("SELECT id FROM memory WHERE layer='research_work'")) == 4


def test_morning_prompt_passes_focus_selection_and_keeps_complete_packet(store, now, monkeypatch):
    from agent_trader.runtime import research, research_work

    context, report = event_report(now)
    retain(store, context, report, now)
    actual = research_work.reviewed_context
    monkeypatch.setattr(research_work, "reviewed_context", lambda store, **kwargs: actual(store, now=now, **kwargs))
    prompt = research.research_prompt("2026-10-30", {"focus_symbols": ["NVDA", "AMD"]}, store)
    packet = json.loads(prompt.split("CONTEXT:\n", 1)[1])
    findings = packet["independently_reviewed_research"][0]["findings"]
    assert {1, 3} <= {f["index"] for f in findings}
    assert len(prompt) <= 27500 and "omitted_findings" in prompt
