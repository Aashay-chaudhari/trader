"""Isolated operational research checks. No execution engine or order methods."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

from .agent import run_task
from .broker import Broker
from .config import Config, ET
from .exploration import (
    exploration_prompt,
    record_report,
    record_validation,
    validation_prompt,
    knowledge_context,
)
from .models import Brief, ExplorationReport, ResearchValidation
from .notify import notify
from .research import market_packet, research_prompt
from .store import Store, dumps, utc_now


class ResearchData:
    def __init__(self, config):
        self._broker = Broker(config)

    def snapshots(self, symbols):
        return self._broker.snapshots(symbols)

    def bars(self, symbols, days=80):
        return self._broker.bars(symbols, days)

    def option_chain(self, symbol):
        return self._broker.option_chain(symbol)


def update_summary(store, entry):
    with store.transaction():
        entries = [x for x in store.get("research_probes", []) if x["id"] != entry["id"]]
        store.set("research_probes", [entry, *entries][:10])


def run_probe(config, run_id, kind="full", quick=False, scheduled_for=None):
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,80}", run_id):
        raise ValueError("Invalid probe ID")
    live = Store(config.state_dir / "trader.sqlite3")
    key = "research-probe:" + run_id
    prior = next((x for x in live.get("research_probes", []) if x["id"] == run_id), {})
    if not live.job_start(key):
        live.close()
        return prior
    result = {
        "id": run_id,
        "kind": kind,
        "state": "running",
        "scheduled_for": scheduled_for or prior.get("scheduled_for"),
        "started_at": utc_now(),
        "orders_authorized": False,
    }
    update_summary(live, result)
    live.event(
        "research_probe_started",
        {
            "summary": "Isolated " + kind + " research check started; no orders authorized.",
            **result,
        },
    )
    notify(
        config,
        live,
        key + ":start",
        "Trader - research check started",
        "Isolated " + kind + " run started. This check cannot place orders.",
    )
    directory = config.state_dir / "probes" / run_id
    directory.mkdir(parents=True, exist_ok=True)
    scratch = Store(directory / "research.sqlite3")
    try:
        for name in ("historical_screen", "research_catalogue", "brief", "market_packet"):
            scratch.set(name, live.get(name, {} if name != "research_catalogue" else []))
        for row in live.rows("SELECT * FROM experiments"):
            scratch.db.execute(
                "INSERT OR IGNORE INTO experiments VALUES(?,?,?,?,?)",
                tuple(row[k] for k in ("id", "branch", "state", "payload", "at")),
            )
        day = datetime.now(ET).date().isoformat()
        output = {}
        if kind in ("research", "full"):
            packet = market_packet(ResearchData(config), scratch)
            prompt = (
                research_prompt(day, packet, scratch).replace(
                    "Use at most 3 focused live searches and 3 source checks (6 web actions total)",
                    "Use at most two live search requests and two page checks (four web actions total)",
                )
                + "\nOPERATIONAL CHECK: return plans=[]; no trades or price plans. Cover verified current/next-session events. Keep each prose section under 500 characters."
            )
            brief = run_task(
                config,
                "probe_research",
                prompt,
                Brief,
                config.research_model,
                "medium" if quick else "high",
                day,
                searches=6 if quick else 8,
                scope=run_id,
            )
            if brief["plans"]:
                raise ValueError("Research check returned execution plans")
            scratch.set("brief", brief)
            output["brief"] = brief
            result["research_sources"] = len(brief["sources"])
        if kind in ("hypotheses", "full"):
            screen = scratch.get("historical_screen")
            if not screen:
                raise ValueError("Frozen historical screen is required")
            prompt = (
                exploration_prompt(day, scratch, screen).replace(
                    "Use at most 5 focused searches and 5 source checks (10 web actions total)",
                    "Use at most one live search and two page checks (three web actions total)",
                )
                + "\nOPERATIONAL CHECK: exactly two concise hypotheses, experiments=[], shadow_plans=[]. Use existing screened evidence and primary sources; no new executable contracts. Keep the response compact."
            )
            report = run_task(
                config,
                "probe_hypotheses",
                prompt,
                ExplorationReport,
                config.research_model,
                "medium" if quick else "high",
                day,
                searches=5 if quick else 8,
                scope=run_id,
            )
            if report["experiments"] or report["shadow_plans"]:
                raise ValueError("Hypothesis check returned operational changes")
            record_report(scratch, report, day, morning=False)
            reviewed = run_task(
                config,
                "probe_validation",
                validation_prompt(scratch).replace(
                    "Use up to 4 live searches",
                    "Use at most one live search and two page checks (three web actions total)",
                ),
                ResearchValidation,
                config.research_model,
                "medium",
                day,
                searches=5 if quick else 6,
                scope=run_id,
            )
            record_validation(scratch, reviewed)
            ids = {h["id"] for h in report["hypotheses"]}
            eligible = [
                h["id"]
                for h in knowledge_context(scratch, max_chars=None)["reviewed_research"]
                if h["id"] in ids
            ]
            handoff = research_prompt(day, {"market": {}}, scratch)
            if not all(identifier in handoff for identifier in eligible):
                raise ValueError("Reviewed hypothesis missing from morning handoff")
            output.update({"hypotheses": report, "validation": reviewed})
            result.update(
                {
                    "hypotheses": len(report["hypotheses"]),
                    "reviewed_for_testing": len(eligible),
                    "morning_handoff_verified": bool(eligible),
                    "handoff_result": "reviewed_cards_retrieved"
                    if eligible
                    else "no_cards_approved",
                }
            )
        (directory / "report.json").write_text(dumps(output))
        result.update({"state": "passed", "completed_at": utc_now()})
        update_summary(live, result)
        live.job_end(key, True, result)
        live.event(
            "research_probe_completed",
            {
                "summary": "Isolated research check passed: data, inference and schema validation; no orders authorized.",
                **result,
            },
        )
        notify(
            config,
            live,
            key + ":done",
            "Trader - research check passed",
            f"{run_id}: {result.get('research_sources', 0)} brief sources; {result.get('hypotheses', 0)} hypotheses; {result.get('reviewed_for_testing', 0)} eligible for testing. Production plans and knowledge unchanged.",
        )
        return result
    except Exception as exc:
        result.update(
            {"state": "failed", "completed_at": utc_now(), "error_type": type(exc).__name__}
        )
        update_summary(live, result)
        live.job_end(key, False, result)
        live.event(
            "research_probe_failed",
            {
                "summary": "Isolated research check failed ("
                + type(exc).__name__
                + "); production trading state untouched.",
                **result,
            },
        )
        notify(
            config,
            live,
            key + ":failed",
            "Trader - research check failed",
            run_id
            + " failed ("
            + type(exc).__name__
            + "). Production plans and knowledge unchanged.",
            urgent=True,
        )
        raise
    finally:
        scratch.close()
        live.close()


def schedule(config, run_id, when):
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,80}", run_id) or when.tzinfo is None:
        raise ValueError("Valid ID and timezone-aware time required")
    when = when.astimezone(ET)
    name = "agent-trader-probe-" + run_id
    unit_dir = Path.home() / ".config/systemd/user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    service = f"""[Unit]
