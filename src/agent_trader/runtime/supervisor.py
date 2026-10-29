from __future__ import annotations

import concurrent.futures
import json
import logging
import signal
import time
from datetime import datetime, timedelta

from .agent import CodexRPC, run_task
from .broker import Broker
from .config import ET
from .engine import Engine, TERMINAL, order_id, quote_values, timestamp
from .experiments import Experiments
from .models import Brief, Decision, MaintenanceProposal, Pulse, Review, PositionDecision
from .notify import notify
from .publish import export, publish
from .research import BASE, decision_prompt, market_packet, research_prompt, review_prompt
from .store import Store, utc_now

LOG = logging.getLogger(__name__)


def session_times(calendar, day):
    if not calendar:
        return None
    c = calendar[0]
    return (
        datetime.fromisoformat(day + "T" + c["open"]).replace(tzinfo=ET),
        datetime.fromisoformat(day + "T" + c["close"]).replace(tzinfo=ET),
    )


def worker(config, role, context, day):
    store = Store(config.state_dir / "trader.sqlite3")
    try:
        if role == "research":
            packet = market_packet(Broker(config), store)
            prompt, schema, model, effort, searches = (
                research_prompt(day, packet, store),
                Brief,
                config.research_model,
                "high",
                8,
            )
        elif role == "decision":
            prompt, schema, model, effort, searches = (
                decision_prompt(**context),
                Decision,
                config.decision_model,
                "medium",
                0,
            )
        elif role == "position_review":
            prompt = (
                BASE
                + "\nROLE: active position reviewer. Use only supplied evidence.\n"
                + json.dumps(context)
                + """
Return PositionDecision. Hold unless the documented thesis is invalidated by current
verified evidence. Exits cannot create a short or reassign ownership. Missing data
means hold with an explicit concern; broker-held protection remains active.
"""
            )
            schema, model, effort, searches = PositionDecision, config.decision_model, "medium", 0
        elif role == "pulse":
            prompt = (
                BASE
                + "\nROLE: focused market-event update. Use at most 3 web searches. "
                + json.dumps(
                    {
                        "now": utc_now(),
                        "brief": context.get("brief"),
                        "symbols": context.get("symbols"),
                        "instruction": "Check material changes to Fed/macro calendar, earnings or major catalysts affecting these holdings/plans. "
                        "Do not invent fresh quotes or plans. Record unknowns. Return Pulse JSON.",
                    }
                )[:18000]
            )
            schema, model, effort, searches = Pulse, config.light_model, "low", 3
        elif role in ("retrospective", "weekly", "monthly"):
            date = datetime.fromisoformat(day).date()
            beginning = day
            if role == "weekly":
                beginning = (date - timedelta(days=date.weekday())).isoformat()
            if role == "monthly":
                beginning = date.replace(day=1).isoformat()
            prompt, schema, model, effort, searches = (
                review_prompt(beginning, store)
                + "\nReview period: "
                + role
                + " through "
                + day
                + ". Do not invent pre-launch evidence.",
                Review,
                config.research_model,
                "high",
                2,
            )
        elif role == "maintenance":
            from .maintenance import maintenance_prompt

            prompt, schema, model, effort, searches = (
                maintenance_prompt(config, context),
                MaintenanceProposal,
                config.maintenance_model,
                "high",
                0,
            )
        else:
            raise ValueError("Unknown role")
        return run_task(config, role, prompt, schema, model, effort, day, searches=searches)
    finally:
        store.close()


