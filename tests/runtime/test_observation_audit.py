import json
from datetime import datetime, timedelta, timezone

import pytest

from agent_trader.runtime.cohorts import ForwardLab, freeze_signals
from agent_trader.runtime.experiments import Experiments
from agent_trader.runtime.observation_audit import content_hash, date_composition, paired_estimators
from agent_trader.runtime.promotion_policy import (
    POLICY_SHA256,
    install_promotion_policy,
    policy_key,
    policy_status,
)
from agent_trader.runtime.store import dumps
from tests.runtime.test_adaptive_lab import (
    setup as adaptive_setup,
    run as adaptive_run,
    quote as adaptive_quote,
)
from tests.runtime.test_learning import raw_bars, sessions, quotes
from tests.runtime.test_system import proposal


def install(store, experiment_id="test-filter"):
    effective = datetime.now(timezone.utc) + timedelta(seconds=1)
    review = {
        "approved": True,
        "independent": True,
        "author": "implementation-agent",
        "reviewer": "independent-review-agent",
        "policy_sha256": POLICY_SHA256,
        "reviewed_at": (effective - timedelta(seconds=1)).isoformat(),
        "validation": "Isolated positive, disagreement, legacy and migration fixtures passed.",
    }
    receipt = install_promotion_policy(
        store, [experiment_id], effective_at=effective.isoformat(), review=review
    )[0]
    return receipt, effective, review


def add_paired_samples(store, receipt, effective, *, disagreement=False):
    day = effective.date() + timedelta(days=1)
    for index in range(20):
        while day.weekday() >= 5:
            day += timedelta(days=1)
        observations = (
            [(-0.001, -0.001), (-0.01, 0)]
            if disagreement and index < 19
            else [(0, 0.005)] * (16 if disagreement else 2)
        )
        for sample, (incumbent, challenger) in enumerate(observations):
            payload = {
                "day": day.isoformat(),
                "entered_at": datetime.combine(day, effective.timetz()).isoformat(),
                "incumbent_return": incumbent,
                "challenger_return": challenger,
                "eligibility_version": "plan-evidence-v2",
            }
            if receipt:
                payload["promotion_policy_receipt_sha256"] = receipt["receipt_sha256"]
            store.db.execute(
                "INSERT INTO shadow VALUES(?,?,?,?,?,?)",
                (
                    f"fixture-{index}-{sample}",
                    "test-filter",
                    "AAPL",
                    "intraday",
                    "closed",
                    dumps(payload),
                ),
            )
        day += timedelta(days=1)


def test_uneven_date_weights_explain_single_symbol_concentration():
    observations = [("2026-10-30", -0.0025, True)] * 29 + [("2026-11-02", -0.094, True)]
    result = date_composition(observations)
    assert result["closed_opportunities"] == 30
    assert result["closed_entry_dates"] == 2
    assert [r["closed_opportunities"] for r in result["by_entry_date"]] == [29, 1]
    assert [r["entry_date_weight"] for r in result["by_entry_date"]] == [0.5, 0.5]
    assert result["maximum_opportunity_weight"] == 0.5
    assert result["weight_concentration_vs_equal_opportunities"] == 15
    assert result["uneven_date_composition"] is True


def test_policy_preserves_contract_and_holds_existing_ambiguous_samples(store):
    lab = Experiments(store)
    lab.register(proposal())
    original = store.rows("SELECT payload FROM experiments")[0]["payload"]
    add_paired_samples(store, None, datetime.now(timezone.utc))
    assert not lab.evaluate()
    assert store.get("experiment-look:test-filter") is None
    assert (
        lab.progress()["test-filter"]["promotion_policy"]["reason"]
        == "independent_prospective_policy_review_required"
    )
    with pytest.raises(ValueError, match="zero observations"):
        install(store)
    assert store.rows("SELECT payload FROM experiments")[0]["payload"] == original
    assert not store.get(policy_key("test-filter"))


def test_disagreeing_absolute_estimators_cannot_promote_under_new_policy(store):
    lab = Experiments(store)
    lab.register(proposal())
    receipt, effective, _ = install(store)
    add_paired_samples(store, receipt, effective, disagreement=True)
    stats = lab.progress()["test-filter"]["estimators"]
    assert stats["opportunity_weighted_absolute_net"] == pytest.approx(0.0011296296296296295)
    assert stats["entry_date_weighted_absolute_net"] == pytest.approx(-0.000225)
    assert stats["absolute_positive_disagreement"] is True
    assert not lab.evaluate()
    event = json.loads(
        store.rows("SELECT payload FROM events WHERE kind='experiment_review'")[0]["payload"]
    )
    assert event["lower_bound"] > 0
    assert event["absolute_mean_net"] > 0
    assert event["absolute_entry_date_mean_net"] < 0
    assert store.rows("SELECT state FROM experiments")[0]["state"] == "shadow"


