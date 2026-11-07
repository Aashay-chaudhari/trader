import copy
import json
from datetime import datetime, timedelta

import pytest
import httpx

from agent_trader.runtime.broker import Broker
from agent_trader.runtime.config import ET
from agent_trader.runtime.daily_inputs import (
    VERSION,
    acquisition_interval,
    build_daily_inputs,
    snapshot_projection,
    validate_daily_inputs,
)
from agent_trader.runtime.features import minute_features
from agent_trader.runtime.observation_audit import content_hash


def data(day="2026-11-09"):
    now = datetime.fromisoformat(day + "T08:45").replace(tzinfo=ET)
    holidays = {"2026-11-26"}
    dates = [now.date() + timedelta(days=i) for i in range(-80, 46)]
    sessions = [
        {"date": d.isoformat(), "open": "09:30", "close": "16:00"}
        for d in dates
        if d.weekday() < 5 and d.isoformat() not in holidays
    ]
    prior = [s["date"] for s in sessions if s["date"] < day][-22:]
    bars = [
        {
            "t": datetime.fromisoformat(d).replace(tzinfo=ET).isoformat(),
            "o": 100 + i,
            "h": 102 + i,
            "l": 99 + i,
            "c": 100 + i,
            "v": 1000 + i,
        }
        for i, d in enumerate(prior)
    ]
    calendar = {
        "sessions": sessions,
        "sha256": content_hash(sessions),
        "observed_at": now.isoformat(),
        "requested_start": dates[0].isoformat(),
        "requested_end": dates[-1].isoformat(),
    }
    return now, {"AAPL": bars, "SPY": copy.deepcopy(bars)}, calendar


def build(store, bars, calendar, now):
    indicators, validation = build_daily_inputs(
        store,
        bars,
        calendar,
        as_of=now.date().isoformat(),
        observed_at=now.isoformat(),
        received_at=(now + timedelta(seconds=1)).isoformat(),
        symbols=["AAPL", "SPY"],
        source_metadata={"feed": "iex", "adjustment": "all", "timeframe": "1Day"},
    )
    return {
        "observed_at": now.isoformat(),
        "daily_indicators": indicators,
        "daily_input_validation": validation,
    }


def test_missing_intermediate_close_uses_exact_return_endpoints_and_holds_only_dependent_fields(
    store,
):
    now, bars, calendar = data()
    bars["AAPL"] = [r for r in bars["AAPL"] if r["t"][:10] != "2026-11-05"]
    packet = build(store, bars, calendar, now)
    daily = packet["daily_indicators"]["AAPL"]
    assert daily["return_3d"] == 121 / 118 - 1
    assert daily["return_5d"] == 121 / 116 - 1
    assert daily["return_1d"] is None
    assert daily["sma20"] is None
    assert daily["preceding_20_close_high"] is None
    assert packet["daily_indicators"]["SPY"]["return_1d"] == 121 / 120 - 1
    assert validate_daily_inputs(store, packet, "AAPL", ["return_3d"], "2026-11-06") == {
        "return_3d": 121 / 118 - 1
    }
    with pytest.raises(ValueError, match="unavailable"):
        validate_daily_inputs(store, packet, "AAPL", ["return_1d"], "2026-11-06")


def test_collector_and_prompt_use_calendar_receipt_without_relabeling_snapshot_dates(
    store, monkeypatch
):
    from agent_trader.runtime import research

    now, bars, calendar = data()
    bars["AAPL"] = [r for r in bars["AAPL"] if r["t"][:10] != "2026-11-05"]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz else now.replace(tzinfo=None)

    class Data:
        def snapshots(self, symbols):
            return {
                "SPY": {
                    "latestQuote": None,
                    "dailyBar": {"t": "2026-11-06T05:00:00Z", "c": 121},
                    "prevDailyBar": {"t": "2026-11-05T05:00:00Z", "c": 120},
                }
            }

        def bars(self, symbols):
            return bars

        def calendar_range(self, start, end):
            return calendar["sessions"]

        def calendar(self, day):
            return [s for s in calendar["sessions"] if s["date"] == day]

        def option_chain(self, symbol):
            return {"snapshots": {}}

    monkeypatch.setattr(research, "datetime", Clock)
    monkeypatch.setattr(research, "utc_now", lambda: now.isoformat())
    monkeypatch.setattr(
        "agent_trader.runtime.store.utc_now", lambda: (now + timedelta(seconds=2)).isoformat()
    )
    monkeypatch.setattr("agent_trader.runtime.cohorts.freeze_signals", lambda *a, **k: None)
    monkeypatch.setattr(
        "agent_trader.runtime.calendars.official_calendar",
        lambda *a: {"sources": [], "unknowns": [], "events": []},
    )
    monkeypatch.setattr(
        "httpx.get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline fixture"))
    )
    packet = research.market_packet(Data(), store)
    assert packet["daily_indicators"]["AAPL"]["return_3d"] == 121 / 118 - 1
    assert packet["daily_indicators"]["AAPL"]["return_1d"] is None
    assert packet["observed_at"] == packet["acquisition_interval"]["started_at"] == now.isoformat()
    assert packet["completed_at"] == packet["acquisition_interval"]["completed_at"]
    prompt = research.research_prompt(now.date().isoformat(), packet, store)
    assert '"current_session_bar_close":null' in prompt
    assert '"prior_close":121.0' in prompt
    assert len(prompt) < 28000
    archived = store.rows("SELECT payload,at FROM memory WHERE layer='research_input'")[0]
    assert json.loads(archived["payload"])["packet"] == packet
    validate_daily_inputs(
        store, packet, "AAPL", ["return_3d"], "2026-11-06", available_by=archived["at"]
    )


