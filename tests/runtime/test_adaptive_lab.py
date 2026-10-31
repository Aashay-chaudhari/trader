"""Adaptive studies test temporal provenance and research-only accounting."""

import json
from datetime import date, datetime, timedelta

import pytest
from pydantic import ValidationError

from agent_trader.runtime.adaptive_lab import AdaptiveContract, AdaptiveLab
from agent_trader.runtime.config import ET
from agent_trader.runtime.store import dumps


def at(day="2026-11-02", clock="09:45"):
    return datetime.fromisoformat(day + "T" + clock).replace(tzinfo=ET)


def calendar():
    # Deterministic mock broker calendar includes the DST transition and a holiday.
    start = date(2026, 10, 29)
    return [
        {"date": (start + timedelta(days=i)).isoformat(), "open": "09:30", "close": "16:00"}
        for i in range(80)
        if (start + timedelta(days=i)).weekday() < 5
        and (start + timedelta(days=i)).isoformat() != "2026-11-26"
    ]


def contract(**changes):
    return {
        "id": "adaptive-test-v1",
        "hypothesis_id": "hypothesis-live-observation",
        "branch": "intraday",
        "symbols": ["AAPL"],
        "predicates": [{"field": "return_3d", "operator": "lte", "value": -0.03}],
        "hypothesis": "A preregistered large decline may subsequently reverse.",
        "falsification": "Reject the positive return claim if stressed mean is nonpositive.",
        "minimum_sessions": 30,
        "minimum_signals": 30,
        **changes,
    }


def quote(now, bid=100, ask=100.01):
    return {"bp": bid, "ap": ask, "t": now.isoformat()}


def packet(store, now, **changes):
    p = {
        "observed_at": (now - timedelta(minutes=30)).isoformat(),
        "daily_indicators": {
            "AAPL": {
                "asof": "2026-10-30",
                "return_3d": -0.04,
                "last_daily_close": 99,
                "sma20": 100,
            },
            "SPY": {"asof": "2026-10-30", "last_daily_close": 100},
        },
        **changes,
    }
    archive(store, p, now)
    return p


def archive(store, p, now):
    store.db.execute(
        "INSERT OR REPLACE INTO memory VALUES(?,?,?,?,?)",
        (
            "research-input:" + p["observed_at"],
            "research_input",
            None,
            dumps({"packet": p}),
            (now - timedelta(minutes=1)).isoformat(),
        ),
    )


def run(lab, now, p, quotes=None, sessions=None):
    lab.observe(
        quotes or {"AAPL": quote(now)},
        p,
        now,
        at(now.date().isoformat(), "09:30"),
        at(now.date().isoformat(), "16:00"),
        sessions or calendar(),
    )


def rows(store):
    return [
        dict(r, payload=json.loads(r["payload"]))
        for r in store.rows("SELECT * FROM adaptive_observations ORDER BY day")
    ]


def setup(store, **changes):
    lab = AdaptiveLab(store)
    lab.register(contract(**changes), at("2026-10-31", "12:00"))
    now = at()
    return lab, now, packet(store, now)


def test_future_only_immutable_and_semantic_dedup(store):
    lab = AdaptiveLab(store)
    spec = contract()
    assert lab.register(spec, at("2026-11-02", "08:00"))
    assert not lab.register(spec, at("2026-11-02", "08:01"))
    with pytest.raises(ValueError, match="immutable"):
        lab.register(contract(hypothesis="Changed after seeing observations would revise history."))
    assert not lab.register(contract(id="renamed-same-rule"))
    run(lab, at(), packet(store, at()))
    obs = rows(store)
    assert len(obs) == 30
    assert obs[0]["day"] == "2026-11-03"
    assert {r["state"] for r in obs} == {"pending"}
    assert not store.rows("SELECT * FROM plans")
    assert not store.rows("SELECT * FROM orders")
    assert not store.rows("SELECT * FROM cohort_expected")


