"""Bounded research sprint. Historical screens never authorize broker orders."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from .config import ET
from .engine import timestamp
from .store import dumps, utc_now

SPRINT_SESSIONS = 10
RULES = {
    "trend": "Prior close above its trailing 20-session average",
    "pullback": "Uptrend with a negative prior-session return",
    "breakout": "Prior close above the preceding 20 closes",
    "reversal": "Prior three-session return below -3%",
    "momentum": "Prior five-session return above 2%",
    "market_confirmed_trend": "Stock and SPY above their prior 20-session averages",
}
FILTERS = {
    "require_risk_on": "Trade only in a researched risk-on regime",
    "avoid_risk_off": "Abstain in risk-off or unknown regimes",
    "higher_confidence_075": "Require confidence of at least 0.75",
    "reward_risk_2": "Require at least 2:1 reward to entry risk",
}


def sprint_active(store):
    return len(store.get("exploration_sessions", [])) <= SPRINT_SESSIONS - 1


def seed_challengers(store):
    from .experiments import Experiments

    registry = Experiments(store)
    for branch in ("intraday", "swing"):
        active = store.get("incumbent_filter:" + branch)
        parent = active["id"] if active else "pilot-v1"
        for change, hypothesis in FILTERS.items():
            registry.register(
                {
                    "id": "explore-" + branch + "-" + change,
                    "branch": branch,
                    "hypothesis": hypothesis,
                    "exact_change": change,
                    "parent_version": parent,
                    "minimum_sessions": 20,
                    "minimum_samples": 30,
                    "cost_model": "Forward quote observation: 20bp plus observed spread; no fill guarantee",
                    "metrics": [
                        "paired net return by entry session",
                        "absolute net return",
                        "abstentions",
                    ],
                }
            )


def clean_bars(bars, as_of):
    """Only completed ET sessions; sorted, unique, finite positive OHLC prices."""
    import math

    result = {}
    for symbol, rows in bars.items():
        days = {}
        for row in rows:
            try:
                day = timestamp(row["t"]).astimezone(ET).date().isoformat()
                prices = {key: float(row[key]) for key in ("o", "h", "l", "c")}
                if day >= as_of or not all(math.isfinite(v) and v > 0 for v in prices.values()):
                    continue
                if prices["l"] > min(prices["o"], prices["c"]) or prices["h"] < max(
                    prices["o"], prices["c"]
                ):
                    continue
                days[day] = {"day": day, **prices}
            except (KeyError, ValueError, TypeError):
                continue
        result[symbol] = [days[d] for d in sorted(days)]
    return result


def rule_signal(rule, history, market_risk_on):
    closes = [x["c"] for x in history[-21:]]
    last, average = closes[-1], sum(closes[-20:]) / 20
    return {
        "trend": last > average,
        "pullback": last > average and last < closes[-2],
        "breakout": last > max(closes[-21:-1]),
        "reversal": last / closes[-4] - 1 < -0.03,
        "momentum": last / closes[-6] - 1 > 0.02,
        "market_confirmed_trend": last > average and market_risk_on,
    }[rule]


def historical_screen(bars, as_of):
    """Fixed 12 trials, chronological split + purge; descriptive, never promotion evidence.

    A rule observes only previous closes and enters next open. Swing samples hold
    five sessions without overlapping another sample for the same symbol/trial.
    Same-day opportunities are clustered rather than counted as independent days.
    """
    data = clean_bars(bars, as_of)
    dates = sorted({r["day"] for rows in data.values() for r in rows})
    if len(dates) < 100:
        raise ValueError("Historical screen requires at least 100 completed sessions")
    split = dates[int(len(dates) * 0.65)]
    market = data.get("SPY", [])
    regimes = {}
    for i in range(21, len(market)):
        prev = market[i - 20 : i]
        regimes[market[i]["day"]] = prev[-1]["c"] > sum(r["c"] for r in prev) / 20
    trials = []
    for branch, holding in (("intraday", 1), ("swing", 5)):
        for rule in RULES:
            samples = {"development": [], "holdout": []}
            for symbol, rows in data.items():
                next_index = 21
                for i in range(21, len(rows) - holding + 1):
                    if i < next_index:
                        continue
                    entry, exit_bar = rows[i], rows[i + holding - 1]
                    if entry["day"] < split <= exit_bar["day"]:
                        continue  # purge overlapping labels at the split
                    partition = "development" if exit_bar["day"] < split else "holdout"
                    eligible = rule_signal(rule, rows[i - 21 : i], regimes.get(entry["day"], False))
                    gross = exit_bar["c"] / entry["o"] - 1
                    samples[partition].append(
                        {
                            "day": entry["day"],
                            "symbol": symbol,
                            "entered": eligible,
                            "net": gross - 0.002 if eligible else 0.0,
                            "stress": gross - 0.005 if eligible else 0.0,
                            "baseline": gross - 0.002,
                        }
                    )
                    next_index = i + holding
            metrics = {}
            for partition, records in samples.items():
                groups = {}
                for r in records:
                    groups.setdefault(r["day"], []).append(r)
                daily = [
                    {
                        key: sum(r[key] for r in values) / len(values)
                        for key in ("net", "stress", "baseline")
                    }
                    for values in groups.values()
                ]
                count = len(daily)
                metrics[partition] = {
                    "sessions": count,
                    "opportunities": len(records),
                    "signals": sum(r["entered"] for r in records),
                    "mean_daily_net": sum(r["net"] for r in daily) / count if count else None,
                    "mean_daily_stress": sum(r["stress"] for r in daily) / count if count else None,
                    "mean_daily_baseline": sum(r["baseline"] for r in daily) / count
                    if count
                    else None,
                }
            trials.append(
                {
                    "id": branch + "-" + rule,
                    "branch": branch,
                    "rule": rule,
                    "description": RULES[rule],
                    "holding_sessions": holding,
                    "state": "historical_screen_only",
                    **metrics,
                }
            )
    return {
        "at": utc_now(),
        "as_of_exclusive": as_of,
        "first_session": dates[0],
        "last_session": dates[-1],
        "split": split,
        "symbols": len(data),
        "dataset_sha256": hashlib.sha256(dumps(data).encode()).hexdigest(),
        "trial_count": len(trials),
        "trials": trials,
        "limitations": [
            "Exploratory historical screen; never counted toward forward promotion or paper P&L.",
            "Fixed present-day liquid universe: survivor/selection bias; adjusted historical data is not a point-in-time universe.",
            "Prior-session features, next-open entry; daily bars cannot test intraday catalyst timing, stops or fills.",
            "65/35 chronological split with boundary-label purge. Holdout has been inspected; future changes require new forward evidence.",
            "Equal-weight unit opportunities, cash for abstentions; no constrained portfolio simulation. Swing entry-day clusters overlap across symbols.",
            "20bp base / 50bp stressed round-trip costs are assumptions; IEX-only OHLC is not consolidated executable liquidity.",
            "Twelve fixed trials reported together; rankings are not statistical proof and correlated signals are not independent evidence.",
        ],
    }


def prepare_screen(config, broker, store):
    # Freeze the original data/holdout so daily reviews cannot silently resample it.
    screen = store.get("historical_screen")
    if screen:
        return screen
    from .research import UNIVERSE

    as_of = datetime.now(ET).date().isoformat()
    bars = broker.bars(UNIVERSE, days=420)
    screen = historical_screen(bars, as_of)
    artifact = config.state_dir / "exploration-history.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(dumps({"as_of": as_of, "bars": bars, "screen": screen}))
    store.set("historical_screen", screen)
    store.event(
        "historical_screen",
        {
            "summary": "Twelve fixed historical screens completed; exploratory only.",
            "dataset_sha256": screen["dataset_sha256"],
        },
    )
    return screen


def exploration_prompt(day, store, screen):
    from .cohorts import normalized_screen
    from .intelligence import observation_context, objective_scorecard
    from .adaptive_lab import AdaptiveLab, PROTOCOL
    from .research import BASE, UNIVERSE, forward_evidence
    from .experiments import Experiments

    score = objective_scorecard(store)
    history = normalized_screen(screen)
    historical_prior = {
        "metric_contract": history.get("metric_contract"),
        "dataset_sha256": history.get("dataset_sha256"),
        "limitations": "Exploratory, inspected historical sample with survivor and selection bias; never forward validation or portfolio returns.",
        "columns": [
            "id",
            "holding_sessions",
            "development_net",
            "development_stressed",
            "holdout_net",
            "holdout_stressed",
        ],
        "trials": [
            [
                t["id"],
                t.get("holding_sessions"),
                t.get("development", {}).get("mean_horizon_net_return"),
                t.get("development", {}).get("mean_horizon_stressed_return"),
                t.get("holdout", {}).get("mean_horizon_net_return"),
                t.get("holdout", {}).get("mean_horizon_stressed_return"),
            ]
            for t in history.get("trials", [])
        ],
    }
    context = {
        "day": day,
        "now": utc_now(),
        "observations": observation_context(store, max_chars=5500),
        "adaptive_tests": AdaptiveLab(store).context(max_trials=6),
        "adaptive_protocol": PROTOCOL,
        "fixed_forward_study": forward_evidence(store),
        "objective": {k: score[k] for k in ("objective", "research_funnel", "diagnostics")},
        "filter_sampling": Experiments(store).funnel(),
        "brief": {
            k: str(v)[:900] if isinstance(v, str) else v[:6]
            for k, v in store.get("brief", {}).items()
            if k in ("summary", "regime", "unknowns")
        },
        "catalogue": [
            {
                k: c.get(k)
                for k in (
                    "id",
                    "branch",
                    "state",
                    "expires_at",
                    "observation_ids",
                    "experiment_ids",
                )
            }
            | {"claim": c.get("claim", "")[:220]}
            for c in store.get("research_catalogue", [])[-36:]
        ],
        "catalogue_total": len(store.get("research_catalogue", [])),
        "historical_screen": historical_prior,
        "existing_experiments": [
            {
                "id": r["id"],
                "branch": r["branch"],
                "state": r["state"],
                **{
                    k: v
                    for k, v in json.loads(r["payload"]).items()
                    if k
                    in (
                        "exact_change",
                        "parent_version",
                        "minimum_sessions",
                        "minimum_samples",
                        "cost_model",
                    )
                },
            }
            for r in store.rows("SELECT * FROM experiments")[-18:]
        ],
        "allowed_adaptive_symbols": UNIVERSE,
        "supported_observation_features": [
            "return_1d",
            "return_3d",
            "return_5d",
            "price_vs_sma20",
            "gap_from_prior_close",
            "relative_gap_spy",
        ],
        "omitted_for_budget": {"catalogue_history": len(store.get("research_catalogue", [])) - 36}
        if len(store.get("research_catalogue", [])) > 36
        else {},
    }
    # Prune complete objects. Instructions never share the truncation budget.
    while len(json.dumps(context, default=str, separators=(",", ":"))) > 18500:
        if context["historical_screen"].get("trials"):
            context["historical_screen"]["trials"].pop()
            selected = "historical_trials"
        elif context["fixed_forward_study"].get("trials"):
            context["fixed_forward_study"]["trials"].pop()
            selected = "fixed_trials"
        elif len(context["catalogue"]) > 8:
            context["catalogue"].pop(0)
            selected = "catalogue"
        elif len(context["existing_experiments"]) > 6:
            context["existing_experiments"].pop(0)
            selected = "existing_experiments"
        elif context["observations"].get("records"):
            context["observations"]["records"].pop()
            selected = "observations"
        else:
            raise ValueError("Exploration context cannot fit without losing its evidence contract")
        context["omitted_for_budget"][selected] = context["omitted_for_budget"].get(selected, 0) + 1
    return (
        BASE
        + """
