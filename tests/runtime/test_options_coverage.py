import copy
import json
from datetime import datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from agent_trader.runtime import options_coverage as probe
from agent_trader.runtime.broker import Broker
from agent_trader.runtime.config import ET
from agent_trader.runtime.observation_audit import content_hash


def at(day="2026-11-09", clock="10:00:00"):
    return datetime.fromisoformat(day + "T" + clock).replace(tzinfo=ET)


def symbol(underlying, kind="call", strike=100, expiry="2026-11-16"):
    return (
        underlying
        + expiry[2:].replace("-", "")
        + ("C" if kind == "call" else "P")
        + f"{int(Decimal(str(strike)) * 1000):08d}"
    )


def contract(underlying, kind, strike=None, expiry="2026-11-16"):
    strike = strike if strike is not None else (100 if underlying == "SPY" else 200)
    return {
        "symbol": symbol(underlying, kind, strike, expiry),
        "id": "PRIVATE-CONTRACT-ID",
        "underlying_symbol": underlying,
        "root_symbol": underlying,
        "type": kind,
        "expiration_date": expiry,
        "strike_price": str(strike),
        "status": "active",
        "tradable": True,
        "size": "100",
        "multiplier": "100",
        "deliverables": [
            {
                "type": "equity",
                "symbol": underlying,
                "amount": "100",
                "allocation_percentage": "100",
                "delayed_settlement": False,
                "asset_id": "PRIVATE-ASSET-ID",
            }
        ],
    }


def registration(store, registered_at=None):
    sessions = [
        {"date": day, "open": "09:30", "close": "16:00"}
        for day in ("2026-11-06", "2026-11-09", "2026-11-10", "2026-11-11")
    ]
    calendar = {
        "sessions": sessions,
        "sha256": content_hash(sessions),
        "requested_start": "2026-11-06",
        "requested_end": "2026-11-11",
        "observed_at": at("2026-11-06", "08:00").isoformat(),
        "source": "Alpaca broker calendar",
    }
    review = {
        "approved": True,
        "reviewer": "independent-source-review",
        "protocol_sha256": probe.PROTOCOL_SHA256,
        "validation": "Read-only compatibility and isolated recovery tests.",
    }
    return probe.register(
        store,
        calendar,
        registered_at=(registered_at or at("2026-11-07", "12:00")).isoformat(),
        review=review,
    )


def confirm(store, now):
    day = now.date().isoformat()
    store.set("market_open", True)
    store.set("calendar:" + day, [{"date": day, "open": "09:30", "close": "16:00"}])
    store.db.execute(
        "INSERT OR REPLACE INTO session_health VALUES(?,?,?,?,?)", (day, 6, now.isoformat(), 1, 1)
    )


class Clock:
    def __init__(self, now=None):
        self.now = now or at()

    def __call__(self):
        return self.now