@pytest.mark.parametrize(
    "day,previous",
    [("2026-11-09", "2026-11-06"), ("2026-11-27", "2026-11-25"), ("2026-11-28", "2026-11-27")],
)
def test_holidays_weekends_and_dst_follow_broker_session_dates(store, day, previous):
    now, bars, calendar = data(day)
    packet = build(store, bars, calendar, now)
    assert packet["daily_input_validation"]["expected_previous_session"] == previous
    assert packet["daily_input_validation"]["state"] == "ready"
    assert packet["daily_indicators"]["AAPL"]["sma20"] == sum(range(102, 122)) / 20


def test_latest_stale_bar_cannot_relabel_an_older_return_as_current(store):
    now, bars, calendar = data()
    bars["AAPL"].pop()
    packet = build(store, bars, calendar, now)
    assert packet["daily_indicators"]["AAPL"]["last_daily_close"] is None
    assert packet["daily_indicators"]["AAPL"]["return_3d"] is None
    # The preceding-high does not require the most recent close.
    assert packet["daily_indicators"]["AAPL"]["preceding_20_close_high"] == 120


@pytest.mark.parametrize("kind", ["missing", "duplicate", "hash", "future", "bounds"])
def test_unknown_calendar_never_uses_price_dates_as_calendar(store, kind):
    now, bars, calendar = data()
    if kind == "missing":
        calendar = None
    elif kind == "duplicate":
        calendar["sessions"].append(calendar["sessions"][-1])
        calendar["sha256"] = content_hash(calendar["sessions"])
    elif kind == "hash":
        calendar["sha256"] = "changed"
    elif kind == "future":
        calendar["observed_at"] = (now + timedelta(hours=1)).isoformat()
    else:
        calendar["requested_end"] = "2026-11-01"
    packet = build(store, bars, calendar, now)
    assert packet["daily_indicators"] == {}
    assert packet["daily_input_validation"]["state"] == "unavailable"
    assert packet["daily_input_validation"]["expected_previous_session"] is None


@pytest.mark.parametrize("volume", [None, -1, float("nan"), float("inf"), True])
def test_volume_missingness_is_separate_from_price_horizons(store, volume):
    now, bars, calendar = data()
    bars["AAPL"][-1]["v"] = volume
    packet = build(store, bars, calendar, now)
    daily = packet["daily_indicators"]["AAPL"]
    assert daily["average_daily_volume_20_iex_only"] is None
    assert daily["return_1d"] == 121 / 120 - 1
    json.dumps(packet, allow_nan=False)


@pytest.mark.parametrize("kind", ["naive", "off_grid", "conflict"])
def test_ambiguous_daily_record_is_unknown_not_last_writer_wins(store, kind):
    now, bars, calendar = data()
    if kind == "naive":
        bars["AAPL"][-1]["t"] = "2026-11-06T00:00:00"
    elif kind == "off_grid":
        bars["AAPL"][-1]["t"] = "2026-11-06T09:30:00-05:00"
    else:
        bars["AAPL"].append({**bars["AAPL"][-1], "c": 122})
    packet = build(store, bars, calendar, now)
    assert packet["daily_indicators"]["AAPL"]["last_daily_close"] is None
    assert packet["daily_indicators"]["SPY"]["last_daily_close"] == 121


