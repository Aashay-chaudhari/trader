from __future__ import annotations

import argparse
import json
import logging
import shutil
import time
from datetime import datetime

from .agent import run_task
from .broker import Broker
from .config import Config, ET
from .engine import Engine, TERMINAL, EXECUTION_KERNEL, order_id
from .publish import export, publish
from .store import Store, utc_now
from .ownership import RuntimeBusy, runtime_ownership


def reset_application(config, confirm, *, ownership=None):
    with runtime_ownership(config.state_dir, ownership):
        return _reset_application(config, confirm)


def _reset_application(config, confirm):
    if confirm != "RESET":
        raise ValueError("Reset requires --confirm RESET")
    broker = Broker(config)
    if broker.positions() or broker.orders():
        raise ValueError("Broker must have no positions or open orders for a fresh ledger")
    archive = config.state_dir / "archive" / datetime.now(ET).strftime("reset-%Y%m%d-%H%M%S")
    archive.mkdir(parents=True, exist_ok=True)
    for name in ("trader.sqlite3", "trader.sqlite3-wal", "trader.sqlite3-shm"):
        p = config.state_dir / name
        if p.exists():
            shutil.move(str(p), archive / name)
    for root in (config.root / "data", config.root / "docs/data"):
        if root.exists():
            destination = archive / (
                "legacy-data" if root == config.root / "data" else "published-data"
            )
            shutil.move(str(root), destination)
    (config.root / "data").mkdir(exist_ok=True)
    (config.root / "data/README.md").write_text(
        "# Runtime state\n\nOperational data lives locally in ignored `.runtime/trader.sqlite3`.\nOnly sanitized snapshots are published to `docs/data/lab.json`.\nHistorical profile artifacts are archived locally and remain in Git history.\n"
    )
    store = Store(config.state_dir / "trader.sqlite3")
    store.set(
        "fresh_start",
        {"start_date": config.start_date, "reset_at": utc_now(), "preserve_git_history": True},
    )
    store.set("mode", "research_shadow")
    store.set(
        "status", "Fresh experiment prepared. First trading session: " + config.start_date + "."
    )
    store.set("next_action", "07:45 ET startup notification; 08:15 ET morning research.")
    store.event(
        "release",
        {
            "summary": "Fresh application ledger. Three separate $10,000 allocations; no legacy trades or memory imported."
        },
    )
    Engine(config, store, broker).reconcile()
    export(config, store)
    store.close()
    return {"reset": "complete", "start_date": config.start_date, "git_history": "preserved"}


def smoke_submission(config, store, *, ownership=None):
    with runtime_ownership(config.state_dir, ownership):
        return _smoke_submission(config, store)


def _smoke_submission(config, store):
    broker = Broker(config)
    if broker.positions() or broker.orders():
        raise ValueError("Submission test requires flat paper account")
    engine = Engine(config, store, broker)
    cid = order_id("preflight-submission", datetime.now(ET).date().isoformat())
    order = broker.by_client(cid)
    if order is None:
        payload = {
            "symbol": "SPY",
            "qty": "1",
            "side": "buy",
            "type": "limit",
            "limit_price": "1.00",
            "time_in_force": "day",
            "client_order_id": cid,
            "extended_hours": False,
        }
        order = engine.submit_intent(payload, "intraday", "submission-preflight")
    try:
        if order["status"] not in TERMINAL:
            broker.cancel(order["id"])
        for _ in range(10):
            latest = broker.order(order["id"])
            engine.ingest_order(latest, "intraday", "submission-preflight")
            if latest["status"] in TERMINAL:
                break
            time.sleep(0.5)
        if float(latest.get("filled_qty") or 0) > 0:
            raise ValueError("Unexpected test fill; reconcile before continuing")
        if latest["status"] != "canceled":
            raise ValueError("Test cancellation not confirmed")
        engine.reconcile()
        readiness = store.get("readiness", {})
        readiness.update(
            {
                "order_submission_verified": True,
                "submission_checked_at": utc_now(),
                "execution_verified": readiness.get("execution_verified", False),
                "required_execution_kernel": EXECUTION_KERNEL,
                "verified_execution_kernel": None,
            }
        )
        store.set("readiness", readiness)
        store.event(
            "startup",
            {
                "summary": "Paper API accepted and canceled a deliberately nonmarketable $1 SPY limit. Fill/exit round-trip still pending market-open check."
            },
        )
        return {
            "submission": "accepted",
            "cancellation": "confirmed",
            "fills": 0,
            "round_trip": "pending_market_open",
        }
    finally:
        # Never intentionally leave a test entry resting overnight.
        fresh = broker.by_client(cid)
        if fresh and fresh["status"] not in TERMINAL:
            broker.cancel(fresh["id"])


def main():
    parser = argparse.ArgumentParser(
        description="Trader — local autonomous paper-trading laboratory"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for cmd in (
        "run",
        "tick",
        "status",
        "doctor",
        "dashboard",
        "publish",
        "smoke",
        "notify",
        "research-test",
        "explore",
        "agent-check",
    ):
        sub.add_parser(cmd)
    reset = sub.add_parser("reset")
    reset.add_argument("--confirm", required=True)
    args = parser.parse_args()
    config = Config.load()
    config.state_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(config.state_dir / "supervisor.log"),
            logging.StreamHandler(),
        ],
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    exclusive_commands = {
        "run", "tick", "doctor", "reset", "smoke", "explore", "research-test", "agent-check",
    }
    try:
        if args.command in exclusive_commands:
            with runtime_ownership(config.state_dir) as ownership:
                return dispatch(config, args, ownership=ownership)
        return dispatch(config, args)
    except RuntimeBusy as exc:
        raise SystemExit(str(exc)) from None