class DataBroker:
    def __init__(self, clock):
        self.clock, self.calls = clock, []
        self.two_pages = True
        self.contracts = {
            underlying: [contract(underlying, kind) for kind in ("call", "put")]
            for underlying in probe.UNDERLYINGS
        }
        self.option_age = 0
        self.iv = 0.25
        self.snapshot_delay = 0
        self.fail_after_quote = False
        self.quote_calls = 0

    def quotes(self, symbols):
        self.calls.append(("underlying", tuple(symbols)))
        self.quote_calls += 1
        if self.fail_after_quote and self.quote_calls % 2 == 0:
            raise httpx.ReadTimeout("fixture outage")
        return {
            underlying: {"bp": price - 0.01, "ap": price + 0.01, "t": self.clock().isoformat()}
            for underlying, price in (("SPY", 100), ("QQQ", 200))
        }

    def option_contracts_page(self, underlying, first, last, low, high, *, page_token=None):
        self.calls.append(("metadata", underlying, page_token))
        assert (first, last) == ("2026-11-16", "2026-11-23")
        rows = self.contracts[underlying]
        if self.two_pages and not page_token:
            return {"option_contracts": copy.deepcopy(rows[:1]), "next_page_token": "page2"}
        return {
            "option_contracts": copy.deepcopy(rows[1:] if self.two_pages else rows),
            "next_page_token": None,
        }

    def option_snapshots(self, symbols):
        self.calls.append(("selected", tuple(symbols)))
        stamp = (self.clock() - timedelta(seconds=self.option_age)).isoformat()
        result = {
            "snapshots": {
                s: {
                    "latestQuote": {"bp": 2, "ap": 2.1, "t": stamp},
                    "impliedVolatility": self.iv,
                    "greeks": {key: 0 for key in probe.GREEKS},
                }
                for s in symbols
            },
            "next_page_token": None,
        }
        self.clock.now += timedelta(seconds=self.snapshot_delay)
        return result

    def option_chain(self, underlying):
        self.calls.append(("legacy", underlying))
        return {
            "snapshots": {
                symbol(underlying, strike=100 + i, expiry="2026-11-09"): {
                    "latestQuote": {"bp": 1, "ap": 1.1, "t": self.clock().isoformat()},
                    "impliedVolatility": 0,
                    "greeks": {},
                }
                for i in range(30)
            },
            "next_page_token": "legacy-incomplete-by-design",
        }


def run(store, broker, clock, slot=1):
    confirm(store, clock())
    return probe.run_capture(store, broker, slot, clock=clock)


def test_registration_freezes_historical_baseline_without_rewriting_packet(store):
    packet = {
        "observed_at": at("2026-11-06", "13:00").isoformat(),
        "contracts": [
            {
                "symbol": symbol("SPY", expiry="2026-11-06"),
                "quote": {"bp": 1, "ap": 1.1, "t": at("2026-11-06", "13:00").isoformat()},
                "implied_volatility": 0.3,
                "greeks": {"delta": 0},
            },
            {
                "symbol": symbol("QQQ", "put", expiry="2026-11-06"),
                "implied_volatility": 0,
                "greeks": {},
            },
        ],
    }
    store.set("options_research", packet)
    reg = registration(store)
    baseline = reg["baseline"]
    assert baseline["contracts"] == baseline["same_day_expiry_count"] == 2
    assert baseline["call_count"] == baseline["put_count"] == 1
    assert baseline["iv_categories"] == {"positive": 1, "zero": 1}
    assert baseline["finite_greek_fields"]["delta"] == 1
    assert baseline["contracts_with_any_finite_greek"] == 1
    assert store.get("options_research") == packet
    assert reg["session_day"] == "2026-11-09"
    assert registration(store) == reg
    changed = copy.deepcopy(reg["calendar_evidence"])
    changed["requested_end"] = "2026-11-12"
    with pytest.raises(ValueError, match="immutable"):
        probe.register(store, changed, registered_at=reg["registered_at"], review=reg["review"])


def test_two_captures_have_eight_denominator_twelve_reserved_requests_and_same_pairs(store):
    reg = registration(store)
    clock = Clock()
    broker = DataBroker(clock)
    first = run(store, broker, clock)
    assert first["request_budget"]["reserved"] == 9
    assert first["captures"][0]["received_snapshots"] == 4
    assert all(row["positive_iv_with_quote_checks"] for row in first["captures"][0]["observations"])
    assert (
        first["captures"][0]["observations"][0]["spread_fraction"] > 0.005
    )  # no equity spread gate
    assert len(first["captures"][0]["legacy_comparator"]) == 2
    clock.now = at(clock="10:15")
    broker.contracts = {}  # The second capture cannot fetch/reselect metadata.
    second = run(store, broker, clock, 2)
    assert second["expected_observations"] == 8
    assert second["request_budget"]["reserved"] == len(broker.calls) == 12
    assert second["selection"] == first["selection"]
    assert sum(c["received_snapshots"] for c in second["captures"]) == 8
    assert probe.run_capture(store, broker, 2, clock=clock) == second
    assert len(broker.calls) == 12
    assert "PRIVATE-" not in json.dumps(second)
    assert not store.rows("SELECT * FROM orders") and not store.rows("SELECT * FROM plans")
    assert not second["execution_eligible"] and not second["promotion_eligible"]
    assert all(
        row["iv_asof"] == "unknown_not_provided_by_provider"
        for c in second["captures"]
        for row in c["observations"]
    )
    requests = probe._requests(store, reg)
    assert all(r["reserved_at"] <= r["requested_at"] <= r["received_at"] for r in requests)


