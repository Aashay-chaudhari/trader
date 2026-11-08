from __future__ import annotations

import json
import hashlib
import math
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from contextlib import contextmanager

from .store import utc_now

PUBLIC_PATHS = (
    "docs/index.html", "docs/style.css", "docs/app.js", "docs/data/lab.json", "docs/.nojekyll",
)

PUBLIC_EVENTS = {
    "adaptive_registered",
    "adaptive_contract_rejected",
    "execution_check",
    "operational_review",
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
    "agent_task_failed",
    "accounting_refreshed",
    "fee_booked",
    "research_work_analyzed",
    "research_work_reviewed",
    "options_coverage_registered",
    "options_coverage_captured",
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


@contextmanager
def _read_snapshot(store):
    """Own only a new deferred read scope; never finish the caller's transaction."""
    connection = store.db
    owned = not connection.in_transaction
    query_only = connection.execute("PRAGMA query_only").fetchone()[0]
    original_error = None
    try:
        connection.execute("PRAGMA query_only=ON")
        if owned:
            connection.execute("BEGIN")
        yield
    except BaseException as exc:
        original_error = exc
        raise
    finally:
        cleanup_errors = []
        try:
            if owned and connection.in_transaction:
                connection.execute("ROLLBACK")
        except Exception as cleanup_error:
            cleanup_errors.append(cleanup_error)
        try:
            connection.execute("PRAGMA query_only=" + str(int(query_only)))
        except Exception as cleanup_error:
            cleanup_errors.append(cleanup_error)
        if cleanup_errors:
            primary = original_error or cleanup_errors[0]
            for cleanup_error in cleanup_errors:
                primary.add_note("Snapshot cleanup failed: " + type(cleanup_error).__name__)
            if original_error is None:
                raise primary


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _complete_sum(values):
    values = list(values)
    return _number(sum(values)) if all(value is not None for value in values) else None


def snapshot(config, store):
    with _read_snapshot(store):
        return _snapshot(config, store)


def _snapshot(config, store):
    from .exploration import knowledge_context
    from .experiments import Experiments
    from .cohorts import ForwardLab, normalized_screen
    from .project import project_snapshot
    from .intelligence import objective_scorecard, observation_context
    from .adaptive_lab import AdaptiveLab
    from .budget import usage_policy
    from .research_work import public_summary
    from .options_coverage import public_summary as options_coverage_summary
    from .accounting import accounting_summary
    from .engine import current_execution_verified
    from .operational_session import assess_evidence

    progress = Experiments(store).progress()
    input_packet = store.get("market_packet", {})
    daily_validation = input_packet.get("daily_input_validation") or {}
    input_quality = {
        "observed_at": input_packet.get("observed_at"),
        "acquisition_interval": {
            key: input_packet.get("acquisition_interval", {}).get(key)
            for key in ("started_at", "completed_at", "crossed_et_date", "crossed_regular_open", "crossed_regular_close")
        },
        "state": daily_validation.get("state", "legacy_or_unversioned"),
        **{key: daily_validation[key] for key in (
            "version", "expected_previous_session", "field_missing_counts", "calendar_error", "collection_error",
        ) if key in daily_validation},
        "source": {key: daily_validation.get("source", {}).get(key)
                   for key in ("feed", "adjustment", "timeframe")},
        "scope": "Calendar-linked feature availability, not independent provider-price verification. Earlier packets retain their original validation scope.",
    }
    try:
        watchdog = json.loads(
            (config.state_dir / "watchdog-state.json").read_text(encoding="utf-8-sig")
        )
    except (OSError, ValueError):
        watchdog = {}

    generated_at = utc_now()
    session_proof = store.get("operational_session")
    operational_session = assess_evidence(session_proof, datetime.fromisoformat(generated_at)).summary()
    proof = session_proof if isinstance(session_proof, dict) else {}
    operational_session["receipts"] = {
        source: {key: receipt.get(key) for key in ("sha256", "requested_at", "received_at")}
        for source in ("calendar", "clock")
        if isinstance(receipt := proof.get(source + "_receipt"), dict)
    }
    operational_session["scope"] = "Session evidence reassessed at snapshot time; not a guarantee of current execution readiness."
    day = datetime.fromisoformat(generated_at).astimezone(
        __import__("zoneinfo").ZoneInfo("America/New_York")
    ).date().isoformat()
    scorecard = objective_scorecard(store, generated_at)
    reconciled = scorecard["portfolio"]["reconciled"]
    positions = store.rows("SELECT * FROM holdings")
    broker = {p["symbol"]: p for p in store.get("broker_positions", [])}
    for h in positions:
        p = broker.get(h["symbol"], {})
        value, quantity = _number(p.get("market_value")), _number(p.get("qty"))
        valid = reconciled and value is not None and value >= 0 and quantity is not None and abs(quantity - h["qty"]) <= 1e-6
        h["market_value"] = value if valid else None
        h["unrealized_pnl"] = _number(value - h["cost"]) if valid else None
        h["valuation_status"] = "reconciled_broker_mark" if valid else "unavailable"
    branches = []
    for b in store.rows("SELECT * FROM branches"):
        market_value = _complete_sum(
            h["market_value"] for h in positions if h["branch"] == b["name"]
        )
        b["equity"] = _number(b["cash"] + market_value) if market_value is not None else None
        b["start_of_day_equity"] = _number(store.get(f"sod:{day}:{b['name']}"))
        b["daily_pnl"] = _number(b["equity"] - b["start_of_day_equity"]) if b["equity"] is not None and b["start_of_day_equity"] is not None else None
        b["total_pnl"] = _number(b["equity"] - 10000) if b["equity"] is not None else None
        peak_ratio = _number(b["equity"] / b["high_water"]) if b["equity"] is not None and b["high_water"] > 0 else None
        b["drawdown"] = max(0, 1 - peak_ratio) if peak_ratio is not None else None
        b["valuation_status"] = "ledger_estimate" if b["equity"] is not None else "unavailable"
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
    account = store.get("account", {})
    ledger_equity = _complete_sum(b["equity"] for b in branches)
    broker_equity = _number(account.get("equity"))
    difference = _number(broker_equity - ledger_equity) if broker_equity is not None and ledger_equity is not None else None
    notional = _complete_sum(_number(r["notional"]) for r in store.rows("SELECT notional FROM orders"))
    extra_cost = notional * 0.001 if notional is not None else None
    return sanitize(
        {
            "schema_version": 2,
            "generated_at": generated_at,
            "start_date": config.start_date,
            "mode": store.get("mode", "research_shadow"),
            "heartbeat": store.get("heartbeat"),
            "watchdog": {
                "checked_at": watchdog.get("checkedAt"),
                "incident": bool(watchdog.get("incident", False)),
                "last_restart": watchdog.get("lastRestart"),
                "service_owner": "systemd user service",
                "models_paused": (config.state_dir / "agent-pause.flag").exists(),
                "maintenance": (config.state_dir / "maintenance.flag").exists(),
            },
            "status": store.get("status", "Preparing a new experiment"),
            "next_action": store.get("next_action"),
            "readiness": {
                **store.get("readiness", {}),
                "current_execution_verified": current_execution_verified(store.get("readiness", {})),
            },
            "reconciliation_errors": store.get("reconciliation_errors", []),
            "calendar": store.get("calendar", {}),
            "operational_session": operational_session,
            "branches": branches,
            "accounting": {
                "broker_equity": broker_equity,
                "broker_cash": _number(account.get("cash")),
                "branch_ledger_equity": ledger_equity,
                "unattributed_equity_difference": round(difference, 8) if difference is not None else None,
                "reconciled": reconciled,
                "as_of": store.get("last_reconciled"),
                "basis": "Broker equity is the portfolio total. Branch attribution excludes any unresolved residual; no fee attribution is invented.",
            },
            "account_activity": accounting_summary(store),
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
            "objective_scorecard": scorecard,
            "observation_research": observation_context(store, max_chars=7500),
            "adaptive_lab": AdaptiveLab(store, initialize=False).summary(),
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
            "operational_review": store.get("operational_review", {}),
            "quality_audit": store.get("quality_audit", {}),
            "source_quality_reviews": [
                store.get(k, {})
                for k in ("source_quality_review", "legacy_source_quality_review")
                if store.get(k)
            ],
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
            "experiment_funnel": Experiments(store).funnel(),
            "background_research": public_summary(store),
            "usage": store.rows(
                "SELECT at,day,role,model,input_tokens,cached_tokens,output_tokens,quota_delta,"
                "coalesce(json_extract(payload,'$.state'),'completed') state,"
                "json_extract(payload,'$.terminal_outcome') outcome,"
                "json_extract(payload,'$.attempt_id') attempt_id,"
                "json_extract(payload,'$.application_outcome') application_outcome,"
                "json_extract(payload,'$.application_validation_code') application_validation_code,"
                "json_extract(payload,'$.reply_usage_reported') reply_usage_reported,"
                "json_extract(payload,'$.quota_delta_reported') quota_delta_reported,"
                "json_extract(payload,'$.quota_delta_basis') quota_delta_basis "
                "FROM usage ORDER BY id DESC LIMIT 150"
            ),
            "budget": usage_policy(store),
            "execution_quality": {
                "additional_cost_allowance": extra_cost,
                "illustrative_equity_after_allowance": _number(broker_equity - extra_cost) if reconciled and broker_equity is not None and extra_cost is not None else None,
                "basis": "Additional 10bp per executed side; illustrative, not actual fees or a live-fill simulation.",
            },
            "benchmarks": store.get("benchmarks", {}),
            "options_research": store.get("options_research", {}),
            "options_coverage": options_coverage_summary(store),
            "research_input_quality": input_quality,
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
        index = index.replace('"' + name + '"', '"' + name + "?v=" + version + '"')
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


def publication_revision(config, store, expected_head=None):
    """Require the configured branch and a reviewed source-commit ancestor.

    Inspect every later commit, including merge-parent diffs, so a source change
    followed by its reversal cannot be laundered into a dashboard-only history.
    """
    branch = git_run(config, ["symbolic-ref", "--quiet", "--short", "HEAD"])
    if branch.returncode or branch.stdout.strip() != config.publish_branch:
        raise RuntimeError("Publication requires the configured local branch")
    revision = git_run(config, ["rev-parse", "HEAD"])
    head = revision.stdout.strip()
    if revision.returncode or not re.fullmatch(r"[0-9a-f]{40}", head):
        raise RuntimeError("Cannot identify the publication revision")
    if expected_head is not None and head != expected_head:
        raise RuntimeError("Repository changed during publication; retry after review")
    dirty = git_run(config, ["diff", "--name-only", "--no-renames", "-z", "HEAD", "--"])
    if dirty.returncode:
        raise RuntimeError("Cannot inspect tracked source changes")
    if any(path not in PUBLIC_PATHS for path in dirty.stdout.split("\0") if path):
        raise RuntimeError("Unreviewed tracked source changes; publication postponed")
    approved = store.get("release", {}).get("source_commit")
    if not isinstance(approved, str) or not re.fullmatch(r"[0-9a-f]{40}", approved):
        raise RuntimeError("Publication requires a reviewed source-commit receipt")
    if git_run(config, ["merge-base", "--is-ancestor", approved, head]).returncode:
        raise RuntimeError("Reviewed source commit is not an ancestor of this revision")
    changes = git_run(config, [
        "log", "--format=", "--name-only", "--no-renames", "-z", "--diff-merges=separate",
        f"{approved}..{head}",
    ])
    if changes.returncode:
        raise RuntimeError("Cannot verify publication history")
    if any(path not in PUBLIC_PATHS for path in changes.stdout.split("\0") if path):
        raise RuntimeError("Unreviewed source commits; publication postponed")
    return head


def publish(config, store):
    def staged_paths():
        result = git_run(config, ["diff", "--cached", "--name-only", "--no-renames", "-z"])
        if result.returncode:
            raise RuntimeError("Cannot inspect staged files; publication postponed")
        paths = [path for path in result.stdout.split("\0") if path]
        if any(path not in PUBLIC_PATHS for path in paths):
            raise RuntimeError("Unrelated staged files; publication postponed")
        return paths

    # Inspect before changing the index so an unrelated user-staged draft stays
    # exactly as staged. A docs/ prefix alone is not a publication allowlist.
    if config.publish:
        staged_paths()
        initial_head = publication_revision(config, store)
    export(config, store)
    if not config.publish:
        return {"status": "local_only"}
    # Stage only sanitized generated site files. Never git add the runtime directory.
    result = git_run(
        config,
        ["add", "--", *PUBLIC_PATHS],
    )
    if result.returncode:
        raise RuntimeError("Dashboard staging failed")
    paths = staged_paths()
    publication_revision(config, store, expected_head=initial_head)
    if paths:
        # Explicit paths also prevent a concurrent git add after the inspection
        # from leaking an unrelated staged file into the autonomous commit.
        result = git_run(config, [
            "commit", "--only", "-m", "[dashboard] local trading laboratory snapshot",
            "--", *PUBLIC_PATHS,
        ])
        if result.returncode:
            raise RuntimeError("Dashboard commit failed")
    revision = publication_revision(config, store)
    # Never force-push or reset user edits. Failed synchronization is retried later.
    binary = "/mnt/c/Windows/System32/wscript.exe"
    if os.path.exists(binary) and str(config.root).startswith("/mnt/c/"):
        # Windows credential helpers can allocate a console when called from WSL.
        # Keep the complete push/authentication chain inside the hidden GUI host.
        launcher = "C:\\" + str(config.root / "scripts/runtime/hidden-launch.vbs")[7:].replace(
            "/", "\\"
        )
        result = subprocess.run(
            [binary, "//B", "//NoLogo", launcher, "publish", revision],
            cwd=config.root,
            capture_output=True,
            text=True,
            timeout=80,
            env={**os.environ, "GCM_INTERACTIVE": "Never"},
        )
    else:
        result = git_run(config, ["push", "origin", revision + ":main"])
    if result.returncode:
        raise RuntimeError("GitHub push failed; local trading remains independent")
    store.set("last_published", utc_now())
    return {"status": "pushed", "commit": revision}