def test_entry_capture_closed_returns_and_idempotency(store):
    lab, now, p = setup(store)
    run(lab, now, p)
    entered = rows(store)[0]
    assert entered["state"] == "open"
    assert entered["payload"]["signal"] is True
    assert entered["payload"]["features"] == {"return_3d": -0.04}
    assert entered["payload"]["input_sha256"]
    run(lab, now + timedelta(minutes=1), p)
    assert rows(store)[0]["payload"]["entered_at"] == now.isoformat()
    lab.mark({"AAPL": quote(at(clock="15:47"), 101, 101.01)}, at(clock="15:47"))
    assert rows(store)[0]["state"] == "open"
    lab.mark({"AAPL": quote(at(clock="15:48"), 101, 101.01)}, at(clock="15:48"))
    result = lab.summary()["trials"][0]
    assert result["closed"] == result["closed_signals"] == result["closed_sessions"] == 1
    assert result["cumulative"]["signal_net"] == pytest.approx(101 / 100.01 - 1 - 0.002)
    assert result["cumulative"]["signal_stressed"] == pytest.approx(101 / 100.01 - 1 - 0.005)
    assert result["minimum_evidence_counts_met"] is False
    assert result["promotion_eligible"] is False
    assert len(rows(store)) == 30


@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "stale",
        "wrong_previous",
        "future",
        "unarchived",
        "changed_after_archive",
        "future_archive",
        "nonfinite",
    ],
)
def test_unknown_inputs_are_never_false_signals(store, case):
    lab, now, p = setup(store)
    if case == "missing":
        del p["daily_indicators"]["AAPL"]["return_3d"]
    elif case == "stale":
        p["observed_at"] = (now - timedelta(hours=3)).isoformat()
    elif case == "wrong_previous":
        p["daily_indicators"]["AAPL"]["asof"] = "2026-10-29"
    elif case == "future":
        p["observed_at"] = (now + timedelta(minutes=1)).isoformat()
    elif case == "unarchived":
        store.db.execute("DELETE FROM memory")
    elif case == "changed_after_archive":
        p["daily_indicators"]["AAPL"]["return_3d"] = 0.04
    elif case == "future_archive":
        store.db.execute("UPDATE memory SET at=?", ((now + timedelta(minutes=1)).isoformat(),))
    elif case == "nonfinite":
        p["daily_indicators"]["AAPL"]["return_3d"] = "NaN"
    if case not in ("unarchived", "changed_after_archive", "future_archive"):
        archive(store, p, now)
    run(lab, now, p)
    first = rows(store)[0]
    assert first["state"] == "pending"
    assert "signal" not in first["payload"]
    lab.expire(at(clock="10:00"))
    first = rows(store)[0]
    assert first["state"] == "not_evaluable"
    assert "signal" not in first["payload"]
    assert lab.summary()["trials"][0]["not_evaluable"] == 1


def test_false_signal_keeps_cash_and_same_symbol_comparator(store):
    lab, now, p = setup(store)
    p["daily_indicators"]["AAPL"]["return_3d"] = 0.04
    archive(store, p, now)
    run(lab, now, p)
    assert rows(store)[0]["payload"]["signal"] is False
    lab.mark({"AAPL": quote(at(clock="15:48"), 99, 99.01)}, at(clock="15:48"))
    result = lab.summary()["trials"][0]
    assert result["closed"] == 1 and result["closed_signals"] == 0
    assert result["cumulative"]["signal_net"] == 0
    assert result["cumulative"]["baseline_net"] < 0


def test_no_backfill_after_missed_entry_or_exit(store):
    lab, now, p = setup(store)
    run(lab, at(clock="10:00"), p)
    assert rows(store)[0]["state"] == "not_evaluable"
    assert "entry_ask" not in rows(store)[0]["payload"]
    lab2 = AdaptiveLab(store)
    lab2.register(
        contract(
            id="other-rule", predicates=[{"field": "return_3d", "operator": "lte", "value": -0.02}]
        ),
        at("2026-10-31", "12:00"),
    )
    run(lab2, now, p)
    lab2.mark({"AAPL": quote(at(clock="16:00"), 105, 105.01)}, at(clock="16:00"))
    second = [r for r in rows(store) if r["contract_id"] == "other-rule"][0]
    assert second["state"] == "not_evaluable"
    assert "signal_net" not in second["payload"]


def test_swing_uses_actual_sessions_dst_and_holiday(store):
    lab, now, p = setup(store, branch="swing")
    run(lab, now, p)
    first = rows(store)[0]["payload"]
    assert first["exit_start"] == at("2026-11-06", "15:48").isoformat()
    assert "-05:00" in first["exit_start"]
    holiday_entry = next(r for r in rows(store) if r["day"] == "2026-11-23")
    assert holiday_entry["payload"]["session_close"] == at("2026-11-30", "16:00").isoformat()
    lab.mark({"AAPL": quote(at("2026-11-05", "15:48"), 102, 102.01)}, at("2026-11-05", "15:48"))
    assert rows(store)[0]["state"] == "open"
    lab.mark({"AAPL": quote(at("2026-11-06", "15:48"), 102, 102.01)}, at("2026-11-06", "15:48"))
    assert rows(store)[0]["state"] == "closed"