def test_metadata_selection_is_iv_independent_and_lower_strike_breaks_tie(store):
    registration(store)
    clock, broker = Clock(), None
    broker = DataBroker(clock)
    broker.two_pages = False
    broker.iv = 0
    for underlying, price in (("SPY", 100), ("QQQ", 200)):
        broker.contracts[underlying] = [
            contract(underlying, kind, price + offset)
            for offset in (0.5, -0.5)
            for kind in ("call", "put")
        ]
    result = run(store, broker, clock)
    assert [s["strike"] for s in result["selection"]] == ["99.5", "199.5"]
    assert result["captures"][0]["iv_categories"] == {"zero": 4}
    assert not any(
        r["positive_iv_with_quote_checks"] for r in result["captures"][0]["observations"]
    )


def test_no_pair_at_earliest_expiry_does_not_select_later_expiry(store):
    registration(store)
    clock = Clock()
    broker = DataBroker(clock)
    broker.two_pages = False
    broker.contracts["SPY"] = [
        contract("SPY", "call"),
        contract("SPY", "call", expiry="2026-11-17"),
        contract("SPY", "put", expiry="2026-11-17"),
    ]
    result = run(store, broker, clock)
    assert result["selection"][0]["reason"] == "earliest_expiry_has_no_paired_strike"
    assert result["captures"][0]["received_snapshots"] == 2
    assert result["captures"][0]["iv_categories"] == {"unobserved": 2, "positive": 2}


@pytest.mark.parametrize(
    "case", ["third_page", "repeated_token", "duplicate_symbol", "no_pagination_field"]
)
def test_incomplete_or_malformed_metadata_never_selects_partial_page(store, case):
    registration(store)
    clock = Clock()
    broker = DataBroker(clock)
    original = broker.option_contracts_page

    def metadata(underlying, *args, **kwargs):
        value = original(underlying, *args, **kwargs)
        if underlying == "SPY":
            if case in ("third_page", "repeated_token"):
                value["next_page_token"] = (
                    "page2" if case == "repeated_token" or not kwargs.get("page_token") else "page3"
                )
            elif case == "duplicate_symbol" and kwargs.get("page_token"):
                value["option_contracts"] = [contract("SPY", "call")]
            elif case == "no_pagination_field":
                value.pop("next_page_token")
        return value

    broker.option_contracts_page = metadata
    result = run(store, broker, clock)
    assert result["selection"][0]["state"] == "unavailable"
    assert result["selection"][1]["state"] == "selected"
    assert result["captures"][0]["received_snapshots"] == 2
    assert sum(call[0] == "metadata" and call[1] == "SPY" for call in broker.calls) <= 2


@pytest.mark.parametrize("field", ["multiplier", "size", "deliverables"])
def test_missing_standardness_evidence_is_unknown_not_defaulted(store, field):
    registration(store)
    clock = Clock()
    broker = DataBroker(clock)
    for row in broker.contracts["SPY"]:
        row.pop(field)
    result = run(store, broker, clock)
    assert result["selection"][0]["metadata_exclusions"] == {"standardness_unknown": 2}
    assert result["selection"][0]["state"] == "unavailable"