Description=Isolated ad hoc Trader research check
[Service]
Type=oneshot
WorkingDirectory={config.root}
ExecStart={config.root}/.venv/bin/python -m agent_trader.runtime.probe --id {run_id} --kind full
TimeoutStartSec=35min
StandardOutput=append:{config.state_dir}/probe-scheduled.log
StandardError=append:{config.state_dir}/probe-scheduled.log
"""
    timer = f"""[Unit]
Description=One-time ad hoc Trader research check
[Timer]
OnCalendar={when.strftime("%Y-%m-%d %H:%M:%S")} America/New_York
AccuracySec=1s
Persistent=true
Unit={name}.service
[Install]
WantedBy=timers.target
"""
    (unit_dir / (name + ".service")).write_text(service)
    (unit_dir / (name + ".timer")).write_text(timer)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", name + ".timer"], check=True)
    store = Store(config.state_dir / "trader.sqlite3")
    entry = {
        "id": run_id,
        "kind": "full",
        "state": "scheduled",
        "scheduled_for": when.isoformat(),
        "orders_authorized": False,
    }
    update_summary(store, entry)
    store.event(
        "research_probe_scheduled",
        {"summary": "Ad hoc non-trading research scheduled for " + when.isoformat(), **entry},
    )
    store.close()
    return entry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", required=True)
    parser.add_argument("--kind", choices=("research", "hypotheses", "full"), default="full")
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--schedule-at")
    args = parser.parse_args()
    config = Config.load()
    result = (
        schedule(config, args.id, datetime.fromisoformat(args.schedule_at))
        if args.schedule_at
        else run_probe(config, args.id, args.kind, args.quick)
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