def test_receipt_identity_time_and_calculated_value_are_enforced(store):
    now, bars, calendar = data()
    packet = build(store, bars, calendar, now)
    reference = packet["daily_input_validation"]["receipt_reference"]
    saved = store.get(reference)
    assert build(store, bars, calendar, now) == packet
    assert store.get(reference) == saved
    with pytest.raises(ValueError, match="unavailable when"):
        validate_daily_inputs(store, packet, "AAPL", ["return_1d"], "2026-11-06", available_by=now)
    validate_daily_inputs(
        store, packet, "AAPL", ["return_1d"], "2026-11-06", available_by=now + timedelta(seconds=2)
    )
    changed = copy.deepcopy(packet)
    changed["daily_indicators"]["AAPL"]["return_1d"] = 0
    with pytest.raises(ValueError, match="differs"):
        validate_daily_inputs(store, changed, "AAPL", ["return_1d"], "2026-11-06")
    store.set(reference, {**saved, "received_at": now.isoformat()})
    with pytest.raises(ValueError, match="lineage"):
        validate_daily_inputs(store, packet, "AAPL", ["return_1d"], "2026-11-06")


@pytest.mark.parametrize("fault", ["raw_adjustment", "late_bar_receipt"])
def test_feature_basis_and_provider_acquisition_interval_cannot_be_mislabeled(store, fault):
    now, bars, calendar = data()
    metadata = {"feed": "iex", "adjustment": "all", "timeframe": "1Day"}
    if fault == "raw_adjustment":
        metadata["adjustment"] = "raw"
    else:
        metadata.update(
            bars_requested_at=now.isoformat(),
            bars_received_at=(now + timedelta(seconds=3)).isoformat(),
        )
    with pytest.raises(ValueError):
        build_daily_inputs(
            store,
            bars,
            calendar,
            as_of=now.date().isoformat(),
            observed_at=now.isoformat(),
            received_at=(now + timedelta(seconds=1)).isoformat(),
            source_metadata=metadata,
            symbols=["AAPL"],
        )
    assert store.rows("SELECT key FROM kv WHERE key LIKE 'daily-inputs:%'") == []


@pytest.mark.parametrize(
    "fault,category",
    [
        ("transport", "provider_transport_error"),
        ("malformed", "invalid_daily_intake"),
    ],
)
def test_failed_daily_intake_has_current_status_without_invented_receipt_or_missing_counts(
    store,
    monkeypatch,
    fault,
    category,
):
    from agent_trader.runtime import research

    prior = {"day": "2026-11-06", "packet": {"observed_at": "2026-11-06T13:15:00Z"}}
    store.memory_put("prior-unversioned-input", "research_input", prior)
    transport = Broker.__new__(Broker)

    def request(*args, **kwargs):
        if fault == "transport":
            raise httpx.ConnectTimeout("private provider detail must not become a category")
        return {"bars": None, "next_page_token": None}

    transport.request = request

    class Data:
        def snapshots(self, symbols):
            return {}

        def bars(self, symbols):
            return transport.bar_pages({"symbols": ",".join(symbols)})

        def calendar(self, day):
            return []

        def option_chain(self, symbol):
            return {"snapshots": {}}

    monkeypatch.setattr(
        "agent_trader.runtime.calendars.official_calendar",
        lambda *a: {"sources": [], "unknowns": [], "events": []},
    )
    monkeypatch.setattr(
        "httpx.get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline fixture"))
    )
    packet = research.market_packet(Data(), store)
    status = packet["daily_input_validation"]
    assert status["version"] == VERSION and status["state"] == "unavailable"
    assert status["collection_error"] == category
    assert status["expected_previous_session"] is None
    assert not {"receipt_reference", "sha256", "field_missing_counts"} & status.keys()
    assert packet["daily_indicators"] == {}
    assert store.rows("SELECT key FROM kv WHERE key LIKE 'daily-inputs:%'") == []
    assert "private provider detail" not in json.dumps(packet)
    assert (
        json.loads(
            store.rows("SELECT payload FROM memory WHERE id='prior-unversioned-input'")[0][
                "payload"
            ]
        )
        == prior
    )


def test_snapshot_projection_handles_preopen_null_and_unknown_prior_date():
    snapshot = {
        "dailyBar": {"t": "2026-11-05T05:00:00Z", "c": 100},
        "prevDailyBar": {"t": "2026-11-04T05:00:00Z", "c": 90},
    }
    result = snapshot_projection(snapshot, as_of="2026-11-06", previous_session="2026-11-05")
    assert result["current_session_bar_close"] is None
    assert result["prior_close"] == 100 and result["prior_close_at"] == snapshot["dailyBar"]["t"]
    assert (
        snapshot_projection(snapshot, as_of="2026-11-06", previous_session=None)["prior_close"]
        is None
    )
    snapshot["dailyBar"] = None
    assert (
        snapshot_projection(snapshot, as_of="2026-11-06", previous_session="2026-11-05")[
            "prior_close"
        ]
        is None
    )