def test_quote_timing_alignment_and_iv_categories_are_separate(store):
    registration(store)
    clock = Clock()
    broker = DataBroker(clock)
    broker.option_age = 31  # fresh but not synchronized with the bracketing IEX quotes
    result = run(store, broker, clock)
    rows = result["captures"][0]["observations"]
    assert all(
        row["quote_status"] == "valid" and row["timestamp_gap_seconds"] == 31 for row in rows
    )
    assert not any(row["positive_iv_with_quote_checks"] for row in rows)
    assert [probe.iv_category(value) for value in (None, float("nan"), 0, -0.1, 0.2)] == [
        "missing",
        "nonfinite",
        "zero",
        "negative",
        "positive",
    ]
    assert (
        probe.quote_diagnostic(
            {"bp": 1e308, "ap": 1.1e308, "t": clock().isoformat()}, clock().isoformat()
        )["status"]
        == "valid"
    )


def test_missing_after_underlying_receipt_cannot_pass_full_quote_check(store):
    registration(store)
    clock = Clock()
    broker = DataBroker(clock)
    broker.fail_after_quote = True
    result = run(store, broker, clock)
    assert all(row["iv_category"] == "positive" for row in result["captures"][0]["observations"])
    assert not any(
        row["positive_iv_with_quote_checks"] for row in result["captures"][0]["observations"]
    )
    assert result["request_budget"]["failed"] == 1


def test_late_snapshot_retains_actual_values_but_never_passes_checks(store):
    registration(store)
    clock = Clock()
    broker = DataBroker(clock)
    broker.snapshot_delay = 120
    result = run(store, broker, clock)
    assert result["captures"][0]["received_snapshots"] == 4
    assert result["request_budget"]["late"] == 1
    assert all(
        row["iv_category"] == "positive" and row["quote_status"] == "late_receipt"
        for row in result["captures"][0]["observations"]
    )
    assert not any(
        row["positive_iv_with_quote_checks"] for row in result["captures"][0]["observations"]
    )
    assert not any(call[0] == "legacy" for call in broker.calls)


def test_skipped_first_window_cannot_reselect_in_second_or_later_session(store):
    registration(store)
    clock = Clock(at(clock="10:15"))
    broker = DataBroker(clock)
    probe.due_capture(store, clock())
    result = run(store, broker, clock, 2)
    assert result["captures"][0]["state"] == "missed"
    assert not broker.calls
    assert result["expected_observations"] == 8
    clock.now = at("2026-11-10", "10:00")
    probe.run_capture(store, broker, 1, clock=clock)
    assert not broker.calls


def test_uncertain_request_reservation_is_consumed_across_restart(store, monkeypatch):
    reg = registration(store)
    clock = Clock()
    broker = DataBroker(clock)
    original = broker.option_contracts_page
    crashed = False

    def once(underlying, *args, **kwargs):
        nonlocal crashed
        if not crashed:
            crashed = True
            broker.calls.append(("metadata_crashed", underlying))
            raise SystemExit("simulated process death after send")
        return original(underlying, *args, **kwargs)

    broker.option_contracts_page = once
    confirm(store, clock())
    with pytest.raises(SystemExit):
        probe.run_capture(store, broker, 1, clock=clock)
    monkeypatch.setattr(probe, "owner_is_dead", lambda _: True)
    result = run(store, broker, clock)
    assert result["request_budget"]["unknown_outcomes"] == 1
    assert result["selection"][0]["state"] == "unavailable"
    assert not any(c[0] == "metadata" and c[1] == "SPY" for c in broker.calls)
    assert len(probe._requests(store, reg)) == len(broker.calls)


