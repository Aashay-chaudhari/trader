import copy
import json

import pytest
from datetime import datetime, timedelta, timezone


from agent_trader.runtime.calendars import parse_calendar, official_calendar
from agent_trader.runtime.cohorts import ForwardLab, freeze_signals, normalized_screen
from agent_trader.runtime.config import ET
from agent_trader.runtime.project import project_snapshot, session_coverage


def raw_bars(day="2026-10-30"):
    start = datetime.fromisoformat(day).replace(tzinfo=ET) - timedelta(days=50)
    rows = [
        {
            "t": (start + timedelta(days=i)).isoformat(),
            "o": 100 + i,
            "h": 102 + i,
            "l": 99 + i,
            "c": 101 + i,
            "v": 1000,
        }
        for i in range(50)
    ]
    return {"AAPL": rows, "SPY": rows}


def sessions():
    rows = []
    day = datetime(2026, 10, 30).date()
    while len(rows) < 26:
        if day.weekday() < 5:
            rows.append({"date": day.isoformat(), "open": "09:30", "close": "16:00"})
        day += timedelta(days=1)
    return rows


def quotes(now, bid=150, ask=150.01):
    return {s: {"bp": bid, "ap": ask, "t": now.isoformat()} for s in ("AAPL", "SPY")}


def test_cohorts_preregistered_before_open_and_idempotent(store):
    before = datetime(2026, 10, 30, 8, 15, tzinfo=ET)
    snapshot = freeze_signals(store, raw_bars(), sessions(), before)
    frozen = copy.deepcopy(snapshot)
    import hashlib

    assert (
        hashlib.sha256(
            json.dumps(
                store.get("cohort-inputs:2026-10-30"), sort_keys=True, allow_nan=False
            ).encode()
        ).hexdigest()
        == snapshot["data_sha256"]
    )
    altered = raw_bars()
    altered["AAPL"][-1]["c"] = 999
    assert freeze_signals(store, altered, sessions(), before + timedelta(minutes=20)) == frozen
    lab = ForwardLab(store)
    opened = before.replace(hour=9, minute=30)
    closed = opened.replace(hour=16, minute=0)
    lab.observe(quotes(opened), opened, opened, closed)
    assert not store.rows("SELECT * FROM cohort_observations")
    now = opened + timedelta(minutes=5)
    lab.observe(quotes(now), now, opened, closed)
    lab.observe(quotes(now), now, opened, closed)
    assert len(store.rows("SELECT * FROM cohort_observations")) == 24
    assert not store.rows("SELECT * FROM orders") and not store.rows("SELECT * FROM plans")
    swing = json.loads(
        store.rows("SELECT payload FROM cohort_observations WHERE branch='swing' LIMIT 1")[0][
            "payload"
        ]
    )
    assert swing["exit_at"] == "2026-11-05T15:48:00-05:00"  # actual sessions cross DST
    assert swing["promotion_eligible"] is False


def test_no_after_open_freeze_or_historical_backfill(store):
    now = datetime(2026, 10, 30, 10, 0, tzinfo=ET)
    assert freeze_signals(store, raw_bars(), sessions(), now) is None
    assert not store.get("cohort-signals:2026-10-30")


def test_cohort_missing_exit_not_filled_next_day(store):
    now = datetime(2026, 10, 30, 8, 15, tzinfo=ET)
    freeze_signals(store, raw_bars(), sessions(), now)
    lab = ForwardLab(store)
    opened = now.replace(hour=9, minute=30)
    closed = opened.replace(hour=16, minute=0)
    entry = opened + timedelta(minutes=5)
    lab.observe(quotes(entry), entry, opened, closed)
    next_day = now + timedelta(days=3, hours=2)
    lab.mark(quotes(next_day, bid=155, ask=155.01), next_day)
    assert (
        len(
            store.rows(
                "SELECT * FROM cohort_observations WHERE branch='intraday' AND state='not_evaluable'"
            )
        )
        == 12
    )
    assert not store.rows(
        "SELECT * FROM cohort_observations WHERE branch='intraday' AND state='closed'"
    )


def test_forward_costs_and_untradeable_abstentions_explicit(store):
    now = datetime(2026, 10, 30, 8, 15, tzinfo=ET)
    freeze_signals(store, raw_bars(), sessions(), now)
    lab = ForwardLab(store)
    opened = now.replace(hour=9, minute=30)
    closed = opened.replace(hour=16, minute=0)
    entry = opened + timedelta(minutes=5)
    lab.observe(quotes(entry), entry, opened, closed)
    exit_at = closed - timedelta(minutes=12)
    lab.mark(quotes(exit_at, bid=151, ask=151.01), exit_at)
    closed_rows = store.rows(
        "SELECT * FROM cohort_observations WHERE branch='intraday' AND state='closed'"
    )
    assert len(closed_rows) == 12
    payloads = [json.loads(r["payload"]) for r in closed_rows]
    assert all(p["observed_signal_horizon_return"] == 0 for p in payloads if not p["signal"])
    assert all(
        p["observed_signal_horizon_return"] < 151 / 150.01 - 1 for p in payloads if p["signal"]
    )
    assert all(p["observed_baseline_horizon_return"] != 0 for p in payloads)
    assert all(t["entry_sessions"] <= 1 for t in lab.summary()["trials"])