def test_relative_gap_requires_synchronous_spy_and_exact_prior_session(store):
    lab, now, p = setup(
        store, predicates=[{"field": "relative_gap_spy", "operator": "gte", "value": 0}]
    )
    run(lab, now, p)
    assert rows(store)[0]["state"] == "pending"
    quotes = {"AAPL": quote(now), "SPY": quote(now, 100, 100.01)}
    run(lab, now, p, quotes)
    assert rows(store)[0]["state"] == "open"
    expected = 100.01 / 99 - 1 - (100.01 / 100 - 1)
    assert rows(store)[0]["payload"]["features"]["relative_gap_spy"] == pytest.approx(expected)


def test_bounds_calendar_requirement_and_trial_retention(store):
    with pytest.raises(ValidationError):
        AdaptiveContract.model_validate(contract(symbols=["NOTREAL"]))
    with pytest.raises(ValidationError):
        AdaptiveContract.model_validate(
            contract(predicates=[{"field": "return_3d", "operator": "gte", "value": float("inf")}])
        )
    lab, now, p = setup(store)
    run(lab, now, p, sessions=calendar()[:5])
    assert rows(store) == []
    run(lab, now, p)
    lab.expire(at("2027-01-01", "16:00"))
    result = lab.summary()["trials"][0]
    assert result["state"] == "completed"
    assert result["preregistered_opportunities"] == result["not_evaluable"] == 30
    assert lab.summary()["trial_count"] == 1
    assert not lab.summary()["automatic_promotion"]
    assert lab.context()["trials"][0]["id"] == contract()["id"]


def test_six_active_per_branch(store):
    lab = AdaptiveLab(store)
    for index in range(7):
        spec = contract(
            id=f"variant-{index}",
            predicates=[{"field": "return_3d", "operator": "lte", "value": -0.03 - index * 0.01}],
        )
        assert lab.register(spec, at("2026-10-31", "12:00")) is (index < 6)
    assert lab.summary()["trial_count"] == 6


def test_complete_inputs_and_stale_quotes_cannot_open(store):
    lab, now, p = setup(store)
    run(lab, now, p, {"AAPL": quote(now - timedelta(minutes=2))})
    assert rows(store)[0]["state"] == "pending"
    run(lab, now, p, {"AAPL": quote(now, 100, 101)})
    assert rows(store)[0]["state"] == "pending"
    run(lab, now, p)
    assert rows(store)[0]["state"] == "open"


def test_protocol_change_cannot_reinterpret_registered_observations(store, monkeypatch):
    import agent_trader.runtime.adaptive_lab as module

    lab, now, p = setup(store)
    run(lab, now, p)
    original = rows(store)[0]["payload"]
    monkeypatch.setitem(module.PROTOCOL, "costs", "An incompatible new cost model")
    lab.mark({"AAPL": quote(at(clock="15:48"), 105, 105.01)}, at(clock="15:48"))
    assert rows(store)[0]["state"] == "open"
    assert rows(store)[0]["payload"] == original
    assert lab.summary()["trials"][0]["protocol_compatible"] is False
    lab.expire(at(clock="16:00"))
    assert rows(store)[0]["state"] == "not_evaluable"


def test_calendar_blocker_and_timezone_required(store):
    lab = AdaptiveLab(store)
    with pytest.raises(ValueError, match="timezone"):
        lab.register(contract(), datetime(2026, 10, 31, 12))
    lab.register(contract(), at("2026-10-31", "12:00"))
    now = at()
    run(lab, now, packet(store, now), sessions=calendar()[:5])
    assert "requires 30" in lab.summary()["trials"][0]["binding_status"]["reason"]


def test_signal_target_is_mathematically_feasible():
    with pytest.raises(ValidationError, match="maximum opportunities"):
        AdaptiveContract.model_validate(contract(minimum_sessions=20))
    assert AdaptiveContract.model_validate(contract(minimum_sessions=20, symbols=["AAPL", "MSFT"]))
    assert AdaptiveContract.model_validate(contract(minimum_sessions=30, minimum_signals=30))