def test_restart_after_deadline_preserves_genuine_saved_capture_receipts(store, monkeypatch):
    registration(store)
    clock = Clock()
    broker = DataBroker(clock)
    original = probe._capture_result
    monkeypatch.setattr(
        probe,
        "_capture_result",
        lambda *a, **kw: (_ for _ in ()).throw(SystemExit("death before final capture commit")),
    )
    confirm(store, clock())
    with pytest.raises(SystemExit):
        probe.run_capture(store, broker, 1, clock=clock)
    assert len(broker.calls) == 9
    monkeypatch.setattr(probe, "_capture_result", original)
    monkeypatch.setattr(probe, "owner_is_dead", lambda _: True)
    clock.now = at(clock="10:03")
    probe.due_capture(store, clock())
    result = probe.public_summary(store)
    assert result["captures"][0]["state"] == "interrupted"
    assert result["captures"][0]["received_snapshots"] == 4
    assert all(r["positive_iv_with_quote_checks"] for r in result["captures"][0]["observations"])
    assert len(broker.calls) == 9


def test_unexpected_live_process_exception_terminalizes_capture(store, monkeypatch):
    registration(store)
    clock = Clock()
    broker = DataBroker(clock)
    monkeypatch.setattr(
        probe, "_select", lambda *a, **kw: (_ for _ in ()).throw(ValueError("fixture corruption"))
    )
    result = run(store, broker, clock)
    assert result["captures"][0]["state"] == "interrupted"
    assert probe.due_capture(store, clock()) is None
    assert len(broker.calls) == 1


def test_reservation_wait_crossing_deadline_never_dispatches_http(store):
    reg = registration(store)
    capture = reg["captures"][0]
    values = iter((at(clock="10:01:59"), at(clock="10:02:00")))
    called = []
    receipt = probe._request(
        store,
        reg,
        capture,
        "reserved-too-late",
        {},
        lambda: called.append(True),
        lambda: next(values),
    )
    assert receipt["state"] == "not_dispatched"
    assert not called
    assert probe.public_summary(store)["request_budget"]["reserved"] == 1


def test_durable_request_budget_cannot_exceed_twelve_even_for_different_slots(store):
    reg = registration(store)
    calls = []
    for index in range(20):
        probe._request(
            store,
            reg,
            reg["captures"][0],
            "budget-fixture-" + str(index),
            {},
            lambda: calls.append(True),
            lambda: at(),
        )
    assert len(calls) == 12
    assert probe.public_summary(store)["request_budget"]["remaining"] == 0


def test_broker_session_mismatch_holds_probe_without_network(store):
    registration(store)
    clock = Clock()
    broker = DataBroker(clock)
    confirm(store, clock())
    store.set("calendar:2026-11-09", [{"open": "09:30", "close": "13:00"}])
    result = probe.run_capture(store, broker, 1, clock=clock)
    assert result["captures"][0]["reason"] == "calendar_incompatibility"
    assert not broker.calls


def test_invalid_registration_does_not_crash_public_export_but_blocks_collection(store):
    registration(store)
    changed = store.get(probe.REGISTRATION_KEY)
    changed["protocol_sha256"] = "changed"
    store.set(probe.REGISTRATION_KEY, changed)
    assert probe.public_summary(store)["status"] == "invalid_registration"
    with pytest.raises(ValueError, match="differs"):
        probe.run_capture(store, DataBroker(Clock()), 1, clock=Clock())


def test_broker_helpers_are_single_gets_with_explicit_metadata_and_indicative_symbols():
    requests = []

    def transport(request):
        requests.append(request)
        return httpx.Response(200, json={"option_contracts": [], "next_page_token": None})

    broker = Broker.__new__(Broker)
    broker.client = httpx.Client(transport=httpx.MockTransport(transport))
    try:
        broker.option_contracts_page(
            "SPY", "2026-11-16", "2026-11-23", "99", "101", page_token="page2"
        )
        broker.option_snapshots([symbol("SPY"), symbol("SPY", "put")])
    finally:
        broker.client.close()
    assert [r.method for r in requests] == ["GET", "GET"]
    assert requests[0].url.host == "paper-api.alpaca.markets"
    assert dict(requests[0].url.params) == {
        "underlying_symbols": "SPY",
        "root_symbol": "SPY",
        "status": "active",
        "show_deliverables": "true",
        "expiration_date_gte": "2026-11-16",
        "expiration_date_lte": "2026-11-23",
        "strike_price_gte": "99",
        "strike_price_lte": "101",
        "limit": "1000",
        "page_token": "page2",
    }
    assert requests[1].url.host == "data.alpaca.markets"
    assert requests[1].url.path == "/v1beta1/options/snapshots"
    assert requests[1].url.params["feed"] == "indicative"
    assert requests[1].url.params["limit"] == "4"