def test_reviewed_policy_promotes_only_with_both_positive_absolute_estimators(store):
    lab = Experiments(store)
    lab.register(proposal())
    receipt, effective, review = install(store)
    original = store.rows("SELECT payload FROM experiments")[0]["payload"]
    add_paired_samples(store, receipt, effective)
    assert lab.evaluate() == ["test-filter"]
    assert store.get("incumbent_filter:intraday")["stage"] == "25% pilot risk"
    assert install_promotion_policy(
        store, ["test-filter"], effective_at=effective.isoformat(), review=review
    ) == [receipt]
    assert len(store.rows("SELECT id FROM events WHERE kind='promotion_policy_registered'")) == 1
    assert store.rows("SELECT payload FROM experiments")[0]["payload"] == original


@pytest.mark.parametrize(
    "case",
    [
        "open",
        "not_evaluable",
        "prior_look",
        "stale_parent",
        "unapproved",
        "same_reviewer",
        "future_review",
        "wrong_hash",
    ],
)
def test_policy_migration_is_atomic_and_rejects_ineligible_histories(store, case):
    lab = Experiments(store)
    lab.register(proposal())
    lab.register({**proposal(), "id": "second", "exact_change": "avoid_risk_off"})
    effective = datetime.now(timezone.utc) + timedelta(seconds=1)
    review = {
        "approved": True,
        "independent": True,
        "author": "author",
        "reviewer": "reviewer",
        "policy_sha256": POLICY_SHA256,
        "reviewed_at": effective.isoformat(),
        "validation": "isolated regression suite",
    }
    if case in ("open", "not_evaluable"):
        store.db.execute(
            "INSERT INTO shadow VALUES(?,?,?,?,?,?)",
            ("old", "second", "AAPL", "intraday", case, "{}"),
        )
    elif case == "prior_look":
        store.set("experiment-look:second", 0)
    elif case == "stale_parent":
        store.set("incumbent_filter:intraday", {"id": "different-parent"})
    elif case == "unapproved":
        review["approved"] = False
    elif case == "same_reviewer":
        review["reviewer"] = "author"
    elif case == "future_review":
        review["reviewed_at"] = (effective + timedelta(seconds=1)).isoformat()
    else:
        review["policy_sha256"] = "wrong"
    with pytest.raises(ValueError):
        install_promotion_policy(
            store, ["test-filter", "second"], effective_at=effective.isoformat(), review=review
        )
    assert not store.get(policy_key("test-filter")) and not store.get(policy_key("second"))


def test_policy_receipt_cannot_change_or_cover_pre_cutoff_observations(store):
    lab = Experiments(store)
    lab.register(proposal())
    receipt, effective, review = install(store)
    with pytest.raises(ValueError, match="immutable"):
        install_promotion_policy(
            store,
            ["test-filter"],
            effective_at=(effective + timedelta(seconds=1)).isoformat(),
            review=review,
        )
    status = policy_status(
        store,
        "test-filter",
        proposal(),
        [
            {
                "entered_at": (effective - timedelta(seconds=1)).isoformat(),
                "promotion_policy_receipt_sha256": receipt["receipt_sha256"],
            }
        ],
    )
    assert status["ready"] is False
    assert (
        policy_status(store, "test-filter", {**proposal(), "minimum_samples": 100})["ready"]
        is False
    )


def test_fixed_quote_receipts_reproduce_costs_and_retry_keeps_first_quote(store):
    from agent_trader.runtime.config import ET

    before = datetime(2026, 10, 30, 8, 15, tzinfo=ET)
    frozen = freeze_signals(store, raw_bars(), sessions(), before)
    lab = ForwardLab(store)
    opened, closed = before.replace(hour=9, minute=30), before.replace(hour=16, minute=0)
    entry, exit_at = opened + timedelta(minutes=5), closed - timedelta(minutes=12)
    lab.observe(quotes(entry), entry, opened, closed)
    lab.mark(quotes(exit_at, 151, 151.03), exit_at)
    row = store.rows("SELECT * FROM cohort_observations WHERE branch='intraday' LIMIT 1")[0]
    payload = json.loads(row["payload"])
    receipt = store.get(f"observation-quote:cohort:{row['id']}:exit")
    assert receipt["quote"] == quotes(exit_at, 151, 151.03)[row["symbol"]]
    assert receipt["calculation"]["baseline_net"] == payload["observed_baseline_horizon_return"]
    assert receipt["calculation"]["total_base_cost_fraction"] == pytest.approx(
        0.002 + 0.01 / 150.01 + 0.03 / 151.03
    )
    assert receipt["sha256"] == content_hash({k: v for k, v in receipt.items() if k != "sha256"})
    lab.mark(quotes(exit_at + timedelta(minutes=1), 152, 152.01), exit_at + timedelta(minutes=1))
    assert store.get(f"observation-quote:cohort:{row['id']}:exit") == receipt
    assert store.get("cohort_study")["protocol_sha256"]
    assert store.get("cohort-signals:2026-10-30") == frozen


