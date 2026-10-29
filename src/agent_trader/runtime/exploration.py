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
    from .research import BASE

    return (
        BASE
        + "\nROLE: initial research sprint / hypothesis designer.\n"
        + json.dumps(
            {
                "day": day,
                "now": utc_now(),
                "brief": {
                    k: v
                    for k, v in store.get("brief", {}).items()
                    if k in ("summary", "regime", "unknowns")
                },
                "historical_screen": screen,
                "existing_experiments": store.rows("SELECT id,branch,state FROM experiments"),
                "instructions": "Use up to 12 focused live web searches, primary research and official sources. "
                "Investigate distinct families: momentum/breakout, mean reversion/pullbacks, earnings/catalysts, macro/rates/regimes, "
                "and options volatility/event hypotheses (options research only). Explain economic mechanism, contrary evidence, "
                "free-data feasibility, costs, failure modes and a falsification test. Historical screens are exploratory, "
                "use current-universe adjusted IEX bars, and are not evidence of an intraday catalyst edge. Report losers too. "
                "Give a day-one research shortlist, not a claim of proven profitability. Propose at most six experiment contracts "
                "per equity branch, diversify mechanisms rather than many parameter tweaks. Already registered contracts are immutable. "
                "Executable exact_change filters: require_risk_on, avoid_risk_off, higher_confidence_075, higher_confidence_085, reward_risk_2. "
                "Other ideas stay proposed until supported by tested code. Minimum forward sessions20 and samples30 remain. "
                "Create up to 16 diversified, dated shadow_plans only when fresh levels and event evidence exist; "
                "these never authorize orders. No options price plans. Plans need narrow observable entries and concrete exits. "
                "At night or with stale quotes, leave shadow_plans empty. Include explicit uncertainty and next tests. "
                "Return ExplorationReport JSON. Keep prose concise.",
            },
            default=str,
        )[:24000]
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
    from .research import BASE

    draft = store.get("exploration_draft", {})
    context = {
        "revision": draft.get("revision"),
        "hypotheses": draft.get("hypotheses", []),
        "sources": draft.get("sources", []),
        "historical_screen": store.get("historical_screen", {}),
    }
    instructions = """
ROLE: independent research validator, not the original researcher.
Use up to 4 live searches to check primary sources and important counterevidence.
For EVERY hypothesis return exactly one verdict. Accept for testing only when cited
evidence supports the mechanism, falsification is concrete, and free-data limits
are explicit. Reject fabricated citations and historical claims unsupported by the
attached screen. Screen metrics are horizon returns averaged across unit opportunities,
grouped by entry session; five-session swing returns are NOT daily portfolio returns.
Do not accept that unit confusion, annualization, or fabricated executable fills.
Unverifiable claims need work. Acceptance means source/method review only, never
profitability validation. Return ResearchValidation JSON.
"""
    return BASE + instructions + json.dumps(context, default=str, separators=(",", ":"))


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
    now = datetime.now(timezone.utc)
    for h in hypotheses:
        verdict = by_id[h["id"]]
        citation_ok = all(
            url in sources and urlsplit(url).scheme == "https" and bool(urlsplit(url).hostname)
            for url in h["source_urls"]
        )
        dates_ok = all(
            timestamp(sources[url]["observed_at"]) <= now + timedelta(minutes=5)
            for url in h["source_urls"]
            if url in sources
        )
        links_ok = set(h["screen_trial_ids"]) <= trial_ids
        accepted = (
            verdict["verdict"] == "accepted_for_testing" and citation_ok and dates_ok and links_ok
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
            approved_experiments.update(h["experiment_ids"])
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
    ready_branches = {
        c["branch"]
        for c in catalogue.values()
        if c["state"] == "reviewed_for_testing" and c["free_data_feasibility"] == "ready"
    }
    store.set(
        "exploration_shadow_plans",
        [
            p
            for p in draft.get("shadow_plans", [])
            if p["branch"] in ready_branches and p["branch"] != "options"
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
    cards = []
    for original in store.get("research_catalogue", []):
        if original["state"] != "reviewed_for_testing" or timestamp(original["expires_at"]) <= now:
            continue
        card = dict(original)
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
