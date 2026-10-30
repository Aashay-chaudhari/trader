"""Human-facing project account, built from recorded evidence rather than optimism."""

from __future__ import annotations

import json
from datetime import datetime

from .config import ET
from .engine import timestamp
from .store import utc_now

RESOURCES = [
    {
        "title": "Alpaca IEX / indicative options",
        "url": "https://docs.alpaca.markets/docs/about-market-data-api",
        "use": "Quotes, daily bars and broker calendar; free IEX only. Indicative options remain research-only.",
        "state": "integrated",
        "limit": "Single exchange; not consolidated prices or firm options liquidity.",
    },
    {
        "title": "BEA release calendar",
        "url": "https://www.bea.gov/news/schedule/icalendar",
        "use": "Official dated GDP, income/outlays and other BEA release events.",
        "state": "integrated calendar",
        "limit": "Calendar dates are not consensus forecasts or economic surprises.",
    },
    {
        "title": "BLS official schedule",
        "url": "https://www.bls.gov/schedule/news_release/",
        "use": "Inflation, employment and wage release dates.",
        "state": "feed checked; web verification when blocked",
        "limit": "Direct feed may reject requests. Missing coverage stays explicit; no paid proxy.",
    },
    {
        "title": "Federal Reserve FOMC calendar",
        "url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
        "use": "Meeting dates, statements, minutes and official policy context.",
        "state": "research reference",
        "limit": "The agent must verify timing and changes; not provided by the BEA/BLS collector.",
    },
    {
        "title": "FRED / ALFRED",
        "url": "https://fred.stlouisfed.org/",
        "use": "Treasury yields, real rates, credit and volatility context.",
        "state": "daily series integrated",
        "limit": "Daily/delayed. Revisions require vintage data for point-in-time backtests; current CSV is not vintage history.",
    },
    {
        "title": "SEC EDGAR APIs",
        "url": "https://www.sec.gov/about/developer-resources",
        "use": "Public submissions and XBRL fundamentals; primary filings for corporate research.",
        "state": "web reference; direct connector deferred",
        "limit": "Declared user agent and fair access required. Filings are not a complete future earnings calendar.",
    },
    {
        "title": "Company investor relations",
        "url": "https://www.sec.gov/edgar/search/",
        "use": "Use issuer IR releases and filings to verify earnings and guidance.",
        "state": "research workflow",
        "limit": "Missing exact timing stays unknown; generic search snippets are not confirmed earnings schedules.",
    },
]

DECISIONS = [
    {
        "date": "2026-10-29",
        "title": "Free data, with explicit missingness",
        "why": "Combine primary public calendars, filings and web research with broker data; never invent a paid-quality quote from a web result.",
        "evidence": "Calendar status, source timestamps, IEX/indicative labels.",
        "status": "active",
    },
    {
        "date": "2026-10-29",
        "title": "Recovery is separate from the trader",
        "why": "The first session was missed after the loop stopped at 08:12 ET. A background service and independent hidden Windows watchdog now own recovery.",
        "evidence": "Interrupt, crash and stopped-service drills; a full unattended session is still a separate gate.",
        "status": "active",
    },
    {
        "date": "2026-10-29",
        "title": "Research review does not certify an edge",
        "why": "A source-supported mechanism can be worth testing without being profitable. Reviewed cards and forward evidence carry different labels.",
        "evidence": "The 19:00 check completed but its reviewer held both hypotheses.",
        "status": "active",
    },
    {
        "date": "2026-10-29",
        "title": "Observe fixed signals without forcing orders",
        "why": "Waiting for model-generated price plans can starve research. Twelve preregistered cohorts can collect fresh paired quote observations across the liquid universe.",
        "evidence": "Pre-open signal freeze; first observed quotes; missing exits are not evaluable. No broker allocation or automatic promotion.",
        "status": "active; forward collection awaits market",
    },
    {
        "date": "2026-10-29",
        "title": "Keep historical units attached to the numbers",
        "why": "Five-session unit-opportunity returns were repeatedly mistaken for daily portfolio returns. Derived evidence now names the horizon and aggregation explicitly.",
        "evidence": "Frozen data/hash retained; historical screens never count toward forward promotion.",
        "status": "active",
    },
    {
        "date": "2026-10-29",
        "title": "Bound role context and finish within tool budgets",
        "why": "A shared thread grew beyond 100,000 cached input tokens and quick checks hit tool limits. Separate role context, bounded rotation, compact packets and soft budget notices reduce avoidable failure paths.",
        "evidence": "Task usage/context-rotation records. Decision-quality and token savings still require matched forward evaluation.",
        "status": "active; benefit under evaluation",
    },
]

