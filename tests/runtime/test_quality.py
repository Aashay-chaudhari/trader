from datetime import datetime, timedelta

import pytest

from agent_trader.runtime.broker import Broker
from agent_trader.runtime.config import ET
from agent_trader.runtime.features import minute_features
from agent_trader.runtime.exploration import (
    record_report,
    record_validation,
    knowledge_context,
    exploration_prompt,
)
from agent_trader.runtime.quality import record_artifact, daily_audit, derive_period, pulse_prompt
from agent_trader.runtime.store import utc_now


def minute(at, price=100, volume=10):
    return {
        "t": at.isoformat(),
        "o": price,
        "h": price + 2,
        "l": price - 2,
        "c": price + 1,
        "v": volume,
        "vw": price + 0.5,
    }


def test_minute_features_exclude_future_incomplete_and_other_sessions():
    opened = datetime(2026, 10, 30, 9, 30, tzinfo=ET)
    now = opened + timedelta(minutes=5)
    rows = [minute(opened + timedelta(minutes=i), 100 + i) for i in range(6)]
    rows += [minute(opened - timedelta(minutes=1), 1), minute(opened + timedelta(days=1), 999)]
    f = minute_features({"SPY": rows}, now, opened, opened.replace(hour=16))["SPY"]
    assert f["observed_minute_bars"] == 5 and f["opening_5m_complete"]
    assert f["high_so_far"] == 106 and f["low_so_far"] == 98
    assert f["bar_vwap_iex"] == 102.5 and f["session_volume_iex"] == 50
    assert f["age_seconds"] == 0 and f["missing_minute_intervals"] == 0


def test_missing_minute_or_vwap_remains_unknown_not_synthetic():
    opened = datetime(2026, 10, 30, 9, 30, tzinfo=ET)
    a = minute(opened)
    b = minute(opened + timedelta(minutes=2), 102)
    b.pop("vw")
    f = minute_features(
        {"SPY": [a, b]}, opened + timedelta(minutes=5), opened, opened.replace(hour=16)
    )["SPY"]
    assert f["bar_vwap_iex"] is None and f["vwap_volume_coverage"] == 0.5
    assert not f["opening_5m_complete"] and f["opening_5m_high"] is None
    assert f["missing_minute_intervals"] == 3


def test_free_bar_pagination_preserves_later_symbols_and_feed():
    b = Broker.__new__(Broker)
    calls = []
    pages = iter(
        [
            {"bars": {"AAPL": [{"t": "one"}]}, "next_page_token": "next"},
            {"bars": {"SPY": [{"t": "two"}]}, "next_page_token": None},
        ]
    )

    def request(*args, **kw):
        calls.append(kw["params"])
        return next(pages)

    b.request = request
    now = datetime.now(ET)
    assert set(b.intraday_bars(["AAPL", "SPY"], now - timedelta(minutes=10), now)) == {
        "AAPL",
        "SPY",
    }
    assert calls[1]["page_token"] == "next" and all(c["feed"] == "iex" for c in calls)


@pytest.mark.parametrize("repeat", [True, False])
def test_incomplete_page_batches_are_rejected_instead_of_returned(repeat):
    b = Broker.__new__(Broker)
    n = 0

    def request(*a, **k):
        nonlocal n
        n += 1
        return {"bars": {"AAPL": [{"t": str(n)}]}, "next_page_token": "same" if repeat else str(n)}

    b.request = request
    with pytest.raises(ValueError, match="pagination"):
        b.bar_pages({"symbols": "AAPL,SPY", "feed": "iex"}, max_pages=2)


def research_report():
    return {
        "summary": "A bounded mechanism to test",
        "hypotheses": [
            {
                "id": "quality-hypothesis",
                "branch": "swing",
                "family": "reversal",
                "claim": "Reversal is a descriptive research lead only.",
                "mechanism": "Liquidity provision may motivate a falsifiable observation.",
                "falsification": "Frozen forward observations net of stated costs.",
                "free_data_feasibility": "limited",
                "source_urls": ["https://example.com/primary"],
                "screen_trial_ids": [],
                "experiment_ids": [],
            }
        ],
        "experiments": [],
        "shadow_plans": [],
        "sources": [
            {
                "title": "Primary source",
                "url": "https://example.com/primary",
                "published_at": None,
                "observed_at": utc_now(),
                "takeaway": "Hypothesis generation, not edge.",
            }
        ],
        "uncertainties": [],
    }