def test_adaptive_receipts_capture_exit_timestamp_and_atomic_rollback(store, monkeypatch):
    import agent_trader.runtime.adaptive_lab as module

    lab, now, packet = adaptive_setup(store)
    adaptive_run(lab, now, packet)
    row = store.rows("SELECT id FROM adaptive_observations WHERE state='open'")[0]
    close = now.replace(hour=15, minute=48)
    original = module.record_quote
    monkeypatch.setattr(
        module,
        "record_quote",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("receipt write failed")),
    )
    with pytest.raises(RuntimeError, match="receipt write failed"):
        lab.mark({"AAPL": adaptive_quote(close, 101, 101.01)}, close)
    assert (
        store.rows("SELECT state FROM adaptive_observations WHERE id=?", (row["id"],))[0]["state"]
        == "open"
    )
    assert not store.get(f"observation-quote:adaptive:{row['id']}:exit")
    monkeypatch.setattr(module, "record_quote", original)
    lab.mark({"AAPL": adaptive_quote(close, 101, 101.01)}, close)
    receipt = store.get(f"observation-quote:adaptive:{row['id']}:exit")
    assert receipt["quote"]["t"] == close.isoformat()
    assert receipt["calculation"]["baseline_net"] == pytest.approx(101 / 100.01 - 1 - 0.002)


def test_legacy_observations_are_described_without_inventing_quote_receipts(store):
    store.db.execute(
        "INSERT INTO cohort_observations VALUES(?,?,?,?,?,?,?)",
        (
            "legacy",
            "2026-10-30",
            "intraday",
            "trend",
            "AAPL",
            "closed",
            dumps(
                {
                    "signal": True,
                    "observed_signal_horizon_return": 0.01,
                    "observed_baseline_horizon_return": 0.01,
                    "stressed_signal_horizon_return": 0.007,
                }
            ),
        ),
    )
    trial = next(
        t
        for t in ForwardLab(store).summary()["trials"]
        if t["branch"] == "intraday" and t["rule"] == "trend"
    )
    assert trial["date_composition"]["closed_opportunities"] == 1
    assert not store.rows("SELECT key FROM kv WHERE key LIKE 'observation-quote:%'")
    assert paired_estimators([])["absolute_positive_disagreement"] is False


@pytest.mark.parametrize("disagreement", [False, True])
def test_review_look_and_result_are_atomic_on_receipt_failure(store, monkeypatch, disagreement):
    lab = Experiments(store)
    lab.register(proposal())
    receipt, effective, _ = install(store)
    add_paired_samples(store, receipt, effective, disagreement=disagreement)
    original = store.event

    def fail_review(kind, *args, **kwargs):
        if kind in ("experiment_review", "strategy_promoted"):
            raise RuntimeError("review receipt failure")
        return original(kind, *args, **kwargs)

    monkeypatch.setattr(store, "event", fail_review)
    with pytest.raises(RuntimeError, match="review receipt failure"):
        lab.evaluate()
    assert store.get("experiment-look:test-filter") is None
    assert store.get("incumbent_filter:intraday") is None
    assert store.rows("SELECT state FROM experiments")[0]["state"] == "shadow"
    monkeypatch.setattr(store, "event", original)
    assert lab.evaluate() == ([] if disagreement else ["test-filter"])
    assert store.get("experiment-look:test-filter") == 0
    assert (
        len(
            store.rows(
                "SELECT id FROM events WHERE kind IN ('experiment_review','strategy_promoted')"
            )
        )
        == 1
    )
    assert not lab.evaluate()
    assert (
        len(
            store.rows(
                "SELECT id FROM events WHERE kind IN ('experiment_review','strategy_promoted')"
            )
        )
        == 1
    )