def test_snapshot_conflicting_same_date_prices_remain_unknown():
    result = snapshot_projection(
        {
            "latestQuote": [],
            "latestTrade": None,
            "dailyBar": {"t": "2026-11-06T05:00:00Z", "c": 100},
            "prevDailyBar": {"t": "2026-11-06T05:00:00Z", "c": 101},
        },
        as_of="2026-11-09",
        previous_session="2026-11-06",
    )
    assert result["prior_close"] is None and result["quote"] == {}


@pytest.mark.parametrize(
    "bad_page",
    [
        {"bars": None, "next_page_token": None},
        {"bars": {"UNREQUESTED": []}, "next_page_token": None},
        {"bars": {"AAPL": []}, "next_page_token": 0},
        {"bars": {"AAPL": []}, "next_page_token": ""},
    ],
)
def test_malformed_page_cannot_certify_completeness(bad_page):
    broker = Broker.__new__(Broker)
    broker.request = lambda *a, **k: bad_page
    with pytest.raises(ValueError):
        broker.bar_pages({"symbols": "AAPL"})
    assert broker.last_bar_receipt is None


def test_absent_final_token_uses_documented_provider_sdk_completion_semantics():
    broker = Broker.__new__(Broker)
    broker.request = lambda *a, **k: {"bars": {"AAPL": []}}
    assert broker.bar_pages({"symbols": "AAPL"}) == {}
    assert broker.last_bar_receipt["completion_basis"] == "token_absent_provider_sdk_semantics"


def test_identical_pagination_duplicates_dedupe_and_conflicts_reject():
    row = {"t": "2026-11-06T05:00:00Z", "c": 100}
    for conflicting in (False, True):
        pages = iter(
            [
                {"bars": {"AAPL": [row]}, "next_page_token": "p2"},
                {
                    "bars": {"AAPL": [{**row, "c": 101 if conflicting else 100}]},
                    "next_page_token": None,
                },
            ]
        )
        broker = Broker.__new__(Broker)
        broker.request = lambda *a, **k: next(pages)
        if conflicting:
            with pytest.raises(ValueError, match="Conflicting duplicate"):
                broker.bar_pages({"symbols": "AAPL"})
            assert broker.last_bar_receipt is None
        else:
            assert broker.bar_pages({"symbols": "AAPL"}) == {"AAPL": [row]}
            assert broker.last_bar_receipt["row_count"] == 1
            assert len(broker.last_bar_receipt["pages"]) == 2


def test_minute_vwap_avoids_product_overflow_and_conflicting_minute_is_missing():
    opened = datetime(2026, 11, 6, 9, 30, tzinfo=ET)
    bar = {
        "t": opened.isoformat(),
        "o": 1e200,
        "h": 1e200,
        "l": 1e200,
        "c": 1e200,
        "v": 1e200,
        "vw": 1e200,
    }
    result = minute_features(
        {"AAPL": [bar]}, opened + timedelta(minutes=1), opened, opened.replace(hour=16)
    )
    assert result["AAPL"]["bar_vwap_iex"] == 1e200
    json.dumps(result, allow_nan=False)
    normal = {
        "t": (opened + timedelta(minutes=1)).isoformat(),
        "o": 100,
        "h": 102,
        "l": 99,
        "c": 100,
        "v": 100,
        "vw": 100,
    }
    result = minute_features(
        {"AAPL": [bar, {**bar, "v": 1}, normal]},
        opened + timedelta(minutes=2),
        opened,
        opened.replace(hour=16),
    )
    assert result["AAPL"]["missing_minute_intervals"] == 1
    assert result["AAPL"]["conflicting_minute_intervals"] == 1


@pytest.mark.parametrize(
    "start,end,date_cross,open_cross",
    [
        ("2026-11-08T23:59:58-05:00", "2026-11-09T00:00:02-05:00", True, False),
        ("2026-11-09T09:29:58-05:00", "2026-11-09T09:30:02-05:00", False, True),
    ],
)
def test_acquisition_boundaries_preserve_start_and_actual_availability(
    start, end, date_cross, open_cross
):
    result = acquisition_interval(
        start, end, [{"date": "2026-11-09", "open": "09:30", "close": "16:00"}]
    )
    assert result["started_at"] == start and result["completed_at"] == end
    assert result["crossed_et_date"] is date_cross
    assert result["crossed_regular_open"] is open_cross