@pytest.mark.parametrize(
    "status,checked",
    [
        ("unverified", []),
        ("partial", ["https://example.com/primary"]),
        ("verified", []),
        ("verified", ["https://example.com/other"]),
    ],
)
def test_accept_verdict_cannot_bypass_explicit_independent_source_checks(store, status, checked):
    record_report(store, research_report(), "2026-10-30")
    record_validation(
        store,
        {
            "summary": "Source review",
            "hypotheses": [
                {
                    "id": "quality-hypothesis",
                    "verdict": "accepted_for_testing",
                    "reason": "A mechanism worth testing.",
                    "source_check_status": status,
                    "checked_source_urls": checked,
                }
            ],
        },
    )
    assert store.get("research_catalogue")[0]["state"] == "needs_work"
    assert not knowledge_context(store)["reviewed_research"]
    assert not store.rows("SELECT * FROM experiments")


def test_missing_source_check_fields_fail_closed_for_legacy_shaped_output(store):
    record_report(store, research_report(), "2026-10-30")
    record_validation(
        store,
        {
            "summary": "Source review",
            "hypotheses": [
                {
                    "id": "quality-hypothesis",
                    "verdict": "accepted_for_testing",
                    "reason": "URL is supplied but content was not checked.",
                }
            ],
        },
    )
    assert store.get("research_catalogue")[0]["state"] == "needs_work"


def test_failed_outputs_are_preserved_without_becoming_no_plan_evidence(store):
    for i, outcome in enumerate(("rejected", "applied")):
        record_artifact(
            store,
            "2026-10-30",
            "research",
            {"summary": "test", "plans": [], "unknowns": ["VWAP is unavailable"]},
            "same-retried-task",
            outcome=outcome,
            observed_at=f"2026-10-30T12:00:0{i}+00:00",
        )
    report = daily_audit(store, "2026-10-30", persist=True)
    assert len(store.rows("SELECT * FROM memory WHERE layer='research_artifact'")) == 2
    assert report["known_no_plan_research_outputs"] == 1
    assert report["artifact_counts"]["research"] == 1
    daily_audit(store, "2026-10-30", persist=True)
    assert len(store.rows("SELECT * FROM memory WHERE layer='improvement_proposal'")) == 1


def test_quality_uses_telemetry_and_reports_missing_artifacts_honestly(store):
    for _ in range(3):
        store.db.execute(
            "INSERT INTO usage(at,day,role,model,input_tokens,cached_tokens,output_tokens,quota_delta,payload) VALUES(?,?,?,?,?,?,?,?,?)",
            (utc_now(), "2026-10-30", "research", "test", 100, 80, 10, 0, '{"searches":2}'),
        )
    record_artifact(
        store,
        "2026-10-30",
        "research",
        {"summary": "Model claims 99 searches", "sources": [], "plans": []},
        "surviving",
        origin="legacy_latest_snapshot",
    )
    r = daily_audit(store, "2026-10-30")
    assert r["measured_usage"]["web_actions"] == 6
    assert r["legacy_snapshot_artifacts"] == 1 and r["artifact_counts"]["research"] == 1
    assert "artifact_history" in {f["id"] for f in r["findings"]}


def test_pulse_context_uses_latest_updates_without_large_stale_brief(store):
    store.set(
        "pulses",
        [{"at": "2026-10-30T17:00:00Z", "summary": "A newly verified release", "sources": []}],
    )
    p = pulse_prompt(
        {"brief": {"summary": "Morning baseline", "rates_bonds": "x" * 20000}, "symbols": []}, store
    )
    assert "A newly verified release" in p and "x" * 100 not in p
    assert "market context only" in p and len(p) < 5000


def test_period_reuse_requires_identical_retained_evidence_windows(store):
    store.set("review_day", "2026-10-30")
    store.set("review", {"summary": "Daily evidence", "observations": []})
    d = derive_period(store, "weekly", "2026-10-30")
    assert d["derived_from"] == "daily:2026-10-30" and not d["independent_model_review"]
    store.db.execute(
        "INSERT INTO events(at,kind,payload) VALUES(?,?,?)",
        ("2026-10-29T14:00:00+00:00", "incident", '{"reason":"Missed earlier session"}'),
    )
    assert derive_period(store, "weekly", "2026-10-30") is None
    store.set("weekly:2026-10-30", {"summary": "Includes Thursday incident"})
    assert derive_period(store, "monthly", "2026-10-30")["derived_from"] == "weekly:2026-10-30"
    store.db.execute(
        "INSERT INTO equity(at,day,branch,value) VALUES(?,?,?,?)",
        ("2026-10-15T14:00:00+00:00", "2026-10-15", "swing", 9999),
    )
    assert derive_period(store, "monthly", "2026-10-30") is None


def test_exploration_gets_exact_existing_contract_terms(store):
    from agent_trader.runtime.exploration import seed_challengers

    seed_challengers(store)
    p = exploration_prompt("2026-10-30", store, {"trials": []})
    assert "parent_version" in p and "pilot-v1" in p and "exact_change" in p


