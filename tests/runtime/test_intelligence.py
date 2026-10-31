import copy
import json
from datetime import timedelta

from agent_trader.runtime.intelligence import (
    capture_observations,
    objective_scorecard,
    observation_context,
    observation_ids_valid,
    record_reconciled_equity,
)


def packet(now):
    return {
        "observed_at": now.isoformat(),
        "universe": ["SPY", "AAPL", "MSFT"],
        "data_feed": "Alpaca free IEX",
        "daily_indicators": {
            "SPY": {"asof": "2026-10-29", "return_1d": -0.01},
            "AAPL": {
                "asof": "2026-10-29",
                "return_1d": 0.02,
                "return_3d": 0.04,
                "last_daily_close": 200,
            },
            "MSFT": {"asof": "2026-10-29", "return_1d": 0.015},
        },
        "macro_daily_delayed": {
            "DGS10": {
                "value": 4.0,
                "observation_date": "2026-10-28",
                "source": "https://fred.stlouisfed.org/series/DGS10",
            }
        },
    }


def test_leads_are_immutable_and_deduplicate_identical_values(store, now):
    p = packet(now)
    first = capture_observations(store, p, now)
    assert len(first) == 2
    assert all(x["kind"] == "daily_relative_move" for x in first)
    later = now + timedelta(hours=1)
    p["observed_at"] = later.isoformat()
    assert capture_observations(store, p, later) == []
    assert observation_context(store)["total_records"] == 2
    assert all(x["observed_at"] == now.isoformat() for x in observation_context(store)["records"])
    assert next(x for x in first if x["subject"] == "AAPL")["values"]["relative_return_1d"] == 0.03


def test_daily_comparison_requires_same_completed_date_and_finite_values(store, now):
    p = packet(now)
    p["daily_indicators"]["AAPL"]["asof"] = "2026-10-28"
    p["daily_indicators"]["MSFT"]["return_1d"] = float("nan")
    assert capture_observations(store, p, now) == []
    p["daily_indicators"]["SPY"]["asof"] = "2026-10-30"
    p["daily_indicators"]["AAPL"]["asof"] = "2026-10-30"
    assert capture_observations(store, p, now) == []


def test_macro_changes_need_actual_prior_capture_and_distinguish_revision(store, now):
    p = packet(now)
    first = capture_observations(store, p, now)
    assert not any(x["kind"].startswith("macro") for x in first)
    later = now + timedelta(hours=1)
    p["observed_at"] = later.isoformat()
    p["macro_daily_delayed"]["DGS10"].update(value=4.1, observation_date="2026-10-29")
    changes = capture_observations(store, p, later)
    assert len(changes) == 1
    change = changes[0]
    assert change["kind"] == "macro_observed_change"
    assert change["values"]["previous_event_asof"] == "2026-10-28"
    assert change["values"]["previous_observed_at"] == now.isoformat()
    p["observed_at"] = (later + timedelta(hours=1)).isoformat()
    p["macro_daily_delayed"]["DGS10"]["value"] = 4.2
    revision = capture_observations(store, p, later + timedelta(hours=1))
    assert revision[0]["kind"] == "macro_revision"
    assert revision[0]["event_asof"] == "2026-10-29"


def test_future_out_of_order_macro_and_naive_capture_do_not_create_changes(store, now):
    p = packet(now)
    capture_observations(store, p, now)
    earlier = now - timedelta(minutes=1)
    p["observed_at"] = earlier.isoformat()
    p["macro_daily_delayed"]["DGS10"].update(value=9, observation_date="2026-10-29")
    assert capture_observations(store, p, now) == []
    assert store.get("observation-macro-baseline:DGS10")["value"] == 4
    p["observed_at"] = (now + timedelta(hours=1)).isoformat()
    assert capture_observations(store, p, now) == []
    assert capture_observations(store, p, now.replace(tzinfo=None)) == []


def test_gap_is_distinct_from_price_lead_and_old_capture_is_not_backdated(store, now):
    p = packet(now)
    p["daily_indicators"] = {}
    p["unknowns"] = ["Daily bars unavailable: TimeoutError"]
    later = now + timedelta(days=1)
    records = capture_observations(store, p, later)
    assert len(records) == 1
    assert records[0]["kind"] == "data_gap"
    assert records[0]["observed_at"] == later.isoformat()
    assert records[0]["input_observed_at"] == now.isoformat()
    assert not observation_ids_valid(store, [records[0]["id"]], before=now)