def test_rollback_state_and_incumbent_and_receipt_are_atomic(store, monkeypatch):
    lab = Experiments(store)
    lab.register(proposal())
    receipt, effective, _ = install(store)
    add_paired_samples(store, receipt, effective)
    assert lab.evaluate() == ["test-filter"]
    store.db.execute(
        "INSERT INTO equity(at,day,branch,value) VALUES(?,?,?,?)",
        (effective.isoformat(), effective.date().isoformat(), "intraday", 9700),
    )
    active = store.get("incumbent_filter:intraday")
    original = store.event

    def fail_rollback(kind, *args, **kwargs):
        if kind == "strategy_rolled_back":
            raise RuntimeError("rollback receipt failure")
        return original(kind, *args, **kwargs)

    monkeypatch.setattr(store, "event", fail_rollback)
    with pytest.raises(RuntimeError, match="rollback receipt failure"):
        lab.evaluate()
    assert store.get("incumbent_filter:intraday") == active
    assert store.rows("SELECT state FROM experiments")[0]["state"] == "promoted"
    monkeypatch.setattr(store, "event", original)
    lab.evaluate()
    assert store.get("incumbent_filter:intraday") is None
    assert store.rows("SELECT state FROM experiments")[0]["state"] == "rolled_back"
    assert len(store.rows("SELECT id FROM events WHERE kind='strategy_rolled_back'")) == 1


@pytest.mark.parametrize(
    "malformation", ["not_object", "invalid_cutoff", "unapproved_review", "wrong_identity"]
)
def test_malformed_policy_fails_closed_without_crashing_other_reviews(store, malformation):
    lab = Experiments(store)
    lab.register(proposal())
    receipt, effective, _ = install(store)
    add_paired_samples(store, receipt, effective)
    if malformation == "not_object":
        changed = []
    else:
        changed = {k: v for k, v in receipt.items() if k != "receipt_sha256"}
        if malformation == "invalid_cutoff":
            changed["effective_at"] = "bad-date"
        elif malformation == "unapproved_review":
            changed["review"] = {**changed["review"], "approved": False}
        else:
            changed["experiment_id"] = "different-study"
        changed["receipt_sha256"] = content_hash(changed)
    store.set(policy_key("test-filter"), changed)
    assert not lab.evaluate()
    assert not lab.progress()["test-filter"]["promotion_policy"]["ready"]
    assert store.get("experiment-look:test-filter") is None


def test_prospective_shadow_capture_pins_policy_and_exact_quotes(store, plan, quote):
    lab = Experiments(store)
    lab.register(proposal())
    receipt, effective, _ = install(store)
    now = effective + timedelta(minutes=1)
    plan = {
        **plan,
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "evidence": [{**plan["evidence"][0], "observed_at": now.isoformat()}],
    }
    quote = {**quote, "t": now.isoformat()}
    lab.consider(plan, quote, "risk_on", now)
    row = store.rows("SELECT id,payload FROM shadow")[0]
    payload = json.loads(row["payload"])
    assert payload["promotion_policy_receipt_sha256"] == receipt["receipt_sha256"]
    assert store.get(f"observation-quote:shadow:{row['id']}:entry")["quote"] == quote


@pytest.mark.parametrize("case", ["missing", "short", "stale"])
def test_unknown_market_input_excludes_only_dependent_fixed_rule(store, case):
    from agent_trader.runtime.config import ET

    before = datetime(2026, 10, 30, 8, 15, tzinfo=ET)
    bars = raw_bars()
    if case == "missing":
        bars.pop("SPY")
    elif case == "short":
        bars["SPY"] = bars["SPY"][-20:]
    else:
        bars["SPY"] = bars["SPY"][:-1]
    frozen = freeze_signals(store, bars, sessions(), before)
    assert len(frozen["flags"]["AAPL"]) == 5
    assert "market_confirmed_trend" not in frozen["flags"]["AAPL"]
    assert not store.rows("SELECT id FROM cohort_expected WHERE rule='market_confirmed_trend'")
    exclusions = store.get("cohort-exclusions:2026-10-30")
    assert exclusions["feature_validation_version"] == "fixed-broker-session-inputs-v3"
    assert exclusions["input_exclusions"][0]["dependency"] == "SPY"
    assert exclusions["input_exclusions"][0]["excluded_opportunities"] == 2


def test_complete_market_input_keeps_frozen_signals_and_protocol_unchanged(store):
    from agent_trader.runtime.config import ET
    from agent_trader.runtime.exploration import RULES, clean_bars, rule_signal

    before = datetime(2026, 10, 30, 8, 15, tzinfo=ET)
    bars = raw_bars()
    frozen = freeze_signals(store, bars, sessions(), before)
    data = clean_bars(bars, "2026-10-30")
    assert frozen["flags"]["AAPL"] == {
        rule: rule_signal(rule, data["AAPL"][-21:], True) for rule in RULES
    }
    original_hash = store.get("cohort_study")["protocol_sha256"]
    broken = {"AAPL": bars["AAPL"]}
    assert freeze_signals(store, broken, sessions(), before + timedelta(minutes=1)) == frozen
    assert store.get("cohort_study")["protocol_sha256"] == original_hash
    assert store.get("cohort-exclusions:2026-10-30")["input_exclusions"] == []


