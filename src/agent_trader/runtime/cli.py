from __future__ import annotations

import argparse
import json
import logging
import shutil
import time
from datetime import datetime

from .agent import CodexRPC
from .broker import Broker
from .config import Config, ET
from .engine import Engine, TERMINAL, order_id
from .publish import export, publish
from .store import Store, utc_now


def reset_application(config, confirm):
    if confirm != "RESET":
        raise ValueError("Reset requires --confirm RESET")
    if (config.state_dir / "supervisor.lock").exists():
        import fcntl

        with open(config.state_dir / "supervisor.lock", "a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError("Stop supervisor before resetting")
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


def smoke_submission(config, store):
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
                "execution_verified": False,
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
    if args.command == "reset":
        print(json.dumps(reset_application(config, args.confirm)))
        return
    if args.command in ("run", "tick", "doctor"):
        from .supervisor import Supervisor

        s = Supervisor(config)
        if args.command == "run":
            s.run()
        elif args.command == "tick":
            s.tick()
            s.pool.shutdown(wait=True)
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
            print(json.dumps(smoke_submission(config, store)))
        elif args.command == "agent-check":
            from .models import Decision

            with CodexRPC(config) as rpc:
                print("Available models:", [m.get("id") for m in rpc.models()])
                print("Quota:", json.dumps(rpc.rate_limits()))
                tid, result, usage, counts = rpc.run(
                    None,
                    'Return Decision with plan_id connectivity-test, action wait, reason "Connectivity test; no trade requested.", contradictions [], evidence_fresh false. No tools.',
                    config.light_model,
                    "low",
                    Decision.model_json_schema(),
                    max_searches=0,
                    max_cycles=8,
                )
                tid, result2, _, _ = rpc.run(
                    tid,
                    "Return the same connectivity-test wait Decision. This turn checks model switching on the same thread. No tools.",
                    config.decision_model,
                    "low",
                    Decision.model_json_schema(),
                    max_searches=0,
                    max_cycles=8,
                )
                print(
                    "Inference and same-thread model switch:", result["action"], result2["action"]
                )
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
