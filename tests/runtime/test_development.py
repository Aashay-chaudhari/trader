import copy
import json

from agent_trader.runtime.development import assess_changes
from agent_trader.runtime.store import dumps

DAY = "2026-11-02"
FIXED = "2026-10-31T06:08:01+00:00"
RESEARCH_AT = "2026-11-02T15:00:00+00:00"


def setup(store, monkeypatch, changes=("artifact_history",)):
    monkeypatch.setattr(
        "agent_trader.runtime.development.utc_now", lambda: "2026-11-02T22:00:00+00:00"
    )
    store.set("calendar:" + DAY, [{"date": DAY, "open": "09:30", "close": "16:00"}])
    for identity in changes:
        store.set(
            "quality-fix:" + identity,
            {
                "at": FIXED,
                "source_commit": "deployed",
                "verification": "Tests passed; effects unobserved",
            },
        )
        store.memory_put(
            "quality-proposal:" + identity,
            "improvement_proposal",
            {
                "id": identity,
                "state": "code_changed_awaiting_observation",
                "first_seen": "first",
                "last_seen": "last",
                "evidence_day": "2026-10-30",
                "problem": "Original issue",
                "requested_change": "Original proposal",
                "code_receipt": {"source_commit": "deployed"},
            },
        )


def research(
    store, *, artifact=True, origin="live_task", outcome="applied", usage=True, state="completed"
):
    if usage:
        store.db.execute(
            "INSERT INTO usage(at,day,role,model,input_tokens,cached_tokens,output_tokens,quota_delta,payload) VALUES(?,?,?,?,0,0,0,0,?)",
            (RESEARCH_AT, DAY, "research", "model", dumps({"state": state})),
        )
    if artifact:
        store.memory_put(
            "artifact",
            "research_artifact",
            {
                "day": DAY,
                "role": "research",
                "origin": origin,
                "outcome": outcome,
                "observed_at": RESEARCH_AT,
                "input_observed_at": RESEARCH_AT,
                "result": {"summary": "No plan with explicit uncertainty", "plans": []},
            },
        )


def one(store, day=DAY, persist=False):
    return assess_changes(store, day, persist)["changes"][0]


def test_no_premature_effects_from_baseline_same_fix_day_or_still_open_session(store, monkeypatch):
    setup(store, monkeypatch)
    research(store)
    assert one(store, "2026-10-30")["state"] == "awaiting_observation"
    assert one(store, "2026-10-31")["evidence_day"] is None
    monkeypatch.setattr(
        "agent_trader.runtime.development.utc_now", lambda: "2026-11-02T20:59:59+00:00"
    )
    assert one(store)["state"] == "awaiting_observation"
    monkeypatch.setattr(
        "agent_trader.runtime.development.utc_now", lambda: "2026-11-02T22:00:00+00:00"
    )
    assert one(store)["state"] == "observed_mechanics"


def test_missing_or_naive_fix_timestamp_never_proves_effect(store, monkeypatch):
    setup(store, monkeypatch)
    research(store)
    for receipt in ({"source_commit": "x"}, {"at": "2026-10-31T06:08:01"}):
        store.set("quality-fix:artifact_history", receipt)
        assert one(store)["state"] == "awaiting_observation"
        assert one(store)["evidence_day"] is None


def test_artifact_check_distinguishes_failed_attempts_and_applied_rejected_outputs(
    store, monkeypatch
):
    setup(store, monkeypatch)
    research(store, outcome="rejected")
    store.db.execute(
        "INSERT INTO usage(at,day,role,model,input_tokens,cached_tokens,output_tokens,quota_delta,payload) VALUES(?,?,?,?,0,0,0,0,?)",
        (RESEARCH_AT, DAY, "research", "model", dumps({"state": "failed"})),
    )
    result = one(store)
    assert result["state"] == "observed_mechanics"
    assert result["metrics"]["completed_live_research_calls"] == 1
    assert result["metrics"]["rejected"] == 1
    # Matching capture counts say nothing about whether rejecting this plan was wise.
    assert "not a measured investment improvement" in result["scope"]


def test_legacy_artifacts_cannot_fill_missing_live_output_and_pure_probe_is_not_session(
    store, monkeypatch
):
    setup(store, monkeypatch)
    research(store, origin="legacy_latest_snapshot")
    assert one(store)["state"] == "needs_attention"
    assert one(store)["metrics"]["full_live_research_artifacts"] == 0
    store.db.execute("DELETE FROM usage")
    assert one(store)["state"] == "awaiting_observation"


def test_persist_updates_effect_state_without_rewriting_proposal_history(store, monkeypatch):
    setup(store, monkeypatch)
    research(store)
    old = store.rows("SELECT * FROM memory WHERE id='quality-proposal:artifact_history'")[0]
    before = json.loads(old["payload"])
    result = one(store, persist=True)
    after_row = store.rows("SELECT * FROM memory WHERE id='quality-proposal:artifact_history'")[0]
    after = json.loads(after_row["payload"])
    assert after["state"] == "observed_mechanics"
    for key in (
        "first_seen",
        "last_seen",
        "problem",
        "requested_change",
        "code_receipt",
        "evidence_day",
    ):
        assert after[key] == before[key]
    assert after_row["at"] == old["at"]
    assert after["development_effect"] == result
    assert store.get("development-effect:artifact_history") == result
    one(store, "2026-10-30", persist=True)
    assert store.get("development-effect:artifact_history") == result