def test_missing_market_input_exclusions_do_not_double_count_swing_overlap(store):
    from agent_trader.runtime.config import ET

    store.db.execute(
        "INSERT INTO cohort_observations VALUES(?,?,?,?,?,?,?)",
        (
            "already-open",
            "2026-10-29",
            "swing",
            "market_confirmed_trend",
            "AAPL",
            "open",
            "{}",
        ),
    )
    before = datetime(2026, 10, 30, 8, 15, tzinfo=ET)
    freeze_signals(store, {"AAPL": raw_bars()["AAPL"]}, sessions(), before)
    exclusions = store.get("cohort-exclusions:2026-10-30")
    assert exclusions["overlap_opportunities"] == 1
    assert exclusions["input_exclusions"][0]["branches"] == ["intraday"]
    assert exclusions["input_exclusions"][0]["excluded_opportunities"] == 1


def approve_global(store, effective=None):
    from agent_trader.runtime.promotion_policy import approve_promotion_policy

    effective = effective or datetime.now(timezone.utc)
    review = {
        "approved": True,
        "independent": True,
        "author": "author",
        "reviewer": "independent-reviewer",
        "policy_sha256": POLICY_SHA256,
        "reviewed_at": effective.isoformat(),
        "validation": "Independent implementation review and regression results.",
    }
    approval = approve_promotion_policy(store, effective_at=effective.isoformat(), review=review)
    return approval, review


def test_global_approval_applies_only_to_new_registrations_and_is_immutable(store):
    from agent_trader.runtime.promotion_policy import approve_promotion_policy, approval_key

    lab = Experiments(store)
    lab.register(proposal())
    assert not store.get(policy_key("test-filter"))
    approval, review = approve_global(store)
    new = {**proposal(), "id": "new-filter", "exact_change": "avoid_risk_off"}
    assert lab.register(new)
    receipt = store.get(policy_key("new-filter"))
    assert receipt["global_approval_sha256"] == approval["approval_sha256"]
    assert policy_status(store, "new-filter", new)["ready"]
    assert not store.get(policy_key("test-filter"))
    assert (
        approve_promotion_policy(store, effective_at=approval["effective_at"], review=review)
        == approval
    )
    with pytest.raises(ValueError, match="immutable"):
        approve_promotion_policy(
            store,
            effective_at=approval["effective_at"],
            review={**review, "validation": "different"},
        )
    store.set(approval_key(), {**approval, "approval_sha256": "tampered"})
    assert not policy_status(store, "new-filter", new)["ready"]


def test_future_approved_cutoff_defers_capture_then_links_first_sample(store, plan, quote):
    effective = datetime.now(timezone.utc) + timedelta(hours=1)
    approve_global(store, effective)
    lab = Experiments(store)
    lab.register(proposal())
    plan = {
        **plan,
        "expires_at": (effective + timedelta(hours=1)).isoformat(),
        "evidence": [
            {**plan["evidence"][0], "observed_at": (effective - timedelta(minutes=2)).isoformat()}
        ],
    }
    for now in (effective - timedelta(minutes=1), effective):
        lab.consider(plan, {**quote, "t": now.isoformat()}, "risk_on", now)
        assert len(store.rows("SELECT id FROM shadow")) == (1 if now == effective else 0)
    p = json.loads(store.rows("SELECT payload FROM shadow")[0]["payload"])
    assert (
        p["promotion_policy_receipt_sha256"]
        == store.get(policy_key("test-filter"))["receipt_sha256"]
    )


def test_new_registration_and_policy_pin_rollback_together(store, monkeypatch):
    approve_global(store)
    original = store.event

    def fail_registration(kind, *args, **kwargs):
        if kind == "experiment_registered":
            raise RuntimeError("registration receipt failure")
        return original(kind, *args, **kwargs)

    monkeypatch.setattr(store, "event", fail_registration)
    with pytest.raises(RuntimeError, match="registration receipt failure"):
        Experiments(store).register(proposal())
    assert not store.rows("SELECT id FROM experiments")
    assert not store.get(policy_key("test-filter"))
    assert not store.rows("SELECT id FROM events WHERE kind='promotion_policy_registered'")