def test_signal_snapshot_excludes_same_day_bars(store):
    now = datetime(2026, 10, 30, 8, 15, tzinfo=ET)
    bars = raw_bars()
    bars["AAPL"].append({"t": now.isoformat(), "o": 999, "c": 999, "h": 999, "l": 999, "v": 1000})
    r = freeze_signals(store, bars, sessions(), now)
    assert r["last_completed_session"] == "2026-10-29"


def test_normalized_screen_preserves_hash_and_frozen_data():
    trial = {
        "id": "swing-reversal",
        "holding_sessions": 5,
        "development": {
            "sessions": 20,
            "opportunities": 600,
            "signals": 73,
            "mean_daily_net": 0.001,
            "mean_daily_stress": 0.0005,
            "mean_daily_baseline": -0.001,
        },
        "holdout": {
            "sessions": 20,
            "opportunities": 600,
            "signals": 73,
            "mean_daily_net": 0.001,
            "mean_daily_stress": 0.0005,
            "mean_daily_baseline": -0.001,
        },
    }
    raw = {"dataset_sha256": "immutable", "trials": [trial]}
    original = copy.deepcopy(raw)
    view = normalized_screen(raw)
    assert raw == original and view["dataset_sha256"] == "immutable"
    assert "mean_daily_net" not in json.dumps(view)
    assert view["trials"][0]["holdout"]["mean_horizon_net_return"] == 0.001
    assert "Not a portfolio daily return" in view["metric_contract"]["not"]


def test_official_calendar_timezone_fold_and_unknown_timing():
    text = """BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:Employment
  Cost Index
DTSTART;TZID=America/New_York:20261030T083000
URL:https://www.bls.gov/news.release/eci.htm
END:VEVENT
BEGIN:VEVENT
SUMMARY:Date only
DTSTART;VALUE=DATE:20261102
END:VEVENT
BEGIN:VEVENT
SUMMARY:Floating time
DTSTART:20261103T100000
END:VEVENT
END:VCALENDAR"""
    events = parse_calendar(
        text, "BLS", "https://www.bls.gov/schedule/", datetime.now(timezone.utc).isoformat()
    )
    assert events[0]["when"] == "2026-10-30T08:30:00-04:00"
    assert events[0]["timing_known"] and "Cost Index" in events[0]["title"]
    assert not events[1]["timing_known"] and not events[2]["timing_known"]


