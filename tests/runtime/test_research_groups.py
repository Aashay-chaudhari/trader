"""Held evidence produces finite, distinct questions without quote-refresh churn."""

import json
from datetime import timedelta

from agent_trader.runtime.adaptive_lab import AdaptiveLab
from agent_trader.runtime.research_work import (
    HELD_GROUPS, PACKET_LIMIT, _context, _hash, _option_coverage, evidence_packets,
    next_work, prepare_task, record_analysis, reviewed_context, _terminal_option_probe,
)
from agent_trader.runtime.store import dumps
from tests.runtime.test_research_handoff import event_report, retain
from tests.runtime.test_research_work import complete, draft_for


REVERSAL = HELD_GROUPS["held_reversal_lineage"][0]
RALLY = HELD_GROUPS["held_rally_universe"][0]
EARNINGS, EVENT_IV = HELD_GROUPS["held_earnings_iv"]
VIX = HELD_GROUPS["held_vix_horizon"][0]


def card(identity, **extra):
    return {"id": identity, "state": "needs_work", "claim": "A conjecture needs a specific prospective test.",
            "review_reason": "The supplied evidence does not yet establish this claim.",
            "source_urls": [], "screen_trial_ids": [], "observation_ids": [], **extra}


def artifact(store, identity, hypothesis, contracts=(), at="2026-11-03T13:37:46+00:00"):
    store.memory_put(identity, "research_artifact", {
        "role": "exploration", "observed_at": at,
        "result": {"hypotheses": [hypothesis], "adaptive_contracts": list(contracts)},
    })
    store.db.execute("UPDATE memory SET at=? WHERE id=?", (at, identity))


def options(store):
    sample = {"feed": "indicative", "observed_at": "2026-11-06T18:01:11+00:00", "execution_eligible": False,
              "contracts": [{"symbol": f"{s}261106C{50000000 + i:08d}", "underlying": s,
                             "quote": {"bp": 10, "ap": 10.5, "t": "2026-11-06T18:01:25Z"},
                             "implied_volatility": None, "greeks": None}
                            for s in ("SPY", "QQQ") for i in range(15)]}
    store.set("options_research", sample)
    return sample


def records(store, topic):
    return evidence_packets(store)[topic]["records"]


def by_kind(packet, kind):
    return [r["value"] for r in packet if r["kind"] == kind]


def test_only_four_exact_held_groups_are_discovered_not_duplicate_paper_families(store):
    store.set("research_catalogue", [
        card(i) for ids in HELD_GROUPS.values() for i in ids
    ] + [card("2026-10-30-intraday-pullback"), card("2026-10-30-intraday-macro")])
    before = store.db.total_changes
    packets = evidence_packets(store)
    assert store.db.total_changes == before
    assert {t for t in packets if t.startswith("held_")} == set(HELD_GROUPS)
    assert len(by_kind(packets["held_earnings_iv"]["records"], "held_card")) == 2
    assert all("intraday-pullback" not in dumps(packets[t]) for t in HELD_GROUPS)
    assert all("intraday-macro" not in dumps(packets[t]) for t in HELD_GROUPS)
    catalogue = store.get("research_catalogue")
    for c in catalogue:
        c["state"] = "reviewed_for_testing"
    store.set("research_catalogue", catalogue)
    assert not (set(evidence_packets(store)) & HELD_GROUPS.keys())