ROLE: continuing observation-led research designer.
The objective is repeatable net returns with controlled drawdown, not research volume.
Start with recorded surprises, cross-market differences, data failures or contrary
forward outcomes. Explain what changed and why it merits a new test. History supplies
base rates and failure cases; do not recite the same screens or tune their frozen study.
Consider at least one competing explanation (market exposure, costs, timing, feed
artifacts, selection or chance). A real observation does NOT establish causality.
Propose at most THREE distinct hypotheses per pass; an empty batch with an explicit
reason is better than duplicate claims. Review the catalogue, stale cards and existing
tests first. Re-review a useful expired card using its ID, preserving its trail.
Lack of outcome evidence does not by itself prevent preregistering a bounded research
test: testing is how we obtain that evidence. It does prevent calling the idea proven.
Narrow a novel observation into a measurable conjecture when the supported inputs
allow it; do not confuse proposed research with changing the frozen control study.
Use up to 3 focused searches and 3 primary-source checks. Spend them resolving a
specific uncertainty, not manufacturing citations for an original empirical idea.
Set evidence_basis=local_observation for an explicitly conjectural mechanism grounded
in supplied observation_ids; it can have no external sources. Set mixed/external and
cite actual readable primary URLs for external factual claims. Local ideas require
alternative_explanations and a precise predicted_outcome plus falsification. Never
invent observation IDs or silently treat old event dates as fresh evidence.
Use adaptive_contracts to make a reviewed idea measurable independently of trade plans:
immutable long-only numeric conjunctions (1–3 predicates, gte/lte) on the supported
fields; all ratios are decimal returns, not percentages. Define symbol scope, hypothesis_id,
branch, prediction and falsification. Intraday horizon=1 session; swing=5 actual sessions;
first valid quote 15–30 minutes after open, exit close minus12 minutes; 20bp base/50bp
stressed cost assumptions. Structured minimum_sessions is the FIXED number of entry
sessions (20..60 inclusive), not an extendable floor. Use 1..6 DISTINCT symbols.
Before returning each contract compute maximum_opportunities = minimum_sessions *
len(symbols), and require 30 <= minimum_signals <= maximum_opportunities.
Examples: one symbol/60 sessions/30 signals is structurally feasible; one symbol/20
sessions/30 signals or one symbol/60 sessions/200 signals is INVALID. Six symbols/60
sessions allow at most360 signals, not360 independent trials. False signals, missing
data and swing overlap can reduce observed counts; feasibility is not a guarantee.
If the question needs more than60 entry sessions, return an unsupported-design
uncertainty/proposal instead of claiming120 sessions in prose. Hypothesis and
falsification must exactly match the structured session/signal counts and horizon.
Insufficient signals at the fixed end are inconclusive; do not extend or retune.
Choose a feasible universe and horizon for the question rather than collecting a
single exceptional event and claiming generality. Both accepted and failed designs remain recorded.
Registration starts FUTURE sessions only; do not treat today's motivating result as
an out-of-sample test. At most3 new adaptive contracts per pass,6 active per branch.
These are observational tests, NOT executable strategies, portfolio returns or automatic
promotions. Unsupported features/event labels remain explicit development proposals.
Use the attached protocol's exact all-opportunity aggregation, including cash for
false signals. It does not report active-only conditional means. relative_gap_spy
uses current ask changes at the entry observation, not opening-auction gaps.
Existing executable filter exact_change values: require_risk_on, avoid_risk_off,
higher_confidence_075, higher_confidence_085, reward_risk_2; existing contracts immutable.
Inspect filter_sampling before proposing more filters: they need valid plan inputs.
When plans are absent, diagnose the documented event/data/setup bottleneck, accept
justified abstention, or design a separate future observational test. More filters
cannot repair absent inputs; never backfill their samples from another study.
A shadow_plan must name its exact hypothesis_id in this draft and have fresh levels
and verified event evidence. No options price plans; options remain qualitative
research. At night/stale quotes leave shadow_plans empty. Do not force trades.
Return ExplorationReport JSON. Source/method review permits testing, never proves edge.
CONTEXT:
"""
        + json.dumps(context, default=str, separators=(",", ":"))
    )


def record_report(store, report, day, *, morning=True):
    revision = hashlib.sha256(dumps(report).encode()).hexdigest()[:16]
    store.set("exploration_draft", {**report, "day": day, "at": utc_now(), "revision": revision})
    if morning:
        sessions = store.get("exploration_sessions", [])
        if day not in sessions:
            store.set("exploration_sessions", [*sessions, day])
        store.set("exploration_day", day)
    store.event(
        "exploration_completed",
        {
            "summary": report["summary"],
            "hypotheses": len(report["hypotheses"]),
            "state": "awaiting_independent_review",
        },
    )


def validation_prompt(store):
    from .cohorts import normalized_screen

    from .research import BASE
    from .adaptive_lab import PROTOCOL

    draft = store.get("exploration_draft", {})
    ids = sorted({i for h in draft.get("hypotheses", []) for i in h.get("observation_ids", [])})
    referenced_urls = {u for h in draft.get("hypotheses", []) for u in h.get("source_urls", [])}
    referenced_trials = {
        t for h in draft.get("hypotheses", []) for t in h.get("screen_trial_ids", [])
    }
    records = []
    for identity in ids:
        rows = store.rows(
            "SELECT id,payload FROM memory WHERE layer='market_observation_lead' AND id=?",
            (identity,),
        )
        if rows:
            r = json.loads(rows[0]["payload"])
            records.append(
                {
                    k: r.get(k)
                    for k in (
                        "id",
                        "kind",
                        "subject",
                        "observed_at",
                        "event_asof",
                        "values",
                        "provenance",
                    )
                }
            )
        else:
            records.append({"id": identity, "status": "missing; cannot validate"})
    screen = normalized_screen(store.get("historical_screen", {}))
    context = {
        "revision": draft.get("revision"),
        "draft_at": draft.get("at"),
        "hypotheses": draft.get("hypotheses", []),
        "sources": [
            {k: v for k, v in source.items() if k != "takeaway"}
            for source in draft.get("sources", [])
            if source.get("url") in referenced_urls
        ],
        "historical_screen": {
            "trials": [t for t in screen.get("trials", []) if t.get("id") in referenced_trials],
            "limitations": screen.get("limitations", []),
        },
        "adaptive_contracts": draft.get("adaptive_contracts", []),
        "adaptive_protocol": PROTOCOL,
        "observations": records,
    }
    instructions = """