def test_maintenance_packet_keeps_complete_audit_json(config):
    import json
    from agent_trader.runtime.maintenance import maintenance_prompt

    source = config.root / "src/agent_trader/strategies/adaptive.py"
    source.parent.mkdir(parents=True)
    source.write_text('VERSION="test"\ndef candidate_filter(plan, context):\n return True\n')
    prompt = maintenance_prompt(
        config,
        {
            "summary": "x" * 20000,
            "observations": ["y" * 5000] * 40,
            "code_changes": [],
            "research_quality_audit": {
                "day": "2026-10-30",
                "findings": [
                    {
                        "id": "source_verification",
                        "problem": "Unverified source accepted",
                        "requested_change": "Require independent attestations",
                        "validation_plan": "Hold unchecked URLs",
                    }
                ],
            },
        },
    )
    packet = json.loads(prompt.split("DAILY REVIEW:\n")[1])
    assert packet["research_quality_audit"]["findings"][0]["id"] == "source_verification"
    assert len(prompt) < config.max_input_chars


def test_daily_packet_has_exact_three_day_return_and_preserved_input(store, monkeypatch):
    from agent_trader.runtime import research, calendars

    class Data:
        def snapshots(self, symbols):
            return {s: {"latestQuote": {"bp": 100, "ap": 100.01, "t": utc_now()}} for s in symbols}

        def bars(self, symbols):
            start = datetime.now(ET) - timedelta(days=60)
            return {
                s: [
                    {
                        "t": (start + timedelta(days=i)).isoformat(),
                        "o": 100 + i,
                        "h": 102 + i,
                        "l": 99 + i,
                        "c": 100 + i,
                        "v": 1000,
                    }
                    for i in range(60)
                ]
                for s in symbols
            }

        def calendar(self, day):
            return []

        def option_chain(self, symbol):
            return {"snapshots": {}}

    monkeypatch.setattr(
        calendars, "official_calendar", lambda *a: {"sources": [], "unknowns": [], "events": []}
    )
    monkeypatch.setattr(
        "httpx.get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline test"))
    )
    packet = research.market_packet(Data(), store)
    assert packet["daily_indicators"]["SPY"]["return_3d"] == 159 / 156 - 1
    assert len(packet["focus_symbols"]) == 3
    prompt = research.research_prompt(datetime.now(ET).date().isoformat(), packet, store)
    assert len(prompt) < 28000 and "return_3d" in prompt
    assert len(store.rows("SELECT * FROM memory WHERE layer='research_input'")) == 1


def test_flat_session_has_only_one_midday_context_pulse(config, broker, monkeypatch):
    from agent_trader.runtime import supervisor

    monkeypatch.setattr(supervisor, "Broker", lambda _: broker)
    monkeypatch.setattr(supervisor, "notify", lambda *a, **k: True)
    s = supervisor.Supervisor(config)
    calls = []
    current = datetime.now(ET).replace(hour=11, minute=0, second=0, microsecond=0)
    day = current.date().isoformat()
    broker.clock = lambda: {"is_open": True, "timestamp": current.isoformat()}
    s.store.set("calendar:" + day, [{"open": "09:30", "close": "16:00"}])
    s.store.set("preflight_day", day)
    s.store.set("brief_day", day)
    s.store.set("readiness", {"execution_verified": True, "funded": True, "models_available": True})
    s.maybe_publish = lambda: None
    s.launch = lambda key, role, *args: calls.append((key, role)) or False
    try:
        s.tick(current)
        assert calls == []
        current = current.replace(hour=13)
        s.tick(current)
        assert len(calls) == 1 and calls[0][1] == "pulse"
        current = current.replace(hour=14, minute=30)
        s.tick(current)
        assert len(calls) == 1 and broker.submissions == 0
    finally:
        s.pool.shutdown(wait=False)
        s.publisher_pool.shutdown(wait=False)
        s.store.close()


def test_period_review_uses_final_day_audit_and_excludes_later_events(store):
    import json
    from agent_trader.runtime.research import review_prompt

    for at, code in [
        ("2026-10-30T15:00:00+00:00", "in_period"),
        ("2026-10-31T05:00:00+00:00", "later_development"),
    ]:
        store.db.execute(
            "INSERT INTO events(at,kind,payload) VALUES(?,?,?)",
            (at, "incident", json.dumps({"code": code})),
        )
    p = review_prompt("2026-10-01", store, end_day="2026-10-30")
    data = json.loads(p.split("ROLE: retrospective and experiment designer.\n")[1])
    assert data["day"] == "2026-10-30" and data["review_window"]["start"] == "2026-10-01"
    assert data["research_quality_audit"]["day"] == "2026-10-30"
    assert [e["facts"]["code"] for e in data["selected_events"]] == ["in_period"]
    assert data["event_counts"] == [{"kind": "incident", "n": 1}]
    # Current operational diagnoses remain available under a separate as-of scope.
    assert "later_development" in json.dumps(data["operational_evidence"])
    assert "later diagnoses" in data["operational_evidence"]["snapshot_scope"]