def test_quote_refresh_expiry_roll_and_accepted_feedback_cannot_reseed_same_coverage(store, now):
    store.set("research_catalogue", [card(EARNINGS), card(EVENT_IV)])
    sample = options(store)
    topic = "held_earnings_iv"
    before = _context(topic, evidence_packets(store)[topic])
    coverage = by_kind(before["evidence"]["records"], "option_coverage")[0]
    assert coverage["counts"] == {"contracts": 30, "positive_two_sided_quotes": 30,
                                  "noncrossed_positive_quotes": 30, "quote_timestamps_present": 30,
                                  "positive_iv": 0, "numeric_greeks": 0}
    assert coverage["rights"] == {"call": 30}
    assert coverage["expiry_from_observed_date"] == {"same_day": 30}
    assert coverage["event_matching"].startswith("unknown")
    # Finish every finite topic, then change only live quote/contract-day noise.
    for _ in range(8):
        request = next_work(store, now)
        if request is None:
            break
        complete(store, request, now)
    assert next_work(store, now) is None
    sample["observed_at"] = "2026-11-09T18:01:11.123456+00:00"
    for c in sample["contracts"]:
        c["symbol"] = c["symbol"].replace("261106", "261109")
        c["quote"] = {"bp": 12, "ap": 12.5, "t": "2026-11-09T18:01:30Z"}
    store.set("options_research", sample)
    after = _context(topic, evidence_packets(store)[topic])
    assert after["work_id"] == before["work_id"]
    assert after["snapshot_hash"] != before["snapshot_hash"]
    assert next_work(store, now + timedelta(days=1)) is None
    sample["contracts"][0]["implied_volatility"] = 0.4
    store.set("options_research", sample)
    assert next_work(store, now + timedelta(days=1))["context"]["topic"] == topic
    newer = _context(topic, evidence_packets(store)[topic])
    assert newer["work_id"] != before["work_id"]


def test_missing_malformed_and_nonfinite_option_inputs_preserve_unknowns(store):
    assert _option_coverage(store)["status"] == "missing"
    sample = options(store)
    sample["observed_at"] = "2026-11-06T18:00:00"  # No timezone: expiry-day comparison is unknown.
    sample["contracts"] = [sample["contracts"][0]]
    sample["contracts"][0]["quote"]["bp"] = "NaN"
    sample["contracts"][0]["implied_volatility"] = "Infinity"
    sample["contracts"][0]["greeks"] = {"delta": False, "gamma": "NaN", "auxiliary_number": 123}
    store.set("options_research", sample)
    coverage = _option_coverage(store)
    assert coverage["expiry_from_observed_date"] == {"unknown": 1}
    assert coverage["counts"]["positive_two_sided_quotes"] == 0
    assert coverage["counts"]["positive_iv"] == coverage["counts"]["numeric_greeks"] == 0
    json.dumps(coverage, allow_nan=False)


def test_missing_group_card_is_explicit_without_creating_an_unrelated_topic(store):
    store.set("research_catalogue", [card(EARNINGS)])
    scope = by_kind(records(store, "held_earnings_iv"), "group_scope")[0]
    assert scope["missing_card_ids"] == [EVENT_IV]
    assert "held_vix_horizon" not in evidence_packets(store)