ROLE: independent research validator, not the original researcher.
Use at most 1 focused search and 3 source checks (4 web actions total) to check primary sources and counterevidence.
For EVERY hypothesis return exactly one verdict. Accept for testing only when cited
evidence supports the external factual claims, falsification is concrete, and free-data limits
are explicit. Reject fabricated citations and historical claims unsupported by the
attached screen. Screen metrics are horizon returns averaged across unit opportunities,
grouped by entry session; five-session swing returns are NOT daily portfolio returns.
Do not accept that unit confusion, annualization, or fabricated executable fills.
For each verdict explicitly set source_check_status and checked_source_urls.
Verified means you independently accessed the cited primary content supporting the
bounded mechanism, not merely the supplied abstract, URL list or a search snippet.
Mark blocked, unfinished or supplied-only checks partial/unverified and needs_work.
List only URLs actually checked, drawn from that hypothesis's source_urls.
All its cited URLs must be checked for acceptance; otherwise hold it for later.
For local_observation conjectures, a published paper is NOT required: validate the
supplied immutable observations, their event/capture dates, competing explanations,
and the proposed future prediction. An observed association does not prove the
conjectured mechanism. With no external claims/sources use source_check_status=
not_applicable, checked_source_urls=[]; never use that to exempt an external fact.
Set method_check_status=reviewed only when the proposed test measures the actual
claim, supported features/horizon/units match, and falsification and costs are explicit.
For adaptive contracts verify 20 <= minimum_sessions <= 60, 1..6 distinct symbols,
and 30 <= minimum_signals <= minimum_sessions * len(symbols). Counts in hypothesis
and falsification prose must match these exact JSON fields; the window cannot extend.
An adaptive contract must reference this hypothesis, use the same branch, and test
only future data; motivating observations are not validation samples. Hold ideas
whose test fails to distinguish the explanation from alternatives. Validation may
accept bounded descriptive testing without asserting causality or profitability.
The attached implemented protocol defines supported features, time/adjustment rules,
missingness and reported units. Do not require future prices to exist before
registering a prospective test; unavailable future observations will be missing.
Reported means include false-signal cash opportunities and group by entry session.
Do not approve a falsification rule requiring unimplemented active-only statistics
or assert that groups selected by opposing conditions identify a causal effect.
Unverifiable claims need work. Acceptance means source/method review only, never
profitability validation. Return ResearchValidation JSON.
"""
    prompt = BASE + instructions + json.dumps(context, default=str, separators=(",", ":"))
    if len(prompt) > 27000:
        raise ValueError(
            "Validation batch too large; retain complete evidence and split into smaller research batches"
        )
    return prompt


def record_validation(store, result):
    from datetime import datetime, timedelta, timezone
    from urllib.parse import urlsplit
    from .experiments import Experiments

    draft = store.get("exploration_draft", {})
    hypotheses = draft.get("hypotheses", [])
    ids = [h["id"] for h in hypotheses]
    verdicts = [v["id"] for v in result["hypotheses"]]
    if (
        len(ids) != len(set(ids))
        or set(ids) != set(verdicts)
        or len(verdicts) != len(set(verdicts))
    ):
        raise ValueError("Validator must cover each draft hypothesis exactly once")
    sources = {s["url"]: s for s in draft.get("sources", [])}
    trial_ids = {t["id"] for t in store.get("historical_screen", {}).get("trials", [])}
    by_id = {v["id"]: v for v in result["hypotheses"]}
    catalogue = {c["id"]: c for c in store.get("research_catalogue", [])}
    approved_experiments = set()
    accepted_ids = set()
    now = datetime.now(timezone.utc)
    for h in hypotheses:
        verdict = by_id[h["id"]]
        citation_ok = all(
            url in sources and urlsplit(url).scheme == "https" and bool(urlsplit(url).hostname)
            for url in h["source_urls"]
        )
        try:
            dates_ok = all(
                timestamp(sources[url]["observed_at"]).tzinfo is not None
                and timestamp(sources[url]["observed_at"]) <= now + timedelta(minutes=5)
                for url in h["source_urls"]
                if url in sources
            )
        except (ValueError, TypeError, KeyError):
            dates_ok = False
        links_ok = set(h["screen_trial_ids"]) <= trial_ids
        checks = set(verdict.get("checked_source_urls", []))
        from .intelligence import observation_ids_valid

        local = h.get("evidence_basis", "external") in ("local_observation", "mixed")
        local_ok = not local or (
            observation_ids_valid(store, h.get("observation_ids", []), before=draft.get("at"))
            and bool(h.get("alternative_explanations"))
            and bool(h.get("predicted_outcome"))
            and verdict.get("method_check_status") == "reviewed"
        )
        independently_checked = (
            verdict.get("source_check_status") == "verified"
            and bool(h["source_urls"])
            and checks == set(h["source_urls"])
        )
        if h.get("evidence_basis") == "local_observation" and not h["source_urls"]:
            independently_checked = (
                verdict.get("source_check_status") == "not_applicable" and not checks
            )
        previous_card = catalogue.get(h["id"])
        linked = store.rows(
            "SELECT name FROM sqlite_master WHERE name='adaptive_contracts'"
        ) and store.rows(
            "SELECT id FROM adaptive_contracts WHERE json_extract(payload,'$.hypothesis_id')=?",
            (h["id"],),
        )
        if (
            previous_card
            and linked
            and any(
                previous_card.get(k) != h.get(k)
                for k in (
                    "branch",
                    "claim",
                    "mechanism",
                    "falsification",
                    "predicted_outcome",
                    "evidence_basis",
                )
            )
        ):
            store.event(
                "adaptive_contract_rejected",
                {
                    "id": h["id"],
                    "reason": "A tested hypothesis definition is immutable; use a new hypothesis/version ID for a changed claim",
                },
            )
            continue
        accepted = (
            verdict["verdict"] == "accepted_for_testing"
            and citation_ok
            and dates_ok
            and links_ok
            and independently_checked
            and local_ok
        )
        gate_issues = []
        if not citation_ok:
            gate_issues.append(
                "A cited URL is missing from the supplied evidence list or is not HTTPS."
            )
        if not dates_ok:
            gate_issues.append("A cited observation is dated in the future.")
        if not links_ok:
            gate_issues.append("A referenced historical trial does not exist.")
        if not independently_checked:
            gate_issues.append(
                "Independent primary-source checks are partial, unverified or missing. Reviewer attestations are not automated content authentication."
            )
        if not local_ok:
            gate_issues.append(
                "Local observations, pre-draft timing, alternatives, prediction or independent method review are missing."
            )
        state = (
            "reviewed_for_testing"
            if accepted
            else "needs_work"
            if verdict["verdict"] != "rejected"
            else "rejected"
        )
        card = {
            **h,
            "state": state,
            "review_reason": verdict["reason"]
            + (" Automated checks: " + " ".join(gate_issues) if gate_issues else ""),
            "reviewer_verdict": verdict["verdict"],
            "source_check_status": verdict.get("source_check_status", "unverified"),
            "method_check_status": verdict.get("method_check_status", "unreviewed"),
            "observation_provenance_verified": bool(local and local_ok),
            "checked_source_urls": sorted(checks),
            "automated_check_issues": gate_issues,
            "reviewed_at": utc_now(),
            "expires_at": (now + timedelta(days=30)).isoformat(),
            "sources": [sources[url] for url in h["source_urls"] if url in sources],
            "validation_scope": "Independent source/method review only; not demonstrated profitability",
        }
        # Preserve the complete review trail, rather than overwriting old evidence.
        store.memory_put(
            "research-card:" + h["id"] + ":" + now.isoformat(), "research_review", card
        )
        catalogue[h["id"]] = card
        if accepted:
            accepted_ids.add(h["id"])
            approved_experiments.update(h["experiment_ids"])
    accepted_current = {h["id"]: catalogue[h["id"]] for h in hypotheses if h["id"] in accepted_ids}
    from .adaptive_lab import AdaptiveLab

    adaptive = AdaptiveLab(store)
    for proposal in draft.get("adaptive_contracts", [])[:3]:
        card = accepted_current.get(proposal.get("hypothesis_id"))
        if (
            not card
            or card["branch"] != proposal.get("branch")
            or (
                card.get("method_check_status") != "reviewed"
                or not observation_ids_valid(
                    store, card.get("observation_ids", []), before=draft.get("at")
                )
            )
        ):
            store.event(
                "adaptive_contract_rejected",
                {
                    "id": proposal.get("id"),
                    "reason": "Current reviewed hypothesis, method and local observation linkage required",
                },
            )
            continue
        try:
            adaptive.register(proposal)
        except (ValueError, KeyError, TypeError):
            store.event(
                "adaptive_contract_rejected",
                {
                    "id": proposal.get("id"),
                    "reason": "Invalid, changed or duplicate prospective contract",
                },
            )
    registry = Experiments(store)
    for proposal in draft.get("experiments", []):
        if proposal["id"] in approved_experiments:
            try:
                registry.register(proposal)
            except (ValueError, KeyError, TypeError):
                store.event(
                    "experiment_rejected",
                    {"reason": "Reviewed exploration contract invalid or stale"},
                )
    store.set("research_catalogue", list(catalogue.values()))
    store.set("exploration_report", {**draft, "validation": result, "validated_at": utc_now()})
    # Research-generated shadow plans also require the method/source review. They
    # can NEVER enter the execution plans table or normal entry review queue.
    store.set(
        "exploration_shadow_plans",
        [
            p
            for p in draft.get("shadow_plans", [])
            if p.get("hypothesis_id") in accepted_current
            and accepted_current[p["hypothesis_id"]]["branch"] == p["branch"]
            and accepted_current[p["hypothesis_id"]]["free_data_feasibility"] == "ready"
            and p["branch"] != "options"
        ],
    )
    store.set("exploration_validated_draft", draft.get("revision"))
    store.event(
        "research_validated",
        {
            "summary": result["summary"],
            "accepted_for_testing": sum(
                c["state"] == "reviewed_for_testing" for c in catalogue.values()
            ),
            "not_profitability_validation": True,
        },
    )


def knowledge_context(store, *, max_chars=6500):
    """Explicit morning-loop handoff, with experiment evidence joined at retrieval."""
    now = datetime.now(ET)
    from .adaptive_lab import AdaptiveLab

    adaptive_trials = AdaptiveLab(store).summary()["trials"]
    cards = []
    for original in store.get("research_catalogue", []):
        if original["state"] != "reviewed_for_testing" or timestamp(original["expires_at"]) <= now:
            continue
        card = dict(original)
        card["source_check_status"] = original.get("source_check_status", "legacy_unattested")
        card["checked_source_urls"] = original.get("checked_source_urls", [])
        evidence = []
        for eid in original["experiment_ids"]:
            rows = store.rows("SELECT id,state,payload FROM experiments WHERE id=?", (eid,))
            if rows:
                e = rows[0]
                evidence.append(
                    {
                        "id": eid,
                        "state": e["state"],
                        "minimum_sessions": json.loads(e["payload"])["minimum_sessions"],
                        "minimum_samples": json.loads(e["payload"])["minimum_samples"],
                        "closed_samples": store.rows(
                            "SELECT count(*) AS n FROM shadow WHERE experiment=? AND state='closed'",
                            (eid,),
                        )[0]["n"],
                    }
                )
        card["forward_evidence"] = evidence
        card["adaptive_tests"] = [
            {
                k: trial[k]
                for k in (
                    "id",
                    "state",
                    "closed",
                    "closed_signals",
                    "closed_sessions",
                    "not_evaluable",
                    "cumulative",
                )
            }
            for trial in adaptive_trials
            if trial["hypothesis_id"] == original["id"]
        ]
        card["test_status"] = (
            "registered_test"
            if evidence or card["adaptive_tests"]
            else "reviewed_without_implemented_test"
        )
        card["evidence_level"] = (
            "forward_validated_filter"
            if any(e["state"] == "promoted" for e in evidence)
            else "reviewed_hypothesis"
        )
        if any(e["state"] == "rolled_back" for e in evidence):
            card["caution"] = (
                "A linked forward experiment was rolled back; do not treat its earlier promotion as current approval."
            )
        cards.append(card)
    compact_cards = []
    for c in cards[-12:]:
        compact_cards.append(
            {
                k: c[k]
                for k in (
                    "id",
                    "branch",
                    "family",
                    "claim",
                    "mechanism",
                    "falsification",
                    "free_data_feasibility",
                    "evidence_level",
                    "forward_evidence",
                    "review_reason",
                    "screen_trial_ids",
                    "caution",
                    "source_check_status",
                    "checked_source_urls",
                    "evidence_basis",
                    "observation_ids",
                    "alternative_explanations",
                    "predicted_outcome",
                    "method_check_status",
                    "adaptive_tests",
                    "test_status",
                )
                if k in c
            }
            | {"sources": [s["url"] for s in c["sources"][:2]]}
        )
        for key in ("claim", "mechanism", "falsification", "review_reason"):
            compact_cards[-1][key] = compact_cards[-1][key][:400]
    # Whole cards only: preserve valid structured context rather than truncating JSON.
    total_reviewed = len(compact_cards)
    while max_chars and len(dumps(compact_cards)) > max_chars and compact_cards:
        compact_cards.pop(0)
    return {
        "reviewed_research": compact_cards,
        "total_reviewed": total_reviewed,
        "omitted_for_context_budget": total_reviewed - len(compact_cards),
        "rejected_or_incomplete": [
            {"id": c["id"], "claim": c["claim"][:200], "reason": c["review_reason"][:250]}
            for c in store.get("research_catalogue", [])
            if c["state"] != "reviewed_for_testing"
        ][-6:],
        "rule": "Research review supports investigation only. Historical screening does not count as forward evidence. Use current sources and quotes for today's trades; acknowledge contradictions and unavailable data.",
    }
