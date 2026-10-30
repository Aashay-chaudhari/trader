from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime

from .store import utc_now

PUBLIC_EVENTS = {
    "research_probe_scheduled",
    "research_probe_started",
    "research_probe_completed",
    "research_probe_failed",
    "cohort_registered",
    "cohort_error",
    "research_audit_completed",
    "historical_screen",
    "exploration_completed",
    "research_validated",
    "fill",
    "order_submitted",
    "agent_task",
    "budget_skip",
    "notification_sent",
    "experiment_registered",
    "experiment_review",
    "strategy_promoted",
    "strategy_rolled_back",
    "maintenance_no_change",
    "maintenance_rejected",
    "maintenance_staged",
    "research_completed",
    "decision",
    "incident",
    "entry_blocked",
    "release",
    "startup",
    "supervisor_stopping",
    "supervisor_stopped",
    "daily_summary",
    "pulse",
    "period_review",
    "entry_cancellation_requested",
    "protection_repair",
}


def sanitize(value, config):
    if isinstance(value, dict):
        return {
            k: sanitize(v, config)
            for k, v in value.items()
            if not any(
                x in k.lower()
                for x in (
                    "secret",
                    "api_key",
                    "account_number",
                    "client_id",
                    "broker_id",
                    "worktree",
                    "thread_id",
                    "token_id",
                )
            )
        }
    if isinstance(value, list):
        return [sanitize(v, config) for v in value]
    if isinstance(value, str):
        for secret in (config.api_key, config.secret_key, config.ntfy_topic):
            if secret:
                value = value.replace(secret, "[redacted]")
        value = re.sub(r'(?i)(?:https?://)?ntfy\.sh/[^\s"<>]+', "[notification destination]", value)
        return value[:12000]
    return value