def test_exact_draft_contract_observation_and_screen_lineage_survive_complete_packet(store):
    current = card(REVERSAL, state="rejected", claim="Recovery after return_3d <= -3% with morning relative stabilization.",
                   predicted_outcome="Both prospective arms use the same six symbols and 60 entry sessions.",
                   observation_ids=["observation:amd", "observation:missing"], screen_trial_ids=[])
    store.set("research_catalogue", [current])
    earlier = card(REVERSAL, claim="The strict three-session-below-minus-3% screen had positive holdout and negative development stress.",
                   screen_trial_ids=["swing-reversal"])
    artifact(store, "earliest-reversal", earlier, at="2026-10-31T05:51:41+00:00")
    contracts = [{"id": "relative-stabilization", "hypothesis_id": REVERSAL, "branch": "swing",
                  "symbols": ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META"],
                  "predicates": [{"field": "return_3d", "operator": "lte", "value": -0.03},
                                 {"field": "relative_gap_spy", "operator": "gte", "value": 0.001}],
                  "hypothesis": "Prospective five-session ask-to-bid observation with 20bp/50bp costs.",
                  "falsification": "Nonpositive stressed mean or failed matched comparisons; missing inputs unknown.",
                  "minimum_sessions": 60, "minimum_signals": 30}]
    artifact(store, "latest-reversal", current, contracts)
    # Similar family names must not be used to supply missing exact identities.
    artifact(store, "unrelated-latest", card("unrelated-reversal"), [dict(contracts[0], id="unrelated")], "2026-11-05T12:00:00+00:00")
    observation = {"id": "observation:amd", "subject": "AMD", "observed_at": "2026-11-03T13:15:29+00:00",
                   "event_asof": "2026-11-02", "values": {"return_3d": -0.19308997553744145},
                   "provenance": {"input_ref": "input:exact", "source": "IEX daily bars"}}
    store.memory_put("observation:amd", "market_observation_lead", observation)
    store.memory_put("input:exact", "research_input", {"observed_at": "2026-11-03T13:15:23+00:00",
                     "packet": {"daily_indicators": {"AMD": {"return_3d": -0.19308997553744145, "asof": "2026-11-02"}}}})
    store.set("historical_screen", {"at": "2026-10-29T11:31:01+00:00", "dataset_sha256": "original-dataset",
              "split": "2026-06-04", "as_of_exclusive": "2026-10-29", "trials": [
                  {"id": "swing-reversal", "description": "Prior three-session return below -3%", "holding_sessions": 5,
                   "development": {"mean_daily_stress": -0.0000075646973180992845},
                   "holdout": {"sessions": 20, "opportunities": 600, "signals": 73, "mean_daily_stress": 0.00053233317889433}},
                  {"id": "unrelated", "claim": "Must not leak into matched lineage"}]})
    packet = evidence_packets(store)["held_reversal_lineage"]
    assert packet["omitted_records"] == 0 and len(dumps(packet)) <= PACKET_LIMIT
    values = packet["records"]
    lineage = by_kind(values, "draft_lineage")[0]
    assert lineage["latest_declared_screen_trial_ids"] == []
    assert lineage["draft_contract_ids"] == ["relative-stabilization"]
    assert by_kind(values, "matched_draft_contract")[0]["definition"] == contracts[0]
    screen = by_kind(values, "referenced_historical_screen")[0]
    assert screen["requested_trial_ids"] == ["swing-reversal"]
    assert screen["trials"][0]["development"]["mean_daily_stress"] < 0
    assert screen["trials"][0]["holdout"]["signals"] == 73
    assert "exact old reviewer input is not retained" in screen["scope"]
    observations = by_kind(values, "matched_observation")
    assert observations[0]["observation_sha256"] == _hash(observation)
    assert observations[0]["exact_input"]["id"] == "input:exact"
    assert observations[1] == {"observation_id": "observation:missing", "status": "missing"}
    assert by_kind(values, "registration_lookup")[0]["matched_contracts"] == []
    assert "unrelated" not in dumps(packet)
    prompt, _ = prepare_task(store, _context("held_reversal_lineage", packet))
    assert len(prompt) < 28000