def test_official_calendar_failure_not_silent_empty_success(store, monkeypatch):
    from agent_trader.runtime import calendars

    monkeypatch.setattr(
        calendars.httpx,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    packet = official_calendar(store)
    assert len(packet["unknowns"]) == 2 and all(
        s["status"] == "unavailable" for s in packet["sources"]
    )
    assert packet["events"] == []


def test_session_coverage_is_not_inferred_from_drills_or_partial_tracking(store):
    day = "2026-10-30"
    opened = datetime(2026, 10, 30, 9, 30, tzinfo=ET)
    store.set("calendar:" + day, [{"open": "09:30", "close": "13:00"}])
    store.set("release", {"recovery_drills": {"interrupt": True}})
    store.set("coverage_tracking_started", (opened + timedelta(hours=1)).isoformat())
    for slot in range(42):
        store.db.execute(
            "INSERT INTO session_health VALUES(?,?,?,?,?)",
            (day, slot, (opened + timedelta(minutes=5 * slot)).isoformat(), 1, 1),
        )
    assert session_coverage(store, opened + timedelta(hours=5))["complete_sessions"] == 0
    store.set("coverage_tracking_started", (opened - timedelta(hours=1)).isoformat())
    assert session_coverage(store, opened + timedelta(hours=5))["complete_sessions"] == 1
    store.db.execute("DELETE FROM session_health WHERE slot BETWEEN 8 AND 12")
    assert session_coverage(store, opened + timedelta(hours=5))["complete_sessions"] == 0


def test_project_does_not_invent_profitability_or_execution_success(config, store):
    store.set("missed_session_recorded:2026-10-29", True)
    p = project_snapshot(config, store)
    assert "operationally missed" in p["assessment"]
    assert p["evidence"]["filled_orders"] == 0 and p["stage"] == "operational_validation"
    assert "probability" in p["assessment_basis"]
    assert not any(m["state"] == "passed" for m in p["milestones"])


def rpc_fixture(config, monkeypatch, messages):
    from agent_trader.runtime.agent import CodexRPC

    rpc = CodexRPC.__new__(CodexRPC)
    rpc.config = config
    rpc.workspace = config.state_dir
    rpc.backlog = []
    sent = []
    rpc.send = lambda message: sent.append(message)
    rpc.rpc = lambda method, params: (
        {"thread": {"id": "thread-test"}}
        if method == "thread/start"
        else {"turn": {"id": "turn-test"}}
    )
    iterator = iter(messages)
    rpc.receive = lambda deadline: next(iterator)
    return rpc, sent


def test_soft_budget_notice_finishes_without_relaxing_hard_limit(config, monkeypatch):
    from agent_trader.runtime.agent import AgentUnavailable

    messages = [
        {"method": "item/started", "params": {"item": {"type": "webSearch"}}},
        {"method": "item/completed", "params": {"item": {"type": "webSearch"}}},
        {"id": 999998, "result": {"turnId": "turn-test"}},
        {
            "method": "item/completed",
            "params": {"item": {"type": "agentMessage", "text": '{"ok":true}'}},
        },
        {"method": "turn/completed", "params": {"turn": {"status": "completed"}}},
    ]
    rpc, sent = rpc_fixture(config, monkeypatch, messages)
    _, payload, _, counts = rpc.run(
        None, "Bounded check", config.research_model, "low", {}, max_searches=2
    )
    assert payload == {"ok": True} and counts["budget_notice"]
    assert counts["budget_notice_status"] == "accepted"
    assert sent[0]["method"] == "turn/steer" and sent[0]["params"]["expectedTurnId"] == "turn-test"
    excessive = [{"method": "item/started", "params": {"item": {"type": "webSearch"}}}] * 2
    rpc, sent = rpc_fixture(config, monkeypatch, excessive)
    with pytest.raises(AgentUnavailable, match="budget exhausted"):
        rpc.run(None, "Bounded check", config.research_model, "low", {}, max_searches=1)
    assert sent[-1]["method"] == "turn/interrupt"


def test_review_packet_is_complete_json_and_reports_selection(store):
    from agent_trader.runtime.research import review_prompt

    for i in range(80):
        store.event(
            "incident",
            {"summary": "x" * 5000, "code": "failure-" + str(i), "raw_large_blob": "y" * 10000},
        )
    prompt = review_prompt("2026-01-01", store)
    context = json.loads(prompt.split("ROLE: retrospective and experiment designer.\n", 1)[1])
    assert len(prompt) < 28000
    assert context["event_counts"] == [{"kind": "incident", "n": 80}]
    assert len(context["selected_events"]) <= 40 and "instructions" in context
    assert "raw_large_blob" not in prompt


def test_observational_lab_failure_does_not_prevent_owned_exit(config, broker, monkeypatch, plan):
    from agent_trader.runtime import supervisor

    monkeypatch.setattr(supervisor, "Broker", lambda _: broker)
    s = supervisor.Supervisor(config)
    try:
        now = datetime.now(ET)
        day = now.date().isoformat()
        p = {**plan, "expires_at": (now + timedelta(hours=1)).isoformat()}
        s.engine.add_plans([p], day)
        s.store.db.execute(
            "INSERT INTO holdings VALUES(?,?,?,?,?)", ("AAPL", "intraday", 1, 100, p["id"])
        )
        s.store.set(
            "exit-intent:AAPL",
            {
                "at": now.isoformat(),
                "reason": "Verified thesis invalidation",
                "plan_id": p["id"],
                "branch": "intraday",
            },
        )
        s.store.set("calendar:" + day, [{"open": "09:30", "close": "16:00"}])
        s.cohorts.symbols = lambda *args: (_ for _ in ()).throw(
            RuntimeError("research data problem")
        )
        s.cohorts.observe = lambda *args: (_ for _ in ()).throw(
            RuntimeError("research data problem")
        )
        s.cohorts.mark = lambda *args: (_ for _ in ()).throw(RuntimeError("research data problem"))
        exits = []
        s.engine.exit_holding = lambda *args: exits.append(args) or True
        s.market_tick(now, now + timedelta(hours=1))
        assert exits and exits[0][0] == "AAPL"
        assert s.store.rows("SELECT * FROM events WHERE kind='cohort_error'")
    finally:
        s.pool.shutdown(wait=False)
        s.publisher_pool.shutdown(wait=False)
        s.store.close()


def test_missing_entry_is_counted_not_zero_return_or_silently_dropped(store):
    before = datetime(2026, 10, 30, 8, 15, tzinfo=ET)
    freeze_signals(store, raw_bars(), sessions(), before)
    assert store.rows("SELECT count(*) n FROM cohort_expected")[0]["n"] == 24
    lab = ForwardLab(store)
    lab.expire(before.replace(hour=10, minute=1))
    rows = store.rows("SELECT * FROM cohort_observations")
    assert len(rows) == 24 and all(r["state"] == "not_evaluable" for r in rows)
    assert not any("observed_signal_horizon_return" in json.loads(r["payload"]) for r in rows)
    assert all(t["mean_horizon_net_return"] is None for t in lab.summary()["trials"])
    assert sum(t["preregistered_opportunities"] for t in lab.summary()["trials"]) == 24


def test_advance_signal_freeze_uses_actual_capture_time_and_completed_day(store):
    data = raw_bars("2026-10-30")
    cal = [{"date": "2026-10-29", "open": "09:30", "close": "16:00"}, *sessions()]
    too_early = datetime(2026, 10, 29, 17, 0, tzinfo=ET)
    assert freeze_signals(store, data, cal, too_early, for_day="2026-10-30") is None
    now = too_early.replace(hour=20, minute=30)
    result = freeze_signals(store, data, cal, now, for_day="2026-10-30")
    assert result["day"] == "2026-10-30" and result["frozen_at"] == now.isoformat()
    assert result["last_completed_session"] == "2026-10-29"
    assert not store.rows("SELECT * FROM cohort_observations")


def test_started_protocol_cannot_be_amended_silently(store, monkeypatch):
    from agent_trader.runtime import cohorts

    before = datetime(2026, 10, 30, 8, 15, tzinfo=ET)
    freeze_signals(store, raw_bars(), sessions(), before)
    old = copy.deepcopy(cohorts.PROTOCOL)
    monkeypatch.setitem(cohorts.PROTOCOL, "cost_formula", "changed after observations")
    with pytest.raises(ValueError, match="cannot be silently amended"):
        cohorts.register_study(store, sessions(), before.replace(hour=10))
    assert store.get("cohort_study")["protocol"] == old


def test_failed_calendar_fetch_is_backed_off_without_claiming_coverage(store, monkeypatch):
    from agent_trader.runtime import calendars

    calls = []

    def fail(*args, **kwargs):
        calls.append(args)
        raise RuntimeError("offline")

    monkeypatch.setattr(calendars.httpx, "get", fail)
    now = datetime(2026, 10, 30, 8, 15, tzinfo=ET)
    official_calendar(store, now)
    result = official_calendar(store, now + timedelta(minutes=5))
    assert len(calls) == 2
    assert all(s["status"] == "unavailable" for s in result["sources"])
    assert len(result["unknowns"]) == 2
    official_calendar(store, now + timedelta(minutes=31))
    assert len(calls) == 4


def test_role_context_is_bounded_and_decision_uses_fresh_evidence(config, monkeypatch):
    from agent_trader.runtime import agent
    from agent_trader.runtime.models import Decision
    from agent_trader.runtime.store import Store

    day = datetime.now(ET).date().isoformat()
    s = Store(config.state_dir / "trader.sqlite3")
    seen = []

    class RPC:
        def __init__(self, _):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def rate_limits(self):
            return {
                "ordinary_usage_allowed": True,
                "windows": [
                    {
                        "usedPercent": 5,
                        "windowDurationMins": 10080,
                        "resetsAt": int(
                            (datetime.now(timezone.utc) + timedelta(days=5)).timestamp()
                        ),
                    }
                ],
            }

        def run(self, thread_id, *args, **kwargs):
            seen.append(thread_id)
            return (
                "bounded-thread",
                {
                    "plan_id": "check-only",
                    "action": "wait",
                    "reason": "No execution requested.",
                    "contradictions": [],
                    "evidence_fresh": False,
                },
                {"last": {"inputTokens": 49000}},
                {},
            )

        def models(self):
            return [{"id": m} for m in (config.research_model, config.light_model)]

    monkeypatch.setattr(agent, "CodexRPC", RPC)
    for role, context in (
        ("research", {}),
        ("research", {"turns": 2}),
        ("research", {"turns": 1, "last_input_tokens": 49000}),
        ("decision", {"turns": 1}),
    ):
        key = f"thread:{day}:{role}"
        s.set(key, "existing-context")
        s.set("context-policy:" + key, context)
        agent.run_task(config, role, "Evidence only", Decision, config.research_model, "low", day)
    assert seen == ["existing-context", None, None, None]
    assert s.get(f"context-policy:thread:{day}:decision")["turns"] == 1
    s.close()