def dispatch(config, args, *, ownership=None):
    if args.command == "reset":
        print(json.dumps(reset_application(config, args.confirm, ownership=ownership)))
        return
    if args.command in ("run", "tick", "doctor"):
        from .supervisor import Supervisor

        try:
            s = Supervisor(config)
        except Exception as exc:
            from .notify import notify

            failed = Store(config.state_dir / "trader.sqlite3")
            notify(
                config,
                failed,
                "startup-failure:" + datetime.now(ET).date().isoformat(),
                "Trader - startup blocked",
                "Local supervisor could not start ("
                + type(exc).__name__
                + "). Check local configuration and logs.",
                urgent=True,
            )
            failed.close()
            raise SystemExit(1) from None
        try:
            if args.command == "run":
                s.run(ownership=ownership)
            elif args.command == "tick":
                from .store import process_owner

                s.store.job_owner = process_owner("supervisor")
                s.tick()
                s.pool.shutdown(wait=True)
                s.finish_task()
            else:
                good = s.preflight()
                export(config, s.store)
                print(
                    json.dumps(
                        {
                            "ready_for_research": good,
                            "checks": s.store.get("readiness"),
                            "reconciliation_errors": s.store.get("reconciliation_errors"),
                        }
                    )
                )
        finally:
            s.pool.shutdown(wait=True, cancel_futures=True)
            s.publisher_pool.shutdown(wait=True, cancel_futures=True)
            s.store.close()
        return
    store = Store(config.state_dir / "trader.sqlite3")
    try:
        if args.command == "status":
            print(
                json.dumps(
                    {
                        "mode": store.get("mode"),
                        "status": store.get("status"),
                        "heartbeat": store.get("heartbeat"),
                        "readiness": store.get("readiness"),
                        "branches": store.rows("SELECT * FROM branches"),
                    }
                )
            )
        elif args.command == "dashboard":
            export(config, store)
            print("Dashboard generated")
        elif args.command == "publish":
            print(json.dumps(publish(config, store)))
        elif args.command == "smoke":
            print(json.dumps(smoke_submission(config, store, ownership=ownership)))
        elif args.command == "agent-check":
            print(json.dumps(check_agent(config)))
        elif args.command == "explore":
            from .supervisor import worker
            from .exploration import seed_challengers, record_report, record_validation
            from .research import market_packet
            from .quality import record_artifact, daily_audit

            day = datetime.now(ET).date().isoformat()
            if store.job_start("exploration-bootstrap:" + day):
                try:
                    seed_challengers(store)
                    market_packet(Broker(config), store)
                    result = worker(config, "exploration", {}, day)
                    record_report(store, result, day, morning=False)
                    record_artifact(
                        store, day, "exploration", result, "exploration-bootstrap:" + day
                    )
                    reviewed = worker(config, "research_validation", {}, day)
                    record_validation(store, reviewed)
                    record_artifact(
                        store, day, "research_validation", reviewed, "validation-bootstrap:" + day
                    )
                    daily_audit(store, day, persist=True)
                    store.job_end("exploration-bootstrap:" + day, True, {"reviewed": True})
                    export(config, store)
                    print(
                        json.dumps(
                            {
                                "hypotheses": len(result["hypotheses"]),
                                "reviewed": len(reviewed["hypotheses"]),
                                "orders_authorized": False,
                            }
                        )
                    )
                except Exception:
                    store.job_end("exploration-bootstrap:" + day, False, {"reviewed": False})
                    raise
            else:
                print("Bootstrap already completed or retry limit reached")
        elif args.command == "research-test":
            from .supervisor import worker

            result = worker(config, "research", {}, datetime.now(ET).date().isoformat())
            (config.state_dir / "research-integration-test.json").write_text(
                json.dumps(result, indent=2)
            )
            print(
                json.dumps(
                    {
                        "valid_brief": True,
                        "sources": len(result["sources"]),
                        "plans": len(result["plans"]),
                        "saved": "private integration-test artifact; not used for trading",
                    }
                )
            )
        elif args.command == "notify":
            from .notify import notify

            print(
                json.dumps(
                    {
                        "accepted": notify(
                            config,
                            store,
                            "manual:" + utc_now(),
                            "Trader - refactor check",
                            "The integrated local runtime and phone notification path are connected. No trade was placed by this notification.",
                        )
                    }
                )
            )
    finally:
        store.close()


def check_agent(config):
    """Two bounded, accounted turns verify a model switch on one isolated thread."""
    from uuid import uuid4
    from .models import Decision

    day = datetime.now(ET).date().isoformat()
    scope = "connectivity-check:" + uuid4().hex
    results = []
    for model in (config.light_model, config.decision_model):
        result = run_task(
            config, "connectivity_check",
            'Return Decision with plan_id connectivity-test, action wait, reason '
            '"Connectivity test; no trade requested.", contradictions [], '
            'evidence_fresh false. No tools. Resume the same test if this is a second turn.',
            Decision, model, "low", day, searches=0, cycles=8, scope=scope,
        )
        results.append(result["action"])
    return {"inference": results, "same_thread_model_switch": "checked", "orders_authorized": False}