class Supervisor:
    def __init__(self, config):
        self.config = config
        self.store = Store(config.state_dir / "trader.sqlite3")
        self.broker = Broker(config)
        self.engine = Engine(config, self.store, self.broker)
        self.experiments = Experiments(self.store)
        self.pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="research"
        )
        self.future = None
        self.task = None
        self.publisher_pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="publisher"
        )
        self.publication_future = None
        self.last_publish = 0
        self.stopping = False

    def incident(self, code, reason):
        LOG.warning("%s: %s", code, reason)
        self.store.event("incident", {"code": code, "reason": reason})
        day = datetime.now(ET).date().isoformat()
        notify(
            self.config,
            self.store,
            f"incident:{day}:{code}",
            "Trader - attention required",
            reason,
            urgent=True,
        )

    def launch(self, key, role, context, day):
        if self.future or not self.store.job_start(key):
            return False
        self.store.set("active_task", {"key": key, "role": role, "started": utc_now()})
        self.task = (key, role, context, day)
        self.future = self.pool.submit(worker, self.config, role, context, day)
        return True

    def finish_task(self):
        if not self.future or not self.future.done():
            return
        key, role, context, day = self.task
        try:
            result = self.future.result()
            if role == "research":
                # Never allow a research result from another session/date to enter
                # the live queue. Expired plans remain visible but cannot execute.
                self.store.set("brief", result)
                self.store.set("brief_day", day)
                import hashlib

                for plan in result["plans"]:
                    suffix = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()[
                        :8
                    ]
                    plan["id"] = plan["id"][:59] + "-" + suffix
                self.store.db.execute(
                    "UPDATE plans SET state='superseded' WHERE state IN ('planned','approved')"
                )
                self.engine.add_plans(result["plans"], day)
                self.store.memory_put(
                    "brief:" + day, "observation", result, day + "T23:59:59-04:00"
                )
                self.store.event(
                    "research_completed",
                    {
                        "summary": result["summary"],
                        "plans": len(result["plans"]),
                        "regime": result["regime"],
                    },
                )
                notify(
                    self.config,
                    self.store,
                    "research:" + day,
                    "Trader - morning research ready",
                    result["summary"][:600]
                    + f"\n{len(result['plans'])} plans. Options remain shadow-only.",
                )
            elif role == "decision":
                if result["plan_id"] != context["plan"]["id"]:
                    raise ValueError("Decision refers to a different plan")
                action = result["action"]
                if action == "approve" and not result["evidence_fresh"]:
                    action = "wait"
                self.store.db.execute(
                    "UPDATE plans SET state=? WHERE id=?",
                    (
                        {"approve": "approved", "wait": "planned", "invalidate": "invalidated"}[
                            action
                        ],
                        result["plan_id"],
                    ),
                )
                self.store.set(
                    "approval:" + result["plan_id"], {"at": utc_now(), "decision": result}
                )
                self.store.event("decision", result, context["plan"]["branch"])
            elif role == "position_review":
                if result["symbol"] != context["holding"]["symbol"]:
                    raise ValueError("Position review refers to another symbol")
                self.store.event("decision", result, context["holding"]["branch"])
                if (
                    result["action"] == "exit"
                    and result["evidence_fresh"]
                    and result["invalidation_observed"]
                ):
                    self.store.set(
                        "exit-intent:" + result["symbol"],
                        {"at": utc_now(), "reason": result["reason"]},
                    )
            elif role == "pulse":
                result["at"] = utc_now()
                self.store.set("pulses", [result, *self.store.get("pulses", [])][:10])
                self.store.event(
                    "pulse",
                    {"summary": result["summary"], "material_change": result["material_change"]},
                )
                if result["material_change"]:
                    # Invalidate approvals and stop new entries pending re-research;
                    # numerical protection remains in operation.
                    self.store.set(
                        "material_change", {"at": utc_now(), "summary": result["summary"]}
                    )
                    self.store.db.execute("UPDATE plans SET state='planned' WHERE state='approved'")
                    self.store.set("needs_research", True)
            elif role in ("weekly", "monthly"):
                self.store.set(role + ":" + day, result)
                self.store.event("period_review", {"period": role, "summary": result["summary"]})
                for i, lesson in enumerate(result["proposed_lessons"]):
                    self.store.memory_put(
                        f"{role}:{day}:lesson:{i}",
                        "lesson",
                        {"claim": lesson, "state": "proposed", "period": role, "ending": day},
                    )
            elif role == "retrospective":
                self.store.set("review", result)
                self.store.set("review_day", day)
                for i, lesson in enumerate(result["proposed_lessons"]):
                    self.store.memory_put(
                        f"{day}:lesson:{i}",
                        "lesson",
                        {"claim": lesson, "state": "proposed", "evidence_day": day},
                    )
                for proposal in result["experiments"]:
                    try:
                        self.experiments.register(proposal)
                    except (ValueError, TypeError, KeyError):
                        self.store.event(
                            "experiment_rejected",
                            {"reason": "Invalid or incomplete evaluation contract"},
                        )
                for exp in self.experiments.evaluate():
                    notify(
                        self.config,
                        self.store,
                        "promotion:" + exp,
                        "Trader - strategy promoted",
                        exp + " passed its recorded forward-evaluation gates.",
                    )
            elif role == "maintenance":
                from .maintenance import stage_change

                stage_change(self.config, self.store, result)
            self.store.job_end(key, True, {"role": role, "completed": utc_now()})
        except Exception as exc:
            self.store.job_end(key, False, {"error_type": type(exc).__name__})
            self.incident(
                "agent_" + role,
                f"{role.title()} did not complete ({type(exc).__name__}). Protective routines continue; new plans require valid research.",
            )
        finally:
            self.future = None
            self.task = None
            self.store.set("active_task", None)

    def preflight(self):
        good = self.engine.reconcile()
        readiness = self.store.get("readiness", {})
        account = self.store.get("account", {})
        funded = (
            abs(float(account.get("equity", 0)) - 30000) < 1
            if not self.store.rows("SELECT * FROM orders")
            else True
        )
        with CodexRPC(self.config) as rpc:
            quota = rpc.rate_limits()
            self.store.set("quota", quota)
            available = [m.get("id") for m in rpc.models()]
        models_ok = all(
            m in available
            for m in (
                self.config.research_model,
                self.config.decision_model,
                self.config.light_model,
                self.config.maintenance_model,
            )
        )
        readiness.update(
            {
                "at": utc_now(),
                "broker_reconciled": good,
                "funded": funded,
                "models_available": models_ok,
                "paper_endpoint": True,
                "free_only": True,
                "options_mode": "shadow_indicative",
                "execution_verified": readiness.get("execution_verified", False),
            }
        )
        self.store.set("readiness", readiness)
        return good and funded and models_ok

    def smoke(self, now, opened, close):
        r = self.store.get("readiness", {})
        if r.get("execution_verified"):
            return True
        if (
            not self.config.execution
            or now.date().isoformat() < self.config.start_date
            or now < opened + timedelta(minutes=2)
        ):
            return False
        if not self.store.get("reconciled") or not r.get("funded") or not r.get("models_available"):
            return False
        day = now.date().isoformat()
        key = "smoke:" + day
        stage = self.store.get(key, {})
        if not stage:
            q = self.broker.quotes(["SPY"]).get("SPY", {})
            _, ask = quote_values(q, now)
            entry = round(ask, 2)
            payload = {
                "symbol": "SPY",
                "side": "buy",
                "qty": "1",
                "type": "limit",
                "limit_price": str(entry),
                "time_in_force": "day",
                "order_class": "bracket",
                "take_profit": {"limit_price": str(round(entry + 2, 2))},
                "stop_loss": {"stop_price": str(round(entry - 2, 2))},
                "client_order_id": order_id("smoke", day, "buy"),
            }
            if now > close - timedelta(minutes=40):
                return False
            self.engine.submit_intent(payload, "intraday", "operational-smoke-" + day)
            self.store.set(key, {"at": now.isoformat(), "state": "submitted"})
            self.store.event(
                "startup",
                {
                    "summary": "Controlled one-share SPY execution smoke check submitted; $2 planned stop distance."
                },
            )
            return False
        rows = self.store.rows(
            "SELECT * FROM orders WHERE plan_id=? AND side='buy'", ("operational-smoke-" + day,)
        )
        if not rows:
            return False
        order = rows[0]
        if order["filled"] > 0:
            self.engine.close_intraday()
            self.engine.reconcile()
            if not self.store.rows("SELECT * FROM holdings WHERE branch='intraday'") and not [
                o for o in self.broker.orders() if o["symbol"] == "SPY"
            ]:
                r["execution_verified"] = True
                r["execution_verified_at"] = utc_now()
                self.store.set("readiness", r)
                self.store.set(key, {"at": now.isoformat(), "state": "passed"})
                notify(
                    self.config,
                    self.store,
                    "smoke:" + day,
                    "Trader - paper execution verified",
                    "One-share paper entry, broker fill, closing fill and reconciliation passed. Equity paper pilots can now operate.",
                )
                return True
        elif now - timestamp(stage["at"]) > timedelta(minutes=2):
            if order["broker_id"] and order["status"] not in TERMINAL:
                self.broker.cancel(order["broker_id"])
            self.store.set(key, {**stage, "state": "unfilled"})
            notify(
                self.config,
                self.store,
                "smoke-unfilled:" + day,
                "Trader - research/shadow mode",
                "Execution check did not fill. Pending entry canceled; pilots remain disabled.",
            )
        return False

    def benchmarks(self, quotes, now):
        benchmarks = self.store.get(
            "benchmarks",
            {"summary": "Forward baseline recording active", "series": [], "starts": {}},
        )
        for symbol in ["SPY", "QQQ", "TLT"]:
            q = quotes.get(symbol)
            if not q:
                continue
            try:
                bid, ask = quote_values(q, now)
            except ValueError:
                continue
            mid = (bid + ask) / 2
            benchmarks["starts"].setdefault(symbol, {"price": mid, "at": now.isoformat()})
            benchmarks[symbol] = {
                "return": mid / benchmarks["starts"][symbol]["price"] - 1,
                "price": mid,
                "at": now.isoformat(),
            }
        q = quotes.get("SPY")
        if q:
            try:
                bid, ask = quote_values(q, now)
                day = now.date().isoformat()
                rule = benchmarks.get("fixed_rule", {})
                cal = self.store.get("calendar:" + day, [])
                session = session_times(cal, day)
                if session and now >= session[0] + timedelta(minutes=5):
                    if rule.get("day") != day:
                        indicator = (
                            self.store.get("market_packet", {})
                            .get("daily_indicators", {})
                            .get("SPY", {})
                        )
                        sma = indicator.get("sma20")
                        rule = {
                            "day": day,
                            "entry": ask,
                            "entered_at": now.isoformat(),
                            "trades": bool(sma and ask > sma),
                            "name": "SPY above SMA20 at first quote after 09:35; close before session end",
                            "assumptions": "Unit exposure, ask entry/bid exit, 20bp cost; forward shadow only",
                        }
                    if now >= session[1] - timedelta(minutes=12) and "last_return" not in rule:
                        rule["last_return"] = (
                            (bid / rule["entry"] - 1 - 0.002) if rule["trades"] else 0
                        )
                        rule["exit_at"] = now.isoformat()
                        rule["exit_price"] = bid
                    benchmarks["fixed_rule"] = rule
            except ValueError:
                pass
        self.store.set("benchmarks", benchmarks)

    def tick(self, now=None):
        now = now or datetime.now(ET)
        now = now.astimezone(ET)
        day = now.date().isoformat()
        self.store.set("heartbeat", now.isoformat())
        self.finish_task()
        calkey = "calendar:" + day
        cal = self.store.get(calkey)
        if cal is None:
            cal = self.broker.calendar(day)
            self.store.set(calkey, cal)
        times = session_times(cal, day)
        self.store.set("calendar", {"date": day, "session": cal})
        if self.store.get("preflight_day") != day:
            self.preflight()
            self.store.set("preflight_day", day)
        if day < self.config.start_date:
            self.store.set("mode", "research_shadow")
            self.store.set(
                "status",
                "Fresh experiment prepared. Trading starts " + self.config.start_date + ".",
            )
            self.store.set(
                "next_action", "07:45 ET startup and phone notification on the first trading day."
            )
            self.maybe_publish()
            return
        if not times:
            self.store.set(
                "status", "Market holiday or weekend. Existing broker protection remains in place."
            )
            self.store.set(
                "next_action", "Next trading session: automatic startup and calendar refresh."
            )
            self.engine.reconcile()
            self.maybe_publish()
            return
        opened, close = times
        valid = self.engine.reconcile(now)
        if not valid:
            self.store.set("mode", "halted")
            self.incident(
                "reconciliation",
                "Broker and branch ledgers differ. New entries halted; inspect System for details.",
            )
        last_fill = self.store.get("notified_fill_id", 0)
        fills = self.store.rows(
            "SELECT id,payload FROM events WHERE kind='fill' AND id>? ORDER BY id LIMIT 50",
            (last_fill,),
        )
        if fills:
            text = "\n".join(
                f"{json.loads(f['payload'])['side'].upper()} {json.loads(f['payload'])['qty']} {json.loads(f['payload'])['symbol']} @ ${json.loads(f['payload'])['price']:.2f}"
                for f in fills
            )
            if notify(
                self.config,
                self.store,
                "fills:" + str(fills[-1]["id"]),
                "Trader - confirmed paper fills",
                text,
            ):
                self.store.set("notified_fill_id", fills[-1]["id"])
        ready = self.store.get("readiness", {})
        pilot = valid and ready.get("execution_verified") and self.config.execution
        self.store.set(
            "mode", "paper_pilot" if pilot else ("halted" if not valid else "research_shadow")
        )
        if now.hour >= 7 and (now.hour > 7 or now.minute >= 45):
            notify(
                self.config,
                self.store,
                "morning:" + day,
                "Trader - good morning",
                "The local trading laboratory is running. Research begins at 08:15 ET. Three separate $10,000 paper allocations; options shadow-only.",
            )
        if now >= opened and now < close:
            self.engine.cancel_entries(now, close)
            self.engine.ensure_protection()
            if not ready.get("execution_verified"):
                try:
                    self.smoke(now, opened, close)
                except Exception as exc:
                    self.incident(
                        "smoke",
                        f"Paper execution check deferred ({type(exc).__name__}); entries remain blocked.",
                    )
            if now >= close - timedelta(minutes=12):
                self.store.set("status", "Closing intraday positions and verifying fills.")
                self.store.set("next_action", "After-close reconciliation and daily results.")
                self.engine.close_intraday()
                self.finish_shadow(now, closing=True)
            else:
                self.store.set(
                    "status",
                    "Monitoring the session. Agent reviews material changes and eligible setups.",
                )
                self.store.set(
                    "next_action",
                    f"Intraday closing routine at {(close - timedelta(minutes=12)).strftime('%H:%M')} ET.",
                )
                self.market_tick(now, close)
        elif now >= close:
            held = self.store.rows("SELECT * FROM holdings WHERE branch='intraday'")
            if held:
                self.incident(
                    "unclosed_intraday",
                    "Intraday holdings remain after the close. Broker-held protection remains; immediate inspection required.",
                )
            self.store.set("status", "Market closed. Reconciling and reviewing the session.")
            self.store.set(
                "next_action",
                "Daily retrospective, experiment evaluation, and validated maintenance.",
            )
        else:
            self.store.set("status", "Preparing the session. Research starts at 08:15 ET.")
            self.store.set(
                "next_action",
                "Morning market brief and event calendar; paper execution check after 09:32 ET.",
            )
        # Launch roles only when the worker is free; deterministic tick keeps running.
        if not self.future:
            if now >= opened.replace(hour=8, minute=15) and now < close - timedelta(minutes=45):
                if self.store.get("brief_day") != day:
                    self.launch("research:" + day, "research", {}, day)
                elif (
                    not self.engine.plans()
                    and 9 * 60 + 45 <= now.hour * 60 + now.minute < 10 * 60 + 15
                ):
                    self.launch("fresh-open-research:" + day, "research", {}, day)
                elif self.store.get("needs_research"):
                    slot = now.strftime("%H")
                    if self.launch("refresh:" + day + ":" + slot, "research", {}, day):
                        self.store.set("needs_research", False)
                elif now >= opened and now < close - timedelta(minutes=30):
                    if not self.launch_position_review(now) and not self.launch_candidate(
                        now, close
                    ):
                        minutes = now.hour * 60 + now.minute
                        for checkpoint in (11 * 60, 13 * 60, 14 * 60 + 30):
                            if checkpoint <= minutes < checkpoint + 45:
                                self.launch(
                                    f"pulse:{day}:{checkpoint}",
                                    "pulse",
                                    {
                                        "brief": self.store.get("brief", {}),
                                        "symbols": sorted(
                                            {p["symbol"] for p in self.engine.plans()}
                                            | {
                                                h["symbol"]
                                                for h in self.store.rows("SELECT * FROM holdings")
                                            }
                                        ),
                                    },
                                    day,
                                )
                                break
            if now >= close + timedelta(minutes=15):
                if self.store.get("review_day") != day:
                    self.launch("review:" + day, "retrospective", {}, day)
                elif now >= close + timedelta(minutes=35):
                    self.launch(
                        "maintenance:" + day, "maintenance", self.store.get("review", {}), day
                    )
        if (
            not self.future
            and now >= close + timedelta(minutes=60)
            and self.store.get("review_day") == day
        ):
            week_key = "last-week-session:" + day
            last_week_session = self.store.get(week_key)
            if last_week_session is None:
                weekend = now.date() + timedelta(days=6 - now.weekday())
                last_week_session = not self.broker.calendar_range(
                    (now.date() + timedelta(days=1)).isoformat(), weekend.isoformat()
                )
                self.store.set(week_key, last_week_session)
            if last_week_session:
                self.launch("weekly:" + day, "weekly", {}, day)
            if not self.future:
                import calendar as month_calendar

                last = now.date().replace(day=month_calendar.monthrange(now.year, now.month)[1])
                last_key = "last-session:" + day
                is_last = self.store.get(last_key)
                if is_last is None:
                    is_last = (
                        not self.broker.calendar_range(
                            (now.date() + timedelta(days=1)).isoformat(), last.isoformat()
                        )
                        if now.date() < last
                        else True
                    )
                    self.store.set(last_key, is_last)
                if is_last:
                    self.launch("monthly:" + day, "monthly", {}, day)
        if now >= close + timedelta(minutes=10):
            values = self.store.rows(
                "SELECT * FROM equity WHERE id IN (SELECT max(id) FROM equity GROUP BY branch)"
            )
            total = sum(x["value"] for x in values)
            summary = (
                f"Paper equity: ${total:,.2f}. Since fresh start: ${total - 30000:+,.2f}.\n"
                + "\n".join(f"{x['branch'].title()}: ${x['value']:,.2f}" for x in values)
            )
            if notify(self.config, self.store, "summary:" + day, "Trader - daily results", summary):
                if not self.store.get("summary_recorded:" + day):
                    self.store.event("daily_summary", {"summary": summary})
                    self.store.set("summary_recorded:" + day, True)
        self.maybe_publish()

    def finish_shadow(self, now, closing=False):
        symbols = [x["symbol"] for x in self.store.rows("SELECT * FROM shadow WHERE state='open'")]
        quotes = self.broker.quotes(sorted(set(symbols) | {"SPY"}))
        self.experiments.mark(quotes, now, closing=closing)
        self.benchmarks(quotes, now)

    def market_tick(self, now, close):
        plans = self.engine.plans()
        symbols = sorted(
            {p["symbol"] for p in plans}
            | {h["symbol"] for h in self.store.rows("SELECT * FROM holdings")}
            | {"SPY", "QQQ", "TLT"}
            | {x["symbol"] for x in self.store.rows("SELECT * FROM shadow WHERE state='open'")}
        )
        quotes = self.broker.quotes(symbols)
        self.store.set("quotes", quotes)
        self.benchmarks(quotes, now)
        brief = self.store.get("brief", {})
        from agent_trader.strategies.adaptive import candidate_filter

        for h in self.store.rows("SELECT * FROM holdings"):
            plan_rows = self.store.rows("SELECT payload FROM plans WHERE id=?", (h["plan_id"],))
            q = quotes.get(h["symbol"])
            if plan_rows and q:
                try:
                    bid, _ = quote_values(q, now)
                    owned_plan = json.loads(plan_rows[0]["payload"])
                    if bid >= owned_plan["target"]:
                        self.store.set(
                            "exit-intent:" + h["symbol"],
                            {"at": utc_now(), "reason": "Recorded target reached on a fresh quote"},
                        )
                except ValueError:
                    pass
            intent = self.store.get("exit-intent:" + h["symbol"])
            if intent and (now - timestamp(intent["at"])).total_seconds() < 300:
                if self.engine.exit_holding(h["symbol"], intent["reason"]):
                    self.store.set("exit-intent:" + h["symbol"], None)
        for p in plans:
            q = quotes.get(p["symbol"])
            if not q or p["branch"] == "options":
                continue
            try:
                self.experiments.consider(p, q, brief.get("regime"), now)
                rows = self.store.rows("SELECT state FROM plans WHERE id=?", (p["id"],))
                if not rows or rows[0]["state"] != "approved":
                    continue
                approval = self.store.get("approval:" + p["id"], {})
                if not approval or (now - timestamp(approval["at"])).total_seconds() > 180:
                    self.store.db.execute("UPDATE plans SET state='planned' WHERE id=?", (p["id"],))
                    continue
                if not candidate_filter(
                    p, {"regime": brief.get("regime")}
                ) or not self.experiments.permits(p, brief.get("regime")):
                    continue
                self.engine.enter(p, q, now, close)
                notify(
                    self.config,
                    self.store,
                    "order:" + p["id"],
                    "Trader - paper order submitted",
                    p["symbol"]
                    + " / "
                    + p["branch"]
                    + "\n"
                    + p["thesis"][:350]
                    + "\nSubmission is not a confirmed fill.",
                )
            except ValueError as exc:
                # Record at most once per plan/reason/5-minute interval.
                key = f"entry-block:{p['id']}:{str(exc)}:{now.strftime('%H')}:{now.minute // 5}"
                if not self.store.get(key):
                    self.store.event(
                        "entry_blocked",
                        {"symbol": p["symbol"], "reason": str(exc), "plan_id": p["id"]},
                        p["branch"],
                    )
                    self.store.set(key, True)
        self.experiments.mark(quotes, now)

    def launch_candidate(self, now, close):
        if not self.store.get("readiness", {}).get("execution_verified") or not self.store.get(
            "reconciled"
        ):
            return False
        if self.store.get("brief_day") != now.date().isoformat():
            return False
        quotes = self.store.get("quotes", {})
        for p in self.engine.plans(("planned",)):
            q = quotes.get(p["symbol"])
            if not q or p["branch"] == "options":
                continue
            try:
                self.engine.validate_entry(p, q, now, close)
            except ValueError:
                continue
            key = f"decision:{p['id']}:{now.hour}:{now.minute // 30}"
            context = {
                "plan": p,
                "quote": q,
                "brief": self.store.get("brief", {}),
                "held": self.store.rows("SELECT symbol,branch,qty FROM holdings"),
            }
            if self.launch(key, "decision", context, now.date().isoformat()):
                return True
        return False

    def maybe_publish(self):
        export(self.config, self.store)
        if self.publication_future and self.publication_future.done():
            try:
                self.publication_future.result()
            except Exception as exc:
                self.store.event("publication_failed", {"error_type": type(exc).__name__})
                LOG.warning("Publication deferred: %s", type(exc).__name__)
            self.publication_future = None
        if self.publication_future or time.monotonic() - self.last_publish < 900:
            return
        self.last_publish = time.monotonic()
        self.publication_future = self.publisher_pool.submit(publish_worker, self.config)

    def run(self):
        import fcntl

        self.config.state_dir.mkdir(parents=True, exist_ok=True)
        lock = open(self.config.state_dir / "supervisor.lock", "w")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Supervisor is already running")
        self.store.recover_jobs()
        self.store.event(
            "startup", {"summary": "Local supervisor started; recovering durable state."}
        )

        def stop(*_):
            self.stopping = True

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        while not self.stopping:
            try:
                self.tick()
            except Exception as exc:
                self.store.set("mode", "halted")
                self.store.set("status", "A runtime check failed; new entries are blocked.")
                self.store.set("reconciled", False)
                self.incident(
                    "runtime_" + type(exc).__name__,
                    f"Runtime check failed ({type(exc).__name__}); retrying in 30 seconds.",
                )
                try:
                    export(self.config, self.store)
                except Exception:
                    LOG.exception("Snapshot failed")
            # Clock checks and Python order handling remain available while the
            # worker waits on research. No long sleep inside an agent turn.
            for _ in range(self.config.poll_seconds):
                if self.stopping:
                    break
                time.sleep(1)
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.publisher_pool.shutdown(wait=False, cancel_futures=True)
        lock.close()

    def launch_position_review(self, now):
        for holding in self.store.rows(
            "SELECT * FROM holdings WHERE branch IN ('intraday','swing')"
        ):
            if holding["plan_id"] and holding["plan_id"].startswith("operational-smoke"):
                continue
            key = f"position:{now.date().isoformat()}:{holding['symbol']}:{now.hour}"
            rows = self.store.rows("SELECT payload FROM plans WHERE id=?", (holding["plan_id"],))
            context = {
                "holding": holding,
                "plan": json.loads(rows[0]["payload"]) if rows else None,
                "quote": self.broker.quotes([holding["symbol"]]).get(holding["symbol"]),
                "brief": self.store.get("brief", {}),
                "latest_events": self.store.get("pulses", [])[:2],
                "now": now.isoformat(),
            }
            if self.launch(key, "position_review", context, now.date().isoformat()):
                return True
        return False


def publish_worker(config):
    store = Store(config.state_dir / "trader.sqlite3")
    try:
        return publish(config, store)
    finally:
        store.close()