AUTOMATIONS = [
    {
        "when": "Continuously / 30 seconds",
        "work": "Broker reconciliation, protection, triggers and heartbeat",
        "owner": "Python background service",
        "condition": "Calendar and broker session must agree; fresh inputs required.",
    },
    {
        "when": "Every 2 minutes",
        "work": "Independent health check, recovery and failure/recovery notifications",
        "owner": "Hidden Windows watchdog",
        "condition": "Windows signed in, powered and connected.",
    },
    {
        "when": "07:45 ET",
        "work": "Morning startup notification",
        "owner": "Supervisor",
        "condition": "Trading session; late starts report their actual time.",
    },
    {
        "when": "08:15 ET",
        "work": "Market brief, primary-source research and reviewed knowledge retrieval",
        "owner": "Research role",
        "condition": "Available account allowance, dated evidence and complete schema.",
    },
    {
        "when": "08:35–09:15 ET",
        "work": "Initial ten-morning exploration, separate review and refreshed brief",
        "owner": "Research / reviewer roles",
        "condition": "Bounded daily/weekly budget; source review is not performance validation.",
    },
    {
        "when": "From 09:32 ET",
        "work": "One-share paper fill/exit gate, once until verified",
        "owner": "Python execution check",
        "condition": "Regular session, reconciliation, fresh quote and existing risk gates.",
    },
    {
        "when": "09:35–10:00 ET",
        "work": "Observe preregistered fixed signal cohorts",
        "owner": "Deterministic research lab",
        "condition": "Signals frozen before open; no orders or backfilled entries.",
    },
    {
        "when": "Hourly; 11:00 / 13:00 / 14:30 ET",
        "work": "Position review and material-event checks",
        "owner": "Decision / light research roles",
        "condition": "Live positions and due checkpoints; Python protection remains independent.",
    },
    {
        "when": "12 minutes before actual close",
        "work": "Flatten intraday positions and observe due cohort exits",
        "owner": "Python / broker calendar",
        "condition": "Early closes honored; confirmed fills and missing exits reported.",
    },
    {
        "when": "After close: +10 / +15 / +35 minutes",
        "work": "Results, retrospective and controlled maintenance",
        "owner": "Supervisor / review / maintenance",
        "condition": "Actual records only. Broader code changes remain proposals.",
    },
    {
        "when": "Every ~15 minutes",
        "work": "Sanitized snapshot → GitHub Pages",
        "owner": "Publisher / Actions",
        "condition": "Publishing can lag; GitHub does not own broker execution.",
    },
]

REPO_MAP = [
    {
        "label": "Operating loop",
        "path": "src/agent_trader/runtime/supervisor.py",
        "purpose": "Calendar, jobs, independent model worker, broker checks and closing.",
    },
    {
        "label": "Execution kernel",
        "path": "src/agent_trader/runtime/engine.py",
        "purpose": "Paper-only orders, branch ownership, risk, fills and reconciliation.",
    },
    {
        "label": "Research and knowledge",
        "path": "src/agent_trader/runtime/research.py",
        "purpose": "Public evidence, calendars, prompt packets and morning knowledge handoff.",
    },
    {
        "label": "Parallel signal lab",
        "path": "src/agent_trader/runtime/cohorts.py",
        "purpose": "Preregistered forward observations with explicit units and missingness.",
    },
    {
        "label": "Experiments and code changes",
        "path": "src/agent_trader/runtime/experiments.py",
        "purpose": "Forward challenger evaluation, promotion and rollback; isolated maintenance candidates.",
    },
    {
        "label": "Model harness",
        "path": "src/agent_trader/runtime/agent.py",
        "purpose": "Existing subscription, model routing, task limits and bounded role context.",
    },
    {
        "label": "Recovery and operator guide",
        "path": "SYSTEM_GUIDE.md",
        "purpose": "Hidden Windows host/watchdog, systemd, probes and recovery procedures.",
    },
    {
        "label": "Persistent vision",
        "path": "REFACTOR_SCOPE.md",
        "purpose": "Capital, free-only constraints, learning rules and research boundaries.",
    },
]