def test_source_gate_allows_reviewed_local_observation_and_detects_missing_external_checks(
    store, monkeypatch
):
    setup(store, monkeypatch, ("source_verification",))
    research(store)
    local = {
        "id": "local",
        "state": "reviewed_for_testing",
        "evidence_basis": "local_observation",
        "source_urls": [],
        "source_check_status": "not_applicable",
        "checked_source_urls": [],
        "method_check_status": "reviewed",
        "observation_provenance_verified": True,
    }
    external = {
        "id": "external",
        "state": "reviewed_for_testing",
        "source_urls": ["https://example.org/paper"],
        "source_check_status": "verified",
        "checked_source_urls": ["https://example.org/paper"],
    }
    store.set("research_catalogue", [local, external])
    assert one(store)["state"] == "observed_mechanics"
    bad = copy.deepcopy(external)
    bad["checked_source_urls"] = []
    store.set("research_catalogue", [local, bad])
    assert one(store)["state"] == "needs_attention"
    assert one(store)["metrics"]["weak_card_ids"] == ["external"]
    local["method_check_status"] = "unreviewed"
    store.set("research_catalogue", [local])
    assert one(store)["state"] == "needs_attention"


def test_feature_mechanics_require_linked_live_inputs_and_fresh_completed_minutes(
    store, monkeypatch
):
    setup(store, monkeypatch, ("missing_price_features",))
    research(store)
    assert one(store)["state"] == "awaiting_observation"
    packet = {
        "observed_at": RESEARCH_AT,
        "daily_indicators": {"SPY": {"return_1d": 0.01, "return_3d": 0.02}},
        "intraday_indicators": {
            "SPY": {
                "asof": RESEARCH_AT,
                "last_completed_close": 100,
                "bar_vwap_iex": 99.9,
                "opening_5m_complete": True,
                "missing_minute_intervals": 0,
            }
        },
    }
    store.memory_put(
        "input", "research_input", {"day": DAY, "observed_at": RESEARCH_AT, "packet": packet}
    )
    assert one(store)["state"] == "observed_mechanics"
    packet["intraday_indicators"]["SPY"]["asof"] = "2026-11-02T14:57:59+00:00"
    store.memory_put(
        "input", "research_input", {"day": DAY, "observed_at": RESEARCH_AT, "packet": packet}
    )
    assert one(store)["state"] == "needs_attention"
    packet["intraday_indicators"]["SPY"]["asof"] = "2026-11-02T15:00:01+00:00"
    store.memory_put(
        "input", "research_input", {"day": DAY, "observed_at": RESEARCH_AT, "packet": packet}
    )
    assert one(store)["state"] == "needs_attention"


def test_empty_plans_no_material_pulse_and_independent_reviews_are_not_failure(store, monkeypatch):
    setup(store, monkeypatch, ("stale_pulses", "duplicate_period_reviews"))
    research(store)
    store.memory_put(
        "pulse",
        "research_artifact",
        {
            "day": DAY,
            "role": "pulse",
            "origin": "live_task",
            "outcome": "applied",
            "result": {"material_change": False},
        },
    )
    report = assess_changes(store, DAY)
    assert all(c["state"] == "awaiting_observation" for c in report["changes"])
    assert (
        next(c for c in report["changes"] if c["id"] == "stale_pulses")["metrics"][
            "declared_material_changes"
        ]
        == 0
    )


def test_derived_rollups_must_be_explicitly_labeled(store, monkeypatch):
    setup(store, monkeypatch, ("duplicate_period_reviews",))
    research(store)
    artifact = {
        "day": DAY,
        "role": "weekly",
        "origin": "derived_period_review",
        "result": {
            "derived_from": "daily:" + DAY,
            "independent_model_review": False,
            "scope_note": "Identical window",
        },
    }
    store.memory_put("weekly", "research_artifact", artifact)
    assert one(store)["state"] == "observed_mechanics"
    artifact["result"].pop("scope_note")
    store.memory_put("weekly", "research_artifact", artifact)
    assert one(store)["state"] == "needs_attention"


def test_assessment_is_read_only_by_default_and_empty_registry_is_valid(store, monkeypatch):
    setup(store, monkeypatch)
    research(store)
    old = store.rows("SELECT payload FROM memory WHERE id='quality-proposal:artifact_history'")[0][
        "payload"
    ]
    assess_changes(store, DAY)
    assert store.get("development-effect:artifact_history") is None
    assert (
        store.rows("SELECT payload FROM memory WHERE id='quality-proposal:artifact_history'")[0][
            "payload"
        ]
        == old
    )
    store.db.execute("DELETE FROM kv WHERE key LIKE 'quality-fix:%'")
    assert assess_changes(store, DAY)["changes"] == []