def test_wmt_prediction_missing_from_catalogue_still_comes_from_exact_draft(store):
    current = card(RALLY, observation_ids=["observation:wmt"], review_reason="Predicted 16-stock universe conflicts with six-stock contract.")
    store.set("research_catalogue", [current])
    draft = {**current, "predicted_outcome": "Freeze the 16-stock universe for 60 future entry sessions."}
    contract = {"id": "rally-v1", "hypothesis_id": RALLY, "symbols": ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META"]}
    artifact(store, "rally-draft", draft, [contract])
    packet = records(store, "held_rally_universe")
    assert by_kind(packet, "draft_lineage")[0]["catalogue_differences"]["predicted_outcome"] == draft["predicted_outcome"]
    assert "WMT" not in by_kind(packet, "matched_draft_contract")[0]["definition"]["symbols"]
    assert by_kind(packet, "matched_observation")[0]["status"] == "missing"
    assert by_kind(packet, "matched_draft_contract")[0]["status"] == "proposed_not_registration"


def test_source_set_reports_cited_but_unsupplied_primary_source_and_refresh_dedupes(store):
    url = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
    current = card(VIX, source_urls=[url], sources=[], reviewed_at="2026-10-29T12:00:00Z")
    store.set("research_catalogue", [current])
    before = _context("held_vix_horizon", evidence_packets(store)["held_vix_horizon"])
    source_set = by_kind(before["evidence"]["records"], "source_set")[0]
    assert source_set["card_source_sets"][0]["missing_supplied_urls"] == [url]
    assert "not source-verification receipts" in source_set["scope"]
    current["reviewed_at"] = "2026-11-07T12:00:00Z"
    store.set("research_catalogue", [current])
    assert _context("held_vix_horizon", evidence_packets(store)["held_vix_horizon"])["work_id"] == before["work_id"]
    current["sources"] = [{"url": url, "title": "Official FOMC calendar", "takeaway": "Announced meeting dates", "observed_at": "2026-11-07T12:00:00Z"}]
    store.set("research_catalogue", [current])
    checked = _context("held_vix_horizon", evidence_packets(store)["held_vix_horizon"])
    assert checked["work_id"] != before["work_id"]
    current["sources"][0]["observed_at"] = "2026-11-07T13:00:00Z"
    store.set("research_catalogue", [current])
    assert _context("held_vix_horizon", evidence_packets(store)["held_vix_horizon"])["work_id"] == checked["work_id"]


def test_replayed_same_draft_changes_audit_snapshot_not_work_identity(store):
    current = card(RALLY)
    store.set("research_catalogue", [current])
    artifact(store, "original", current)
    before = _context("held_rally_universe", evidence_packets(store)["held_rally_universe"])
    artifact(store, "later-copy", current, at="2026-11-04T14:00:00+00:00")
    after = _context("held_rally_universe", evidence_packets(store)["held_rally_universe"])
    assert after["work_id"] == before["work_id"]
    assert after["snapshot_hash"] != before["snapshot_hash"]


def test_registered_contract_lookup_is_exact_and_new_observation_state_is_fresh_evidence(store):
    AdaptiveLab(store)
    store.set("research_catalogue", [card(RALLY)])
    definition = {"id": "exact", "hypothesis_id": RALLY}
    store.db.execute("INSERT INTO adaptive_contracts VALUES(?,?,?,?,?,?,?,?,?)",
                     ("exact", "swing", "observing", "2026-11-04T12:00:00Z", "2026-11-04", "spec-sha", "fp", dumps(definition), None))
    store.db.execute("INSERT INTO adaptive_contracts VALUES(?,?,?,?,?,?,?,?,?)",
                     ("other", "swing", "observing", "2026-11-04T12:00:00Z", "2026-11-04", "other-sha", "other-fp", dumps({"hypothesis_id": "other"}), None))
    before = _context("held_rally_universe", evidence_packets(store)["held_rally_universe"])
    registered = by_kind(before["evidence"]["records"], "registration_lookup")[0]["matched_contracts"]
    assert [c["id"] for c in registered] == ["exact"]
    assert registered[0]["specification_sha256"] == "spec-sha"
    assert registered[0]["observations_by_state"] == []
    store.db.execute("INSERT INTO adaptive_observations VALUES(?,?,?,?,?,?)", ("ob", "exact", "2026-11-05", "WMT", "missing", "{}"))
    after = _context("held_rally_universe", evidence_packets(store)["held_rally_universe"])
    assert after["work_id"] != before["work_id"]
    assert by_kind(after["evidence"]["records"], "registration_lookup")[0]["matched_contracts"][0]["observations_by_state"] == [{"state": "missing", "n": 1}]


def test_future_method_handoff_follows_current_events_and_preserves_held_scope(store, now):
    context, report = event_report(now)
    retain(store, context, report, now)
    store.set("research_catalogue", [card(VIX)])
    method = _context("held_vix_horizon", evidence_packets(store)["held_vix_horizon"])
    retain(store, method, draft_for(method), now + timedelta(seconds=1))
    short = reviewed_context(store, 3000, now + timedelta(seconds=2), ["NVDA", "AMD"])
    assert short[0]["topic"] == "event_coverage"
    assert {1, 3} <= {f["index"] for f in short[0]["findings"]}
    all_context = reviewed_context(store, 10000, now + timedelta(seconds=2), ["NVDA", "AMD"])
    held = next(r for r in all_context if r["topic"] == "held_vix_horizon")
    assert "held cards remain held" in held["scope"]
    assert "No order" in held["scope"]
    assert held["findings"][0]["qualification"] == draft_for(method)["findings"][0]["qualification"]


def test_valid_report_storage_preserves_provider_text_and_prompt_requests_complete_checks(store, now):
    store.set("research_catalogue", [card(RALLY)])
    context = _context("held_rally_universe", evidence_packets(store)["held_rally_universe"])
    report = draft_for(context)
    # Production revisions arrived already cut at 1200 characters. Storage must
    # neither invent the missing ending nor clip a provider's complete proposal.
    plan = "Replay immutable inputs at the original cutoff; compare declared formulas within fixed tolerances. " * 7
    plan += "Pass on exact supported reproduction, fail on a demonstrated discrepancy, and mark absent receipts unknown."
    assert 650 < len(plan) < 1200
    report["proposals"][0]["validation_plan"] = plan
    record_analysis(store, context, report, now.date().isoformat(), now.isoformat())
    stored = json.loads(store.rows("SELECT payload FROM memory WHERE id=?", ("research-work:" + context["work_id"] + ":analysis",))[0]["payload"])
    assert stored["result"] == report
    prompt, _ = prepare_task(store, context, review=True)
    assert plan in prompt
    assert "validation_plan under 650 characters" in prompt
    assert "never cut a word or sentence" in prompt


def test_option_probe_is_not_discovery_evidence_until_both_windows_are_terminal(store, monkeypatch):
    from agent_trader.runtime import options_coverage as probe
    from tests.runtime.test_options_coverage import registration, Clock, DataBroker, run, at

    store.set("research_catalogue", [card(EARNINGS), card(EVENT_IV)])
    baseline = options(store)
    before = _context("held_earnings_iv", evidence_packets(store)["held_earnings_iv"])
    reg = registration(store)
    assert _terminal_option_probe(store) is None
    assert _context("held_earnings_iv", evidence_packets(store)["held_earnings_iv"])["work_id"] == before["work_id"]
    clock, broker = Clock(), None
    broker = DataBroker(clock)
    run(store, broker, clock)
    assert _terminal_option_probe(store) is None
    assert _context("held_earnings_iv", evidence_packets(store)["held_earnings_iv"])["work_id"] == before["work_id"]
    clock.now = at(clock="10:15:00")
    run(store, broker, clock, 2)
    # Projection cannot collect data or create inference, even once eligible.
    monkeypatch.setattr(probe, "run_capture", lambda *a, **k: (_ for _ in ()).throw(AssertionError("projection must not collect")))
    changes, calls = store.db.total_changes, len(broker.calls)
    terminal = _terminal_option_probe(store)
    assert store.db.total_changes == changes and len(broker.calls) == calls
    assert terminal["expected_observations"] == len(terminal["observations"]) == 8
    assert terminal["iv_categories"] == {"positive": 8}
    assert terminal["selected_side_counts"] == {"call": 2, "put": 2}
    assert terminal["frozen_baseline"]["counts"] == [30, 30, 0, 30, 30, 0]
    assert terminal["frozen_baseline"]["iv"] == {"missing": 30}
    assert terminal["protocol_sha256"] == reg["protocol_sha256"]
    assert terminal["registration_id"] == reg["registration_id"]
    assert len(dumps(terminal)) <= 2500
    assert terminal["_observation_metadata"]["capture_sha256"]
    assert store.get("options_research") == baseline
    after = _context("held_earnings_iv", evidence_packets(store)["held_earnings_iv"])
    assert after["work_id"] != before["work_id"]
    assert _context("held_earnings_iv", evidence_packets(store)["held_earnings_iv"])["work_id"] == after["work_id"]
    # Even a timing-only receipt correction cannot manufacture new coverage.
    summary = probe.public_summary(store)
    summary["captures"][0]["completed_at"] = "2026-11-09T15:01:59+00:00"
    summary["captures"][0]["capture_sha256"] = "changed-audit-hash"
    monkeypatch.setattr(probe, "public_summary", lambda store: summary)
    same_facts = _context("held_earnings_iv", evidence_packets(store)["held_earnings_iv"])
    assert same_facts["work_id"] == after["work_id"]
    assert same_facts["snapshot_hash"] != after["snapshot_hash"]


def test_missed_probe_windows_retain_eight_unknowns_not_zero_iv(store):
    from agent_trader.runtime import options_coverage as probe
    from tests.runtime.test_options_coverage import registration, at

    registration(store)
    probe.due_capture(store, at(clock="10:18:00"))
    terminal = _terminal_option_probe(store)
    assert terminal["capture_states"] == [[1, "missed"], [2, "missed"]]
    assert terminal["iv_categories"] == {"unobserved": 8}
    assert len(terminal["observations"]) == 8
    assert all(row[6] is False and row[7] is not None for row in terminal["observations"])
    assert terminal["missing_reasons"]
    assert len(dumps(terminal)) <= 2500
    assert "IV as-of remains unknown" in terminal["scope"]