def session_coverage(store, now=None):
    now = (now or datetime.now(ET)).astimezone(ET)
    started = store.get("coverage_tracking_started")
    records = []
    for row in store.rows("SELECT key,value FROM kv WHERE key LIKE 'calendar:____-__-__'"):
        day = row["key"].split(":", 1)[1]
        cal = json.loads(row["value"])
        if not cal or day > now.date().isoformat():
            continue
        opened = datetime.fromisoformat(day + "T" + cal[0]["open"]).replace(tzinfo=ET)
        closed = datetime.fromisoformat(day + "T" + cal[0]["close"]).replace(tzinfo=ET)
        expected = max(1, int((closed - opened).total_seconds() // 300))
        slots = {
            r["slot"]
            for r in store.rows(
                "SELECT slot FROM session_health WHERE day=? AND broker_confirmed=1", (day,)
            )
            if 0 <= r["slot"] < expected
        }
        bounded = sorted({-1, expected, *slots})
        max_gap = max(b - a - 1 for a, b in zip(bounded, bounded[1:])) * 5
        eligible = bool(started and timestamp(started) <= opened and now >= closed)
        complete = eligible and len(slots) / expected >= 0.95 and max_gap <= 10
        records.append(
            {
                "day": day,
                "recorded_slots": len(slots),
                "expected_slots": expected,
                "observed_fraction": len(slots) / expected,
                "whole_session_evaluable": eligible,
                "complete_observed_session": complete,
                "maximum_unobserved_gap_minutes": max_gap,
                "state": "observed_complete"
                if complete
                else "incomplete"
                if eligible
                else "not_fully_instrumented_or_in_progress",
            }
        )
    return {
        "tracking_started": started,
        "complete_sessions": sum(r["complete_observed_session"] for r in records),
        "sessions": sorted(records, key=lambda r: r["day"], reverse=True)[:10],
        "definition": "Five-minute slots after broker-session confirmation; at least 95% and no gap above ten minutes across a fully instrumented completed session. Not proof of order execution.",
    }


def project_snapshot(config, store):
    fills = store.rows("SELECT count(*) n FROM orders WHERE filled>0")[0]["n"]
    closed_filter = store.rows("SELECT count(*) n FROM shadow WHERE state='closed'")[0]["n"]
    closed_cohort = store.rows("SELECT count(*) n FROM cohort_observations WHERE state='closed'")[
        0
    ]["n"]
    reviewed = sum(
        c["state"] == "reviewed_for_testing" for c in store.get("research_catalogue", [])
    )
    promoted = store.rows("SELECT count(*) n FROM experiments WHERE state='promoted'")[0]["n"]
    coverage = session_coverage(store)
    ready = store.get("readiness", {})
    missed = bool(store.get("missed_session_recorded:2026-10-29"))
    assessment = (
        "No measured trading edge. The system is still collecting operational and forward evidence."
        if not fills
        else "Paper execution has begun. Returns and isolated winning trades do not yet establish a repeatable net edge."
    )
    if missed:
        assessment += " October 29 was an operationally missed session; premarket research and recovery drills do not count as a trading day."
    return {
        "as_of": utc_now(),
        "title": "Operational progress. Profitability unproven.",
        "assessment": assessment,
        "assessment_basis": "A computed operating assessment, not subjective feelings or a probability of future profitability.",
        "stage": "operational_validation"
        if not ready.get("execution_verified")
        else "forward_paper_evidence",
        "evidence": {
            "filled_orders": fills,
            "reviewed_cards": reviewed,
            "closed_filter_observations": closed_filter,
            "closed_cohort_observations": closed_cohort,
            "promoted_filters": promoted,
            "complete_observed_sessions": coverage["complete_sessions"],
        },
        "coverage": coverage,
        "milestones": [
            {
                "name": "Independent recovery",
                "state": "drills_passed"
                if all(
                    store.get("release", {}).get("recovery_drills", {}).get(k)
                    for k in ("interrupt", "crash", "independent_watchdog_seconds")
                )
                else "pending",
                "detail": "Interrupt, crash and stopped-service recovery are separate from a whole unattended session.",
            },
            {
                "name": "Reliable market-session coverage",
                "state": "observed" if coverage["complete_sessions"] else "not_demonstrated",
                "detail": str(coverage["complete_sessions"])
                + " completed sessions satisfy the recorded coverage rule.",
            },
            {
                "name": "Reusable research",
                "state": "reviewed_for_testing" if reviewed else "pending",
                "detail": str(reviewed)
                + " cards passed source/method review. None is certified profitable by that review.",
            },
            {
                "name": "Broker fill/exit verification",
                "state": "passed" if ready.get("execution_verified") else "pending",
                "detail": "The market-open one-share paper gate has its own explicit receipt.",
            },
            {
                "name": "Forward net expectancy",
                "state": "collecting"
                if closed_filter + closed_cohort
                else "no_completed_observations",
                "detail": "Paired observations, costs, correlation and multiple testing matter. Historical screens cannot satisfy this stage.",
            },
            {
                "name": "Real-money readiness",
                "state": "outside_this_release",
                "detail": "No live endpoint or automatic paper-to-live switch is implemented.",
            },
        ],
        "agenda": [
            {
                "question": "Can the unattended loop cover a complete session?",
                "test": "Record broker-confirmed five-minute coverage slots; retain missed periods.",
                "next": "Observe the next fully instrumented session.",
            },
            {
                "question": "Do fixed reversal/continuation rules survive observed costs?",
                "test": "Run all twelve forward cohorts on the same frozen universe; preserve losses and abstentions.",
                "next": "Capture the first eligible quote window; no forced trades.",
            },
            {
                "question": "Does event context change a decision worth changing?",
                "test": "Use official calendar coverage plus source-checked Fed/earnings research; missing timing stays unknown.",
                "next": "Compare explicit event-aware hypotheses, not extra searches alone.",
            },
            {
                "question": "Does bounded role context improve useful work per token?",
                "test": "Compare matched role tasks, validity, sources and input/cache usage; do not infer causality from one probe.",
                "next": "Accumulate role-level measurements before promoting further routing changes.",
            },
        ],
        "decisions": DECISIONS,
        "automations": AUTOMATIONS,
        "resources": RESOURCES,
        "repo_map": REPO_MAP,
        "research_audit": store.get("research_audit", {}),
        "limits": [
            "No probability-of-profitability score is supportable yet.",
            "More tokens, sources or agents do not substitute for measured forward outcomes.",
            "Public calendars do not supply complete earnings surprises, consolidated quotes or firm options execution.",
            "Current historical universe and adjusted data are not a point-in-time backtest universe.",
        ],
    }