def test_ids_require_existing_leads_unique_values_and_aware_cutoff(store, now):
    ids = [r["id"] for r in capture_observations(store, packet(now), now)]
    assert observation_ids_valid(store, ids, before=now)
    assert not observation_ids_valid(store, ids, before=now - timedelta(seconds=1))
    assert not observation_ids_valid(store, ids, before=now.replace(tzinfo=None))
    assert not observation_ids_valid(store, [ids[0], ids[0]])
    assert not observation_ids_valid(store, ["observation:invented"])
    assert not observation_ids_valid(store, [])


def test_context_budget_preserves_complete_records_and_correct_omission_count(store, now):
    capture_observations(store, packet(now), now)
    context = observation_context(store, max_chars=1700)
    assert len(json.dumps(context)) <= 1700
    assert len(context["records"]) + context["omitted"] == context["total_records"]
    assert all(r["id"] and r["provenance"] and r["alternatives"] for r in context["records"])


def test_intraday_leads_reject_future_stale_and_incomplete_features(store, now):
    p = packet(now)
    p["daily_indicators"] = {}
    p["universe"] = []
    base = {
        "asof": now.isoformat(),
        "last_completed_close": 101,
        "bar_vwap_iex": 100,
        "opening_5m_complete": True,
        "missing_minute_intervals": 0,
        "observed_minute_bars": 30,
    }
    p["intraday_indicators"] = {
        "AAPL": base,
        "MSFT": {**base, "asof": (now - timedelta(minutes=3)).isoformat()},
        "NVDA": {**base, "asof": (now + timedelta(seconds=1)).isoformat()},
        "QQQ": {**base, "missing_minute_intervals": 1},
    }
    records = capture_observations(store, p, now)
    assert len(records) == 1 and records[0]["subject"] == "AAPL"
    assert records[0]["kind"] == "intraday_vwap_distance"


def test_scorecard_unknown_account_and_no_fake_drawdown(store, now):
    store.set("account", {"equity": "30000"})
    card = objective_scorecard(store, now)
    assert card["portfolio"]["equity"] is None
    assert card["portfolio"]["total_return"] is None
    assert card["portfolio"]["max_drawdown"] is None
    assert not record_reconciled_equity(store, now)
    assert not card["portfolio"]["execution_verified"]


def test_verified_drawdown_and_return_never_import_legacy_equity(store, now):
    for branch in ("intraday", "swing", "options"):
        store.db.execute(
            "INSERT INTO equity(at,day,branch,value) VALUES(?,?,?,?)",
            ((now - timedelta(days=1)).isoformat(), "2026-10-29", branch, 100000),
        )
    store.set("reconciled", True)
    store.set("account", {"equity": "33000"})
    store.set("last_reconciled", now.isoformat())
    assert record_reconciled_equity(store, now)
    assert not record_reconciled_equity(store, now)
    later = now + timedelta(minutes=1)
    store.set("last_reconciled", later.isoformat())
    store.set("account", {"equity": "31350"})
    assert record_reconciled_equity(store, later)
    card = objective_scorecard(store, later)
    assert abs(card["portfolio"]["total_return"] - 0.045) < 1e-9
    assert abs(card["portfolio"]["max_drawdown"] - 0.05) < 1e-9
    assert card["portfolio"]["verified_equity_marks"] == 2
    assert card["portfolio"]["drawdown_observed_since"] == now.isoformat()
    store.set("reconciled", False)
    assert objective_scorecard(store, later)["portfolio"]["total_return"] is None