@pytest.mark.parametrize(
    "time,day", [("09:29", "2026-11-09"), ("09:30", "2026-11-10"), ("16:30", "2026-11-10")]
)
def test_first_eligible_session_is_frozen_before_open(store, time, day):
    assert registration(store, at(clock=time))["session_day"] == day


@pytest.mark.parametrize("age,valid", [(-6, False), (-5, True), (90, True), (91, False)])
def test_quote_age_boundaries_and_finite_price_checks(age, valid):
    now = at()
    quote = {"bp": 1, "ap": 3, "t": (now - timedelta(seconds=age)).isoformat()}
    assert probe.quote_diagnostic(quote, now.isoformat())["fresh"] is valid
    assert (
        probe.quote_diagnostic({**quote, "bp": float("nan")}, now.isoformat())[
            "finite_positive_ordered"
        ]
        is False
    )
    assert probe.quote_diagnostic({**quote, "bp": 4}, now.isoformat())["status"] == "invalid_prices"


@pytest.mark.parametrize("change", ["open", "close", "day"])
def test_admission_checks_actual_calendar_and_never_moves_registered_windows(store, change):
    reg = registration(store)
    now = at()
    confirm(store, now)
    if change == "day":
        assert (
            probe.session_confirmation_reason(store, reg, now + timedelta(days=1))
            == "session_day_mismatch"
        )
    else:
        calendar = store.get("calendar:2026-11-09")
        calendar[0][change] = "10:00" if change == "open" else "13:00"
        store.set("calendar:2026-11-09", calendar)
        assert probe.capture_admission(store, now) is None
        assert probe.public_summary(store)["captures"][0]["reason"] == "calendar_incompatibility"
    assert store.get(probe.REGISTRATION_KEY) == reg


def test_nonfinite_iv_is_retained_and_not_coerced_to_missing(store):
    registration(store)
    clock = Clock()
    broker = DataBroker(clock)
    broker.iv = float("nan")
    result = run(store, broker, clock)
    assert result["captures"][0]["iv_categories"] == {"nonfinite": 4}
    assert not any(
        r["positive_iv_with_quote_checks"] for r in result["captures"][0]["observations"]
    )
    assert "nan" in json.dumps(probe._requests(store, store.get(probe.REGISTRATION_KEY)))


def test_unrequested_snapshots_remain_unknown(store):
    registration(store)
    clock = Clock()
    broker = DataBroker(clock)
    original = broker.option_snapshots

    def wrong_scope(symbols):
        result = original(symbols)
        result["snapshots"][symbol("SPY", strike=120)] = result["snapshots"][symbols[0]]
        return result

    broker.option_snapshots = wrong_scope
    result = run(store, broker, clock)
    assert result["captures"][0]["iv_categories"] == {"unobserved": 4}
    assert not any(
        r["positive_iv_with_quote_checks"] for r in result["captures"][0]["observations"]
    )


def test_raw_positive_iv_does_not_override_explicit_missing_camelcase_value():
    result = probe._coverage_counts(
        [
            {
                "symbol": symbol("SPY"),
                "impliedVolatility": None,
                "implied_volatility": 0.2,
                "greeks": {"delta": 0, "gamma": float("nan"), "theta": None},
            }
        ],
        at().isoformat(),
    )
    assert result["iv_categories"] == {"missing": 1}
    assert result["finite_greek_fields"] == {
        "delta": 1,
        "gamma": 0,
        "rho": 0,
        "theta": 0,
        "vega": 0,
    }