def snapshot(config, store):
    from .exploration import knowledge_context
    from .experiments import Experiments
    from .cohorts import ForwardLab, normalized_screen
    from .project import project_snapshot

    progress = Experiments(store).progress()
    try:
        watchdog = json.loads(
            (config.state_dir / "watchdog-state.json").read_text(encoding="utf-8-sig")
        )
    except (OSError, ValueError):
        watchdog = {}

    positions = store.rows("SELECT * FROM holdings")
    broker = {p["symbol"]: p for p in store.get("broker_positions", [])}
    for h in positions:
        p = broker.get(h["symbol"], {})
        h["market_value"] = float(p.get("market_value", h["cost"]))
        h["unrealized_pnl"] = h["market_value"] - h["cost"]
    branches = []
    for b in store.rows("SELECT * FROM branches"):
        b["equity"] = b["cash"] + sum(
            h["market_value"] for h in positions if h["branch"] == b["name"]
        )
        b["daily_pnl"] = b["equity"] - store.get(
            "sod:"
            + datetime.now()
            .astimezone(__import__("zoneinfo").ZoneInfo("America/New_York"))
            .date()
            .isoformat()
            + ":"
            + b["name"],
            10000,
        )
        b["total_pnl"] = b["equity"] - 10000
        b["drawdown"] = max(0, 1 - b["equity"] / b["high_water"])
        b["mode"] = "shadow" if b["name"] == "options" else store.get("mode", "research_shadow")
        branches.append(b)
    events = []
    for r in store.rows("SELECT * FROM events ORDER BY id DESC LIMIT 250"):
        if r["kind"] in PUBLIC_EVENTS:
            events.append({**r, "payload": json.loads(r["payload"])})
    plans = [
        {k: v for k, v in r.items() if k != "payload"} | {"plan": json.loads(r["payload"])}
        for r in store.rows("SELECT * FROM plans ORDER BY day DESC LIMIT 60")
    ]
    quota = store.get("quota", {})
    extra_cost = sum(r["notional"] for r in store.rows("SELECT notional FROM orders")) * 0.001
    return sanitize(
        {
            "schema_version": 2,
            "generated_at": utc_now(),
            "start_date": config.start_date,
            "mode": store.get("mode", "research_shadow"),
            "heartbeat": store.get("heartbeat"),
            "watchdog": {
                "checked_at": watchdog.get("checkedAt"),
                "incident": bool(watchdog.get("incident", False)),
                "last_restart": watchdog.get("lastRestart"),
                "service_owner": "systemd user service",
                "models_paused": (config.state_dir / "agent-pause.flag").exists(),
            },
            "status": store.get("status", "Preparing a new experiment"),
            "next_action": store.get("next_action"),
            "readiness": store.get("readiness", {}),
            "reconciliation_errors": store.get("reconciliation_errors", []),
            "calendar": store.get("calendar", {}),
            "branches": branches,
            "positions": positions,
            "orders": [
                {
                    "branch": r["branch"],
                    "symbol": r["symbol"],
                    "side": r["side"],
                    "qty": r["qty"],
                    "filled": r["filled"],
                    "status": r["status"],
                    "at": r["at"],
                }
                for r in store.rows("SELECT * FROM orders ORDER BY at DESC LIMIT 60")
            ],
            "equity": store.rows(
                "SELECT at,day,branch,value FROM equity WHERE id IN (SELECT max(id) FROM equity GROUP BY branch,substr(at,1,16)) ORDER BY id DESC LIMIT 1800"
            ),
            "brief": store.get("brief", {}),
            "project": project_snapshot(config, store),
            "forward_lab": ForwardLab(store).summary(),
            "official_calendar": store.get("official_calendar", {}),
            "pulses": store.get("pulses", [])[:10],
            "plans": plans,
            "events": events[:100],
            "experiments": [
                dict(r, payload=json.loads(r["payload"]), progress=progress.get(r["id"], {}))
                for r in store.rows("SELECT * FROM experiments")
            ],
            "shadow": [
                {
                    "experiment": r["experiment"],
                    "symbol": r["symbol"],
                    "branch": r["branch"],
                    "state": r["state"],
                    "result": json.loads(r["payload"]),
                }
                for r in store.rows("SELECT * FROM shadow LIMIT 200")
            ],
            "exploration": {
                "completed_sessions": len(store.get("exploration_sessions", [])),
                "sprint_sessions": 10,
                "max_parallel_per_branch": 6,
                "report": store.get("exploration_report", {}),
                "draft": {
                    k: v
                    for k, v in store.get("exploration_draft", {}).items()
                    if k in ("summary", "day", "revision")
                },
                "historical_screen": normalized_screen(store.get("historical_screen", {})),
                "knowledge": knowledge_context(store, max_chars=None),
            },
            "review": store.get("review", {}),
            "research_probes": store.get("research_probes", []),
            "period_reviews": [
                json.loads(r["value"])
                for r in store.rows(
                    "SELECT value FROM kv WHERE key LIKE 'weekly:%' OR key LIKE 'monthly:%' ORDER BY key DESC LIMIT 4"
                )
            ],
            "lessons": [
                dict(r, payload=json.loads(r["payload"]))
                for r in store.rows(
                    'SELECT layer,payload,at FROM memory WHERE layer="lesson" ORDER BY at DESC LIMIT 20'
                )
            ],
            "maintenance": store.get("maintenance_candidate"),
            "quota": quota,
            "usage": store.rows(
                "SELECT at,day,role,model,input_tokens,cached_tokens,output_tokens,quota_delta,coalesce(json_extract(payload,'$.state'),'completed') state FROM usage ORDER BY id DESC LIMIT 150"
            ),
            "budget": {
                "project_weekly_share": 80,
                "reserve": 20,
                "daily_call_ceiling": 24,
                "night_review_reserved_calls": 4,
                "attribution": "Task tokens measured; quota deltas include concurrent account activity.",
            },
            "execution_quality": {
                "additional_cost_allowance": extra_cost,
                "illustrative_equity_after_allowance": sum(b["equity"] for b in branches)
                - extra_cost,
                "basis": "Additional 10bp per executed side; illustrative, not actual fees or a live-fill simulation.",
            },
            "benchmarks": store.get("benchmarks", {}),
            "options_research": store.get("options_research", {}),
            "release": store.get("release", {}),
            "limitations": [
                "Paper results are not live returns.",
                "Free equities quotes cover IEX only.",
                "Options use indicative data and remain shadow-only.",
                "Shadow returns are assumptions, not broker fills.",
                "No strategy is proven on launch.",
                "Static dashboard may lag the local process.",
            ],
        },
        config,
    )