def test_scorecard_counts_learning_stalls_without_converting_cohorts_to_profit(store, now):
    store.db.execute(
        "INSERT INTO experiments VALUES(?,?,?,?,?)",
        ("test", "intraday", "shadow", "{}", now.isoformat()),
    )
    store.memory_put("lesson", "lesson", {"state": "proposed", "claim": "Test next session"})
    store.memory_put(
        "proposal", "improvement_proposal", {"state": "code_changed_awaiting_observation"}
    )
    store.set(
        "benchmarks",
        {
            "SPY": {"return": 0.02, "at": now.isoformat()},
            "starts": {"SPY": {"at": (now - timedelta(days=1)).isoformat()}},
        },
    )
    before = store.rows("SELECT count(*) n FROM memory")[0]["n"]
    card = objective_scorecard(store, now)
    assert card["research_funnel"]["active_shadow_experiments"] == 1
    assert card["research_funnel"]["experiments_with_samples"] == 0
    assert card["development"]["stage_counts"] == {"code_changed_awaiting_observation": 1}
    assert card["learning"]["proposed_lessons"] == 1
    assert {x["id"] for x in card["diagnostics"]} >= {
        "experiment_sample_starvation",
        "untested_lessons",
    }
    assert card["portfolio"]["market_references"][0]["return"] == 0.02
    assert card["portfolio"]["total_return"] is None
    assert store.rows("SELECT count(*) n FROM memory")[0]["n"] == before


def test_macro_fingerprint_changes_only_for_real_observed_change(store, now):
    p = packet(now)
    capture_observations(store, p, now)
    second = copy.deepcopy(p)
    second["observed_at"] = (now + timedelta(minutes=1)).isoformat()
    second["macro_daily_delayed"]["DGS10"]["value"] = 4.05
    first_change = capture_observations(store, second, now + timedelta(minutes=1))
    assert len(first_change) == 1
    assert capture_observations(store, second, now + timedelta(minutes=2)) == []


def test_live_quote_leads_preserve_first_observation_per_bucket_and_actual_prices(store, now):
    p = packet(now)
    p["daily_indicators"]["SPY"]["last_daily_close"] = 100
    p["market"] = {
        "SPY": {"latestQuote": {"bp": 99.99, "ap": 100.01, "t": now.isoformat()}},
        "AAPL": {"latestQuote": {"bp": 203.99, "ap": 204.01, "t": now.isoformat()}},
    }
    first = capture_observations(store, p, now)
    current = [x for x in first if x["kind"] == "intraday_relative_move"]
    assert len(current) == 1
    assert abs(current[0]["values"]["relative_change"] - 0.02) < 1e-9
    assert current[0]["values"]["spy"]["quote_at"] == now.isoformat()
    assert current[0]["provenance"]["input_ref"] is None
    later = now + timedelta(minutes=1)
    p["observed_at"] = later.isoformat()
    for item in p["market"].values():
        item["latestQuote"]["t"] = later.isoformat()
    p["market"]["AAPL"]["latestQuote"].update(bp=204.99, ap=205.01)
    assert capture_observations(store, p, later) == []
    new_bucket = now + timedelta(minutes=15)
    p["observed_at"] = new_bucket.isoformat()
    for item in p["market"].values():
        item["latestQuote"]["t"] = new_bucket.isoformat()
    assert len(capture_observations(store, p, new_bucket)) == 1


def test_importing_old_packet_never_mislabels_quotes_or_minutes_as_live(store, now):
    p = packet(now)
    p["daily_indicators"]["SPY"]["last_daily_close"] = 100
    p["market"] = {
        "SPY": {"latestQuote": {"bp": 99.99, "ap": 100.01, "t": now.isoformat()}},
        "AAPL": {"latestQuote": {"bp": 203.99, "ap": 204.01, "t": now.isoformat()}},
    }
    p["intraday_indicators"] = {
        "AAPL": {
            "asof": now.isoformat(),
            "last_completed_close": 201,
            "bar_vwap_iex": 200,
            "opening_5m_complete": True,
            "missing_minute_intervals": 0,
            "observed_minute_bars": 30,
        },
    }
    result = capture_observations(store, p, now + timedelta(days=1))
    assert result
    assert all(not x["kind"].startswith("intraday") for x in result)


def test_imported_macro_baseline_retains_actual_capture_time(store, now):
    p = packet(now)
    capture_time = now + timedelta(days=1)
    capture_observations(store, p, capture_time)
    p["observed_at"] = (now + timedelta(hours=1)).isoformat()
    p["macro_daily_delayed"]["DGS10"].update(value=4.1, observation_date="2026-10-29")
    changes = capture_observations(store, p, capture_time + timedelta(minutes=1))
    assert changes[0]["kind"] == "macro_observed_change"
    assert changes[0]["values"]["previous_observed_at"] == capture_time.isoformat()
    assert changes[0]["values"]["previous_input_observed_at"] == now.isoformat()