def export(config, store):
    target = config.root / "docs"
    target.mkdir(exist_ok=True)
    source = config.root / "src/agent_trader/runtime/web"
    index = (source / "index.html").read_text()
    for name in ("app.js", "style.css"):
        shutil.copyfile(source / name, target / name)
        version = hashlib.sha256((source / name).read_bytes()).hexdigest()[:12]
        index = index.replace('"' + name + '"', '"' + name + '?v=' + version + '"')
    # Version assets so a fresh snapshot cannot be paired with stale CDN scripts.
    (target / "index.html").write_text(index)
    (target / "data").mkdir(exist_ok=True)
    data = snapshot(config, store)
    encoded = json.dumps(data, indent=2, allow_nan=False)
    for secret in (config.api_key, config.secret_key, config.ntfy_topic):
        if secret and secret in encoded:
            raise ValueError("Private value found in dashboard export")
    with tempfile.NamedTemporaryFile(
        mode="w", dir=target / "data", suffix=".tmp", delete=False
    ) as handle:
        handle.write(encoded)
        temp = handle.name
    os.replace(temp, target / "data/lab.json")
    (target / ".nojekyll").touch()
    return data


def git_run(config, args, timeout=60):
    return subprocess.run(
        ["git", *args],
        cwd=config.root,
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "Never"},
    )


def publish(config, store):
    export(config, store)
    if not config.publish:
        return {"status": "local_only"}
    # Stage only sanitized generated site files. Never git add the runtime directory.
    result = git_run(
        config,
        [
            "add",
            "--",
            "docs/index.html",
            "docs/style.css",
            "docs/app.js",
            "docs/data/lab.json",
            "docs/.nojekyll",
        ],
    )
    if result.returncode:
        raise RuntimeError("Dashboard staging failed")
    paths = git_run(config, ["diff", "--cached", "--name-only"]).stdout.splitlines()
    if any(not p.startswith("docs/") for p in paths):
        raise RuntimeError("Unrelated staged files; publication postponed")
    if paths:
        result = git_run(config, ["commit", "-m", "[dashboard] local trading laboratory snapshot"])
        if result.returncode:
            raise RuntimeError("Dashboard commit failed")
    # Never force-push or reset user edits. Failed synchronization is retried later.
    binary = "/mnt/c/Windows/System32/wscript.exe"
    if os.path.exists(binary) and str(config.root).startswith("/mnt/c/"):
        # Windows credential helpers can allocate a console when called from WSL.
        # Keep the complete push/authentication chain inside the hidden GUI host.
        launcher = "C:\\" + str(config.root / "scripts/runtime/hidden-launch.vbs")[7:].replace(
            "/", "\\"
        )
        result = subprocess.run(
            [binary, "//B", "//NoLogo", launcher, "publish"],
            cwd=config.root,
            capture_output=True,
            text=True,
            timeout=80,
            env={**os.environ, "GCM_INTERACTIVE": "Never"},
        )
    else:
        result = git_run(config, ["push", "origin", "HEAD:main"])
    if result.returncode:
        raise RuntimeError("GitHub push failed; local trading remains independent")
    store.set("last_published", utc_now())
    return {"status": "pushed", "commit": git_run(config, ["rev-parse", "HEAD"]).stdout.strip()}
