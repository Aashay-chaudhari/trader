from __future__ import annotations

import concurrent.futures
import json
import logging
import os
import signal
import tempfile
import time
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

from .agent import CodexRPC, record_application_outcome, run_task
from .broker import Broker
from .config import ET
from .cohorts import ForwardLab
from .engine import (
    Engine, TERMINAL, EXECUTION_KERNEL, current_execution_verified,
    order_id, quote_values, timestamp,
)
from .experiments import Experiments
from .models import (
    Brief,
    Decision,
    MaintenanceProposal,
    Pulse,
    Review,
    PortfolioReview,
    ExplorationReport,
    ResearchValidation,
)
from .notify import notify
from .publish import export, publish
from .research import BASE, UNIVERSE, decision_prompt, market_packet, research_prompt, review_prompt
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


def worker(config, role, context, day, task_key=None):
    store = Store(config.state_dir / "trader.sqlite3")
    try:
        if role == "quota_refresh":
            with CodexRPC(config) as rpc:
                return rpc.rate_limits()
        if role == "accounting_refresh":
            from .accounting import Accounting

            with Broker(config) as broker:
                return Accounting(store).refresh(broker)
        if role == "options_coverage":
            from .options_coverage import run_capture

            with Broker(config) as broker:
                return run_capture(store, broker, context["slot"])
        if role in ("deep_research", "deep_research_review"):
            from .research_work import prepare_task

            prompt, schema = prepare_task(store, context, review=role == "deep_research_review")
            model, effort, searches = config.research_model, "high", 16
        elif role == "research":
            with Broker(config) as broker:
                packet = market_packet(broker, store)
            prompt, schema, model, effort, searches = (
                research_prompt(day, packet, store),
                Brief,
                config.research_model,
                "high",
                24,
            )
        elif role == "exploration":
            from .exploration import exploration_prompt, prepare_screen

            with Broker(config) as broker:
                screen = prepare_screen(config, broker, store)
            prompt, schema, model, effort, searches = (
                exploration_prompt(day, store, screen),
                ExplorationReport,
                config.research_model,
                "high",
                12,
            )
        elif role == "research_validation":
            from .exploration import validation_prompt

            prompt, schema, model, effort, searches = (
                validation_prompt(store),
                ResearchValidation,
                config.research_model,
                "medium",
                6,
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
Return PortfolioReview with one decision per supplied holding. Hold unless the documented thesis is invalidated by current
verified evidence. Exits cannot create a short or reassign ownership. Missing data
means hold with an explicit concern; broker-held protection remains active.
"""
            )
            schema, model, effort, searches = PortfolioReview, config.decision_model, "medium", 0
        elif role == "pulse":
            from .quality import pulse_prompt

            # The background role refreshes research inputs; order protection keeps
            # running in the supervisor. No model tokens are spent on the raw packet.
            with Broker(config) as broker:
                market_packet(broker, store)
            prompt = pulse_prompt(context, store)
            schema, model, effort, searches = Pulse, config.light_model, "low", 3
        elif role in ("retrospective", "weekly", "monthly"):
            date = datetime.fromisoformat(day).date()
            beginning = day
            if role == "weekly":
                beginning = (date - timedelta(days=date.weekday())).isoformat()
            if role == "monthly":
                beginning = date.replace(day=1).isoformat()
            prompt, schema, model, effort, searches = (
                review_prompt(beginning, store, end_day=day)
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
            from .quality import digest

            prompt, schema, model, effort, searches = (
                maintenance_prompt(
                    config, {**context, "research_quality_audit": digest(store, day)}
                ),
                MaintenanceProposal,
                config.maintenance_model,
                "high",
                0,
            )
        else:
            raise ValueError("Unknown role")
        return run_task(
            config, role, prompt, schema, model, effort, day, searches=searches,
            cycles=45 if role in ("research", "deep_research", "deep_research_review") else 25,
            task_key=task_key,
            scope=task_key if role in ("deep_research", "deep_research_review") else None,
        )
    finally:
        store.close()


class Supervisor:
    def __init__(self, config):
        self.config = config
        self.store = self.broker = self.pool = self.publisher_pool = None
        self._closed = False
        try:
            self.store = Store(config.state_dir / "trader.sqlite3")
            self.broker = Broker(config)
            self.engine = Engine(config, self.store, self.broker)
            self.experiments = Experiments(self.store)
            self.cohorts = ForwardLab(self.store)
            from .adaptive_lab import AdaptiveLab

            self.adaptive = AdaptiveLab(self.store)
            if not self.store.get("coverage_tracking_started"):
                self.store.set("coverage_tracking_started", utc_now())
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
        except BaseException as exc:
            try:
                self.close()
            except Exception as cleanup_error:
                exc.add_note("Supervisor initialization cleanup failed: " + type(cleanup_error).__name__)
            raise

    def close(self):
        """Drain owned workers before releasing the HTTP client and SQLite store."""
        if self._closed:
            return
        try:
            if self.pool is not None:
                self.pool.shutdown(wait=True, cancel_futures=True)
        finally:
            if self.publisher_pool is not None:
                self.publisher_pool.shutdown(wait=True, cancel_futures=True)
        self._closed = True
        try:
            if self.broker is not None:
                self.broker.close()
        finally:
            if self.store is not None:
                self.store.close()

    def incident(self, code, reason, details=None):
        LOG.warning("%s: %s", code, reason)
        self.store.event("incident", {"code": code, "reason": reason, **({"operation": details} if details else {})})
        day = datetime.now(ET).date().isoformat()
        notify(
            self.config,
            self.store,
            f"incident:{day}:{code}",
            "Trader - attention required",
            reason,
            urgent=True,
        )

    def cohort_check(self, label, action, default=None):
        # The observational lab must never prevent order protection or closing.
        try:
            return action()
        except Exception as exc:
            key = "cohort-warning:" + datetime.now(ET).date().isoformat() + ":" + label
            if not self.store.get(key):
                self.store.event(
                    "cohort_error",
                    {
                        "summary": "Observational cohort "
                        + label
                        + " deferred ("
                        + type(exc).__name__
                        + "); broker routines continue."
                    },
                )
                self.store.set(key, True)
            LOG.warning("Cohort %s deferred: %s", label, type(exc).__name__)
            return default

    def launch(self, key, role, context, day):
        if (self.config.state_dir / "agent-pause.flag").exists():
            return False
        if self.future or not self.store.job_start(key):
            return False
        self.store.set("active_task", {"key": key, "role": role, "started": utc_now()})
        self.task = (key, role, context, day)
        self.future = self.pool.submit(worker, self.config, role, context, day, key)
        return True

    def finish_task(self):
        if not self.future or not self.future.done():
            return
        key, role, context, day = self.task
        atomic_batch = role in {
            "research", "research_validation", "retrospective", "decision",
            "position_review", "exploration", "weekly", "monthly",
            "deep_research", "deep_research_review", "pulse",
        }
        notifications = []
        application_succeeded = False
        try:
            result = self.future.result()
            original_result = json.loads(json.dumps(result))
            result = json.loads(json.dumps(original_result))
            # These roles apply only local state. Their complete batch, usage
            # outcome and job completion share one commit; notifications follow it.
            with (self.store.transaction() if atomic_batch else nullcontext()):
                if atomic_batch:
                    prior_job = self.store.rows("SELECT state FROM jobs WHERE key=?", (key,))
                    if prior_job and prior_job[0]["state"] == "done":
                        return  # A delayed replay cannot replace a committed brief.
                if role == "quota_refresh":
                    from .budget import account_limit_reason

                    self.store.set("quota", result)
                    self.store.set("quota_refresh_error", None)
                    self.store.set("entry_budget_blocked", (
                        bool(account_limit_reason(result))
                        or not self.store.get("readiness", {}).get("models_available", False)
                    ))
                elif role == "accounting_refresh":
                    self.store.set("accounting_refresh_day", day)
                    self.store.event("accounting_refreshed", {
                        "summary": "Broker activity receipts refreshed; branch cash unchanged.",
                        "fee_count": result.get("fee_count", 0),
                        "cash_bridge": result.get("cash_bridge", {}),
                    })
                elif role == "options_coverage":
                    self.store.event("options_coverage_worker_completed", {
                        "summary": "Bounded indicative options coverage receipts recorded; no execution authority.",
                        "slot": context["slot"], "execution_eligible": False,
                    })
                elif role in ("deep_research", "deep_research_review"):
                    from .research_work import record_analysis, record_review

                    if role == "deep_research":
                        record_analysis(self.store, context, result, day)
                    else:
                        record_review(self.store, context, result, day)
                elif role == "research":
                    # Never allow a research result from another session/date to enter
                    # the live queue. Expired plans remain visible but cannot execute.
                    import hashlib

                    for plan in result["plans"]:
                        active = self.store.get("incumbent_filter:" + plan["branch"])
                        if active:
                            plan["version"] = ("promoted-" + active["id"])[:30]
                        suffix = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()[
                            :8
                        ]
                        plan["id"] = plan["id"][:59] + "-" + suffix
                    plan_ids = [plan["id"] for plan in result["plans"]]
                    if len(plan_ids) != len(set(plan_ids)):
                        raise ValueError("Research must contain distinct plan IDs")
                    # A new brief needs fresh decisions, while immutable terminal
                    # plan states must never be revived by repeating their content.
                    placeholders = ",".join("?" for _ in plan_ids)
                    absent = " AND id NOT IN (" + placeholders + ")" if plan_ids else ""
                    self.store.db.execute(
                        "UPDATE plans SET state='superseded' WHERE state IN ('planned','approved','suspended')" + absent,
                        plan_ids,
                    )
                    if plan_ids:
                        self.store.db.execute(
                            "UPDATE plans SET state='planned' WHERE state='approved' AND id IN (" + placeholders + ")",
                            plan_ids,
                        )
                        if self.store.get("research_refresh_required", False):
                            self.store.db.execute(
                                "UPDATE plans SET state='planned' WHERE state='suspended' AND id IN (" + placeholders + ")",
                                plan_ids,
                            )
                    self.engine.add_plans(result["plans"], day)
                    self.store.set("brief", result)
                    self.store.set("brief_day", day)
                    self.store.set("brief_recorded_at", utc_now())
                    self.store.set("research_refresh_required", False)
                    self.store.set("needs_research", False)
                    self.store.memory_put(
                        "brief:" + day,
                        "observation",
                        result,
                        datetime.fromisoformat(day)
                        .replace(hour=23, minute=59, second=59, tzinfo=ET)
                        .astimezone(UTC)
                        .isoformat(),
                    )
                    self.store.event(
                        "research_completed",
                        {
                            "summary": result["summary"],
                            "plans": len(result["plans"]),
                            "regime": result["regime"],
                        },
                    )
                    notifications.append((
                        "research:" + day,
                        "Trader - morning research ready",
                        result["summary"][:600]
                        + f"\n{len(result['plans'])} plans. Options remain shadow-only.",
                    ))
                elif role == "exploration":
                    from .exploration import record_report

                    record_report(self.store, result, day)
                    self.store.set("exploration_observation_ids", context.get("observation_ids", []))
                elif role == "research_validation":
                    from .exploration import record_validation

                    if context.get("revision") != self.store.get("exploration_draft", {}).get(
                        "revision"
                    ):
                        raise ValueError("Research draft changed while validation was running")
                    record_validation(self.store, result)
                    now = datetime.now(ET)
                    if now.hour < 9 or (now.hour == 9 and now.minute < 25):
                        self.store.set("needs_research", True)
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
                    owners = {
                        h["holding"]["symbol"]: h["holding"]["branch"] for h in context["positions"]
                    }
                    ownership = {h["holding"]["symbol"]: h["holding"] for h in context["positions"]}
                    symbols = [d["symbol"] for d in result["decisions"]]
                    if set(symbols) != set(owners) or len(symbols) != len(set(symbols)):
                        raise ValueError(
                            "Position review must cover every requested symbol exactly once"
                        )
                    seen = set()
                    for decision in result["decisions"]:
                        symbol = decision["symbol"]
                        if symbol not in owners or symbol in seen:
                            raise ValueError("Position review contains an unknown/duplicate symbol")
                        seen.add(symbol)
                        self.store.event("decision", decision, owners[symbol])
                        if (
                            decision["action"] == "exit"
                            and decision["evidence_fresh"]
                            and decision["invalidation_observed"]
                        ):
                            self.store.set(
                                "exit-intent:" + symbol,
                                {
                                    "at": utc_now(),
                                    "reason": decision["reason"],
                                    "plan_id": ownership[symbol].get("plan_id"),
                                    "branch": owners[symbol],
                                },
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
                        self.store.set("research_refresh_required", True)
                        self.store.db.execute(
                            "UPDATE plans SET state='suspended' WHERE state IN ('planned','approved')"
                        )
                        self.store.set("needs_research", True)
                        for order in self.store.rows("SELECT * FROM orders WHERE side='buy'"):
                            if order["status"] not in TERMINAL:
                                self.queue_pulse_cancellation(order, key, result["at"])
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
                    for i, proposal in enumerate(result["code_changes"]):
                        self.store.memory_put(
                            f"{day}:improvement:{i}",
                            "improvement_proposal",
                            {
                                **proposal,
                                "state": "proposed",
                                "evidence_day": day,
                                "authority": "Recorded for developer review; does not expand automated maintenance scope",
                            },
                        )
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
                                {"id": proposal.get("id"), "reason": "Invalid or incomplete evaluation contract"},
                            )
                    for exp in self.experiments.evaluate():
                        notifications.append((
                            "promotion:" + exp,
                            "Trader - strategy promoted",
                            exp + " passed its recorded forward-evaluation gates.",
                        ))
                elif role == "maintenance":
                    from .maintenance import stage_change

                    stage_change(self.config, self.store, result)
                completed = self.store.job_end(key, True, {"role": role, "completed": utc_now()})
                if atomic_batch and not completed:
                    raise RuntimeError("Result application lost its job claim")
                if role not in ("quota_refresh", "accounting_refresh", "options_coverage"):
                    record_application_outcome(self.store, key, "accepted")
            application_succeeded = True
        except Exception as exc:
            notifications.clear()
            if "original_result" in locals() and role not in ("quota_refresh", "accounting_refresh", "options_coverage"):
                record_application_outcome(
                    self.store, key, "rejected", getattr(exc, "validation_code", None)
                )
            if role in ("deep_research", "deep_research_review"):
                from .research_work import record_failure

                record_failure(self.store, key, exc, datetime.now(ET))
            if "original_result" in locals() and role not in ("quota_refresh", "accounting_refresh", "options_coverage"):
                try:
                    self.record_quality(day, role, original_result, key, "rejected")
                except Exception as capture_error:
                    LOG.warning("Rejected-result quality capture deferred: %s", type(capture_error).__name__)
            if role in ("research", "decision", "position_review", "pulse"):
                self.store.set("entry_budget_blocked", True)
            if role == "research":
                self.store.set("needs_research", True)
            self.store.job_end(key, False, {"error_type": type(exc).__name__})
            if role == "quota_refresh":
                self.store.set("quota", {"at": utc_now(), "windows": [], "ordinary_usage_allowed": False})
                self.store.set("quota_refresh_error", type(exc).__name__)
                self.store.set("entry_budget_blocked", True)
            else:
                self.incident(
                    "agent_" + role,
                    f"{role.title()} did not complete ({type(exc).__name__}). Protective routines continue; new plans require valid research.",
                )
        finally:
            self.future = None
            self.task = None
            self.store.set("active_task", None)
        if application_succeeded and role not in ("quota_refresh", "accounting_refresh", "options_coverage"):
            try:
                self.record_quality(day, role, original_result, key, "applied")
            except Exception as exc:
                LOG.warning("Completed-result quality capture deferred: %s", type(exc).__name__)
        for notification in notifications:
            try:
                notify(self.config, self.store, *notification)
            except Exception as exc:
                # A delivery failure after commit does not undo a valid result.
                LOG.warning("Completed-result notification deferred: %s", type(exc).__name__)

    def record_quality(self, day, role, result, key, outcome):
        from .quality import record_artifact, daily_audit

        try:
            record_artifact(self.store, day, role, result, key, outcome)
            daily_audit(self.store, day, persist=True)
        except Exception as exc:
            LOG.warning("Research-quality capture deferred: %s", type(exc).__name__)

    def queue_pulse_cancellation(self, order, task_key, observed_at):
        """Persist exact owned identity inside the pulse's local transaction."""
        from .observation_audit import content_hash

        identity = {key: order[key] for key in (
            "client_id", "broker_id", "branch", "symbol", "side", "plan_id", "qty",
        )}
        key = "pulse-cancellation:" + content_hash(identity)
        if self.store.get(key) is None:
            state = "pending" if identity["broker_id"] else "unresolved"
            self.store.set(key, {
                "version": "pulse-cancellation-v1", "identity": identity,
                "task_key": task_key, "created_at": observed_at, "state": state,
                "attempts": 0, "last_attempt_at": None, "next_retry_at": None,
                "reason": None if identity["broker_id"] else "missing_broker_identity",
            })
            self.store.event("pulse_cancellation_queued", {"reference": key, "state": state})

    def apply_pulse_cancellations(self, now):
        """Deliver durable cancellation requests, never inferred cancellations."""
        started = time.monotonic()
        for row in self.store.rows(
            "SELECT key FROM kv WHERE key LIKE 'pulse-cancellation:%' "
            "AND json_extract(value,'$.state') IN ('pending','attempting','requested','uncertain') "
            "ORDER BY key"
        ):
            try:
                attempt_now = now + timedelta(seconds=max(0, time.monotonic() - started))
                self._deliver_pulse_cancellation(row["key"], attempt_now)
            except Exception as exc:
                # A DB/transport fault on one intent must not skip its siblings.
                LOG.warning("Pulse cancellation delivery deferred: %s", type(exc).__name__)

    def _deliver_pulse_cancellation(self, key, now):
        started = time.monotonic()
        with self.store.transaction():
            intent = self.store.get(key)
            if not intent or intent["state"] not in ("pending", "attempting", "requested", "uncertain"):
                return
            identity = intent["identity"]
            orders = self.store.rows("SELECT * FROM orders WHERE client_id=?", (identity["client_id"],))
            now = now + timedelta(seconds=max(0, time.monotonic() - started))
            if not orders or not identity["broker_id"] or any(
                orders[0].get(field) != value for field, value in identity.items()
            ):
                self.store.set(key, {**intent, "state": "unresolved", "reason": "owned_identity_unavailable_or_changed"})
                self.store.event("pulse_cancellation_unresolved", {"reference": key, "reason": "owned_identity_unavailable_or_changed"})
                return
            if orders[0]["status"] in TERMINAL:
                self.store.set(key, {**intent, "state": "terminal", "observed_status": orders[0]["status"], "confirmed_at": now.isoformat()})
                self.store.event("pulse_cancellation_terminal", {"reference": key, "observed_status": orders[0]["status"]})
                return
            if intent.get("next_retry_at") and now < timestamp(intent["next_retry_at"]):
                return
            attempt = intent["attempts"] + 1
            intent = {**intent, "state": "attempting", "attempts": attempt,
                      "last_attempt_at": now.isoformat(),
                      "next_retry_at": (now + timedelta(seconds=60)).isoformat(), "reason": None}
            self.store.set(key, intent)
        # Commit the attempt before HTTP so restart preserves the cooldown even
        # if the request or its acknowledgement is lost. No entry is submitted.
        outcome, error_type = "requested", None
        try:
            self.broker.cancel(identity["broker_id"])
        except Exception as exc:
            outcome, error_type = "uncertain", type(exc).__name__
        try:
            with self.store.transaction():
                current = self.store.get(key)
                if current != intent:
                    raise RuntimeError("Pulse cancellation attempt changed during delivery")
                if outcome == "uncertain":
                    self.store.set("entry_budget_blocked", True)
                self.store.set(key, {**intent, "state": outcome, "error_type": error_type})
                self.store.event("pulse_cancellation_attempt", {
                    "reference": key, "attempt": attempt, "outcome": outcome,
                    "error_type": error_type,
                    "summary": "Cancellation request only; terminal broker state requires reconciliation.",
                })
        except Exception:
            # Preserve the prior failure gate if an external request happened
            # but its outcome could not be retained. Quota refresh may later
            # clear this flag; owned pending-order reservations remain separate.
            self.store.set("entry_budget_blocked", True)
            raise

    def launch_deep_research(self, now):
        """Useful off-hours work; fresh quota is checked again in the worker."""
        from .budget import budget_check
        from .research_work import next_work

        if self.future or (self.config.state_dir / "agent-pause.flag").exists():
            return False
        quota = self.store.get("quota", {})
        try:
            age = (now - timestamp(quota["at"])).total_seconds()
        except (KeyError, TypeError, ValueError):
            age = float("inf")
        if age < -60 or age > 900:
            # Meter refresh is read-only and runs on the background executor.
            return self.launch(
                "quota-refresh:" + now.strftime("%Y-%m-%d:%H:") + str(now.minute // 5),
                "quota_refresh", {}, now.date().isoformat(),
            )
        day = now.date().isoformat()
        if self.store.get("accounting_refresh_day") != day:
            key = "accounting-refresh:" + day
            prior = self.store.rows("SELECT state,attempts,at FROM jobs WHERE key=?", (key,))
            due = not prior or (
                prior[0]["state"] in ("failed", "retry")
                and (now - timestamp(prior[0]["at"])).total_seconds() >= 1800
            )
            if due and self.launch(key, "accounting_refresh", {}, day):
                return True
        work = next_work(self.store, now)
        if not work:
            return False
        allowed, reason = budget_check(self.store, quota, work["role"], now)
        self.store.set("background_budget", {"at": now.isoformat(), "allowed": allowed, "reason": reason})
        if not allowed:
            return False
        return self.launch(work["key"], work["role"], work["context"], now.date().isoformat())

    def launch_period(self, role, day):
        from .quality import derive_period, record_artifact, daily_audit

        result = derive_period(self.store, role, day)
        if result is None:
            return self.launch(role + ":" + day, role, {}, day)
        key = role + ":" + day
        if not self.store.job_start(key):
            return False
        self.store.set(key, result)
        self.store.event(
            "period_review",
            {"period": role, "summary": result["summary"], "derived_from": result["derived_from"]},
        )
        self.store.job_end(key, True, {"derived_from": result["derived_from"], "model_call": False})
        self.cohort_check(
            "derived_review_capture",
            lambda: record_artifact(
                self.store, day, role, result, key, origin="derived_period_review"
            ),
        )
        self.cohort_check(
            "research_quality_audit", lambda: daily_audit(self.store, day, persist=True)
        )
        return True

    def model_quota_state(self, now):
        """Classify model admission without confusing unknown metadata with a limit."""
        from .budget import account_limit_reason

        quota = self.store.get("quota", {})
        try:
            age = (now - timestamp(quota["at"])).total_seconds()
        except (KeyError, TypeError, ValueError):
            return "unknown"
        windows = quota.get("windows")
        if not -60 <= age <= 900 or not isinstance(windows, list) or not windows:
            return "unknown"
        ceilings = {
            "20% account reserve reached", "Short-window quota nearly exhausted",
        }
        # Validate every bucket even when an earlier bucket already hits a limit.
        reasons = [account_limit_reason({**quota, "windows": [window]}, now) for window in windows]
        if any(reason not in ceilings | {None, "Weekly quota window unavailable"} for reason in reasons):
            return "unknown"
        if not any(window["windowDurationMins"] >= 10000 for window in windows):
            return "unknown"
        return "blocked" if any(reason in ceilings for reason in reasons) else "ready"

    def fresh_quota_blocks_models(self, now):
        return self.model_quota_state(now) == "blocked"

    def launch_options_coverage(self, now, close):
        from .options_coverage import capture_admission, public_summary

        if self.future or not self.store.get("market_open") or now >= close - timedelta(minutes=12):
            return False
        slot = self.cohort_check("options coverage due", lambda: capture_admission(self.store, now))
        if slot is None:
            return False
        # Metadata refresh never needs model inference. Known blocked model work
        # cannot consume this preregistered, data-only collection window.
        quota_state = self.model_quota_state(now)
        if quota_state == "unknown":
            return self.launch("quota-refresh:" + now.strftime("%Y-%m-%d:%H:") + str(now.minute // 5),
                               "quota_refresh", {}, now.date().isoformat())
        if quota_state == "ready" and self.launch_candidate(now, close):
            return True
        summary = public_summary(self.store)
        return self.launch("options-coverage:" + summary["registration_id"] + ":" + str(slot),
                           "options_coverage", {"slot": slot}, now.date().isoformat())

    def preflight(self):
        good = self.engine.reconcile()
        readiness = self.store.get("readiness", {})
        account = self.store.get("account", {})
        funded = (
            abs(float(account.get("equity", 0)) - 30000) < 1
            if not self.store.rows("SELECT * FROM orders")
            else True
        )
        available = []
        quota = {"windows": [], "ordinary_usage_allowed": False}
        try:
            with CodexRPC(self.config) as rpc:
                quota = rpc.rate_limits()
                self.store.set("quota", quota)
                available = [m.get("id") for m in rpc.models()]
        except Exception as exc:
            self.store.set(
                "quota", {"at": utc_now(), "windows": [], "error_type": type(exc).__name__}
            )
            self.store.event(
                "budget_skip",
                {"role": "preflight", "reason": "CLI unavailable; Python protection continues"},
            )
        models_ok = all(
            m in available
            for m in (
                self.config.research_model,
                self.config.decision_model,
                self.config.light_model,
                self.config.maintenance_model,
            )
        )
        from .budget import account_limit_reason

        quota_blocked = bool(account_limit_reason(quota))
        self.store.set("entry_budget_blocked", not models_ok or quota_blocked)
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
                "required_execution_kernel": EXECUTION_KERNEL,
            }
        )
        self.store.set("readiness", readiness)
        return good and funded and models_ok and not quota_blocked

    def smoke(self, now, opened, close):
        started, observed_at = time.monotonic(), now
        r = self.store.get("readiness", {})
        if current_execution_verified(r):
            return True
        if now < opened or now >= close:
            return False
        if r.get("required_execution_kernel", EXECUTION_KERNEL) != EXECUTION_KERNEL:
            return False  # This binary cannot certify another required release.
        day = now.date().isoformat()
        key = "smoke:" + day
        stage = self.store.get(key, {})
        if not stage:
            def new_stage_ready(at):
                ready = self.store.get("readiness", {})
                try:
                    reconciliation_age = (at - timestamp(self.store.get("last_reconciled"))).total_seconds()
                except (TypeError, ValueError):
                    return False
                return (
                    self.config.execution
                    and not self.store.get("entry_budget_blocked", False)
                    and day >= self.config.start_date
                    and at.date().isoformat() == day
                    and opened + timedelta(minutes=2) <= at <= close - timedelta(minutes=40)
                    and self.store.get("reconciled")
                    and -5 <= reconciliation_age <= 90
                    and ready.get("funded")
                    and ready.get("models_available")
                    and ready.get("required_execution_kernel", EXECUTION_KERNEL) == EXECUTION_KERNEL
                    and not current_execution_verified(ready)
                    and not self.store.get(key)
                    and not self.store.rows("SELECT symbol FROM holdings")
                )

            if not new_stage_ready(now):
                return False
            if self.broker.orders():
                return False  # operational round-trip starts only from a flat account
            now = observed_at + timedelta(seconds=max(0, time.monotonic() - started))
            if not new_stage_ready(now):
                return False
            q = self.broker.quotes(["SPY"]).get("SPY", {})
            # Order/quote lookups can consume the quote's remaining lifetime or
            # cross the entry cutoff. Recheck local admission at receipt time;
            # a quota update while those requests run cannot authorize an entry.
            now = observed_at + timedelta(seconds=max(0, time.monotonic() - started))
            if not new_stage_ready(now):
                return False
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
            # Persist the bounded operational intent before submission, including
            # timeout/response-loss recovery. This is not a strategy-plan exemption.
            self.store.set(
                key,
                {
                    "at": now.isoformat(),
                    "state": "submitted",
                    "expires_at": (now + timedelta(minutes=2)).isoformat(),
                    "entry_client_id": payload["client_order_id"],
                    "execution_kernel": EXECUTION_KERNEL,
                },
            )
            self.engine.submit_intent(payload, "intraday", "operational-smoke-" + day)
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
        deadline = (
            timestamp(stage["expires_at"])
            if stage.get("expires_at")
            else timestamp(stage["at"]) + timedelta(minutes=2)
        )
        if order["filled"] > 0:
            self.engine.close_intraday()
            reconciled = self.engine.reconcile()
            exits = self.store.rows(
                "SELECT filled FROM orders WHERE symbol='SPY' AND side='sell' AND branch='intraday' AND plan_id IN (?,?,?)",
                ("operational-smoke-" + day, "close:" + day + ":SPY", "exit:" + day + ":SPY"),
            )
            if (
                reconciled
                and stage.get("execution_kernel") == EXECUTION_KERNEL
                and order["filled"] == 1
                and sum(e["filled"] for e in exits) == 1
                and not self.store.rows("SELECT * FROM holdings WHERE branch='intraday'")
                and not [o for o in self.broker.orders() if o["symbol"] == "SPY"]
            ):
                verified_at = utc_now()
                history = self.store.get("execution_verification_history", [])
                if r.get("execution_verified") and r.get("execution_verified_at") and not history:
                    history.append({
                        "kernel": r.get("verified_execution_kernel", "legacy_unversioned"),
                        "verified_at": r["execution_verified_at"],
                        "basis": "Prior persisted verification; original order receipts remain retained.",
                    })
                r["execution_verified"] = True
                if not r.get("execution_verified_at"):
                    r["execution_verified_at"] = verified_at
                r["verified_execution_kernel"] = EXECUTION_KERNEL
                r["verified_execution_kernel_at"] = verified_at
                receipt = {
                    "kernel": EXECUTION_KERNEL, "verified_at": verified_at, "day": day,
                    "entry_filled_qty": 1, "exit_filled_qty": 1,
                    "basis": "Broker-confirmed bounded paper round-trip and reconciliation.",
                }
                with self.store.transaction():
                    self.store.set("readiness", r)
                    self.store.set("execution_verification_history", [*history, receipt])
                    self.store.set(
                        key,
                        {
                            **stage, "state": "passed", "verified_at": verified_at,
                            "entry_filled_qty": 1, "exit_filled_qty": 1,
                        },
                    )
                    self.store.event(
                        "execution_check",
                        {
                            "summary": "One-share paper entry and exit fills reconciled; execution gate passed.",
                            "day": day, "execution_kernel": EXECUTION_KERNEL,
                            "entry_filled_qty": 1, "exit_filled_qty": 1,
                        },
                    )
                notify(
                    self.config,
                    self.store,
                    "smoke:" + day,
                    "Trader - paper execution verified",
                    "One-share paper entry, broker fill, closing fill and reconciliation passed. Equity paper pilots can now operate.",
                )
                return True
        elif order["status"] in TERMINAL:
            if stage.get("state") != "unfilled":
                self.store.set(
                    key,
                    {
                        **stage,
                        "state": "unfilled",
                        "entry_order_status": order["status"],
                        "confirmed_at": self.store.get("last_reconciled"),
                        "reason": stage.get("reason", "entry_terminated_without_fill"),
                    },
                )
                self.store.event(
                    "execution_check",
                    {
                        "summary": "Paper execution check ended without a fill; broker entry status confirmed as "
                        + order["status"]
                        + ". Gate remains pending.",
                        "day": day,
                        "order_status": order["status"],
                    },
                )
            notify(
                self.config,
                self.store,
                "smoke-unfilled:" + day,
                "Trader - research/shadow mode",
                "Execution check ended without a fill. Broker entry status: "
                + order["status"]
                + ". Pilots remain disabled.",
            )
        elif now >= deadline:
            if order["broker_id"] and order["status"] not in TERMINAL:
                if stage.get("state") != "cancel_requested":
                    self.broker.cancel(order["broker_id"])
                    self.store.set(
                        key,
                        {
                            **stage,
                            "state": "cancel_requested",
                            "cancel_requested_at": now.isoformat(),
                            "reason": "execution_check_timeout",
                        },
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
        tick_started = time.monotonic()
        now = now or datetime.now(ET)
        now = now.astimezone(ET)
        tick_time = now
        day = now.date().isoformat()
        self.store.set("heartbeat", now.isoformat())
        self.cohort_check("expiry", lambda: self.cohorts.expire(now))
        self.cohort_check("adaptive expiry", lambda: self.adaptive.expire(now))
        from .options_coverage import due_capture

        self.cohort_check("options coverage deadlines", lambda: due_capture(self.store, now))
        # The Windows watchdog reads this directly even when Pages/export fail.
        self.config.state_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", dir=self.config.state_dir, suffix=".tmp", delete=False
        ) as handle:
            json.dump({"at": now.isoformat(), "pid": os.getpid(), "schema": 1}, handle)
            heartbeat_temp = handle.name
        os.replace(heartbeat_temp, self.config.state_dir / "heartbeat.json")
        self.finish_task()
        if self.store.retry_failed_jobs((now.astimezone(UTC) - timedelta(minutes=30)).isoformat()):
            self.store.set("needs_research", True)
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
            self.apply_pulse_cancellations(tick_time + timedelta(seconds=max(0, time.monotonic() - tick_started)))
            self.maybe_publish()
            return
        if not times:
            valid = self.engine.reconcile()
            # A successful weekend check must clear a prior transient halt label,
            # while an actual mismatch must remain visible and block entries.
            self.store.set("mode", "market_closed" if valid else "halted")
            self.store.set("market_open", False)
            quota_state = self.model_quota_state(now)
            status = "Market closed. Reconciliation failed; new entries remain blocked."
            next_action = "Next trading session: automatic startup and calendar refresh."
            if valid:
                if quota_state == "blocked":
                    status = "Market holiday or weekend. Reconciled Python monitoring continues; model work and new entries await quota admission."
                    next_action = "Continue monitoring and recheck quota admission before new model work or entries."
                elif quota_state == "unknown":
                    status = "Market holiday or weekend. Reconciled Python monitoring continues; model quota admission is unknown."
                    next_action = "Refresh quota metadata before admitting new model work or entries."
                else:
                    status = "Market holiday or weekend. Reconciled; background research is available."
            self.store.set("status", status)
            self.store.set("next_action", next_action)
            self.engine.cancel_entries(now, now + timedelta(days=1))
            self.apply_pulse_cancellations(tick_time + timedelta(seconds=max(0, time.monotonic() - tick_started)))
            self.cohort_check("background research", lambda: self.launch_deep_research(now))
            self.maybe_publish()
            return
        opened, close = times
        valid = self.engine.reconcile(now)
        if valid:
            from .intelligence import record_reconciled_equity

            self.cohort_check("performance receipt", lambda: record_reconciled_equity(self.store))
        self.engine.cancel_entries(now, close)
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
        pilot = (
            valid
            and current_execution_verified(ready)
            and self.config.execution
            and not self.store.get("entry_budget_blocked", False)
        )
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
        # Reconciliation and notification requests can take tens of seconds.
        # Advance the supplied clock by monotonic elapsed time, preserving
        # deterministic test clocks without mistaking request latency for drift.
        now = tick_time + timedelta(seconds=max(0, time.monotonic() - tick_started))
        if now >= opened and now < close:
            clock = self.broker.clock()
            now = tick_time + timedelta(seconds=max(0, time.monotonic() - tick_started))
            market_open = bool(clock.get("is_open"))
            clock_age = abs((now - timestamp(clock["timestamp"])).total_seconds())
            self.store.set("market_open", market_open and clock_age <= 30 and now < close)
            if clock_age > 30:
                self.incident(
                    "clock_drift", "Local and broker clocks disagree. New entries blocked."
                )
            if not self.store.get("market_open"):
                self.store.set("mode", "halted")
                self.store.set(
                    "status",
                    "Broker session/clock does not confirm the calendar. New entries and market exits deferred.",
                )
                self.incident(
                    "broker_clock",
                    "Broker session or clock disagrees with the calendar. Existing broker protection remains in place.",
                )
                self.apply_pulse_cancellations(tick_time + timedelta(seconds=max(0, time.monotonic() - tick_started)))
                self.maybe_publish()
                return
            slot = int((now - opened).total_seconds() // 300)
            self.cohort_check(
                "session_health",
                lambda: self.store.db.execute(
                    "INSERT OR REPLACE INTO session_health VALUES(?,?,?,?,?)",
                    (day, slot, now.isoformat(), 1, int(self.store.get("brief_day") == day)),
                ),
            )
            overdue = self.engine.overdue_intraday(now)
            if overdue:
                self.store.set("mode", "halted")
                self.store.set("status", "Recovering intraday exposure carried beyond its entry session.")
                self.store.set("next_action", "Verify paper exit fills and reconciliation before resuming entries.")
                self.engine.close_intraday()
                self.apply_pulse_cancellations(tick_time + timedelta(seconds=max(0, time.monotonic() - tick_started)))
                self.maybe_publish()
                return
            if (not current_execution_verified(ready) and self.store.get("market_open")
                    and now < close - timedelta(minutes=12)):
                try:
                    self.smoke(now, opened, close)
                except Exception as exc:
                    self.incident(
                        "smoke",
                        f"Paper execution check deferred ({type(exc).__name__}); entries remain blocked.",
                    )
            def session_deadline_reached(at):
                if at >= close:
                    self.store.set("market_open", False)
                    self.store.set("status", "Market closed while broker checks were pending. Existing protection retained.")
                    self.store.set("next_action", "After-close reconciliation and recovery review.")
                    if self.store.rows("SELECT symbol FROM holdings WHERE branch='intraday'"):
                        self.incident(
                            "unclosed_intraday",
                            "Intraday holdings remain after the close. Broker-held protection remains; immediate inspection required.",
                        )
                    return True
                if at >= close - timedelta(minutes=12):
                    self.store.set("status", "Closing intraday positions and verifying fills.")
                    self.store.set("next_action", "After-close reconciliation and daily results.")
                    self.engine.close_intraday()
                    self.finish_shadow(at, closing=True)
                    return True
                return False

            now = tick_time + timedelta(seconds=max(0, time.monotonic() - tick_started))
            if not session_deadline_reached(now):
                attempted_exits = self.apply_pending_exits(now)
                now = tick_time + timedelta(seconds=max(0, time.monotonic() - tick_started))
                if not session_deadline_reached(now):
                    self.engine.ensure_protection()
                    now = tick_time + timedelta(seconds=max(0, time.monotonic() - tick_started))
                    if not session_deadline_reached(now):
                        self.store.set(
                            "status",
                            "Monitoring the session. Agent reviews material changes and eligible setups.",
                        )
                        self.store.set(
                            "next_action",
                            f"Intraday closing routine at {(close - timedelta(minutes=12)).strftime('%H:%M')} ET.",
                        )
                        self.market_tick(now, close, attempted_exits)
        elif now >= close:
            self.store.set("market_open", False)
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
        self.apply_pulse_cancellations(tick_time + timedelta(seconds=max(0, time.monotonic() - tick_started)))
        if not self.future:
            if now >= opened.replace(hour=8, minute=15) and now < close - timedelta(minutes=45):
                if now >= opened and self.model_quota_state(now) != "ready" and self.launch_options_coverage(now, close):
                    pass  # A blocked model job cannot consume this fixed data window.
                elif self.store.get("brief_day") != day:
                    self.launch("research:" + day, "research", {}, day)
                elif now >= opened and self.launch_position_review(now):
                    pass
                elif now >= opened and self.launch_options_coverage(now, close):
                    pass
                elif (
                    not self.engine.plans()
                    and 9 * 60 + 45 <= now.hour * 60 + now.minute < 10 * 60 + 15
                    and self.launch("fresh-open-research:" + day, "research", {}, day)
                ):
                    pass
                elif self.pending_research_validation(day):
                    pass
                elif self.launch_exploration(now, close):
                    pass
                elif self.store.get("needs_research") and self.launch(
                    "refresh:" + day + ":" + now.strftime("%H"), "research", {}, day
                ):
                    self.store.set("needs_research", False)
                elif now >= opened and now < close - timedelta(minutes=30):
                    if not self.launch_position_review(now) and not self.launch_candidate(
                        now, close
                    ):
                        minutes = now.hour * 60 + now.minute
                        exposed = bool(
                            self.engine.plans() or self.store.rows("SELECT symbol FROM holdings")
                        )
                        for checkpoint in (11 * 60, 13 * 60, 14 * 60 + 30):
                            if not exposed and checkpoint != 13 * 60:
                                continue  # one focused midday context pulse when no exposure/plans
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
                    from .quality import daily_audit

                    self.cohort_check(
                        "research_quality_audit", lambda: daily_audit(self.store, day, persist=True)
                    )
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
                self.launch_period("weekly", day)
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
                    self.launch_period("monthly", day)
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
        # Leave the single worker free for morning and market-session priorities.
        # After-close reviews above receive first priority; overnight work stops
        # launching 45 minutes before the morning research window.
        if not self.future and (now.hour < 7 or now >= close + timedelta(minutes=90)):
            self.cohort_check("background research", lambda: self.launch_deep_research(now))
        self.maybe_publish()

    def finish_shadow(self, now, closing=False):
        symbols = [x["symbol"] for x in self.store.rows("SELECT * FROM shadow WHERE state='open'")]
        cohort_symbols = self.cohort_check(
            "symbols", lambda: self.cohorts.symbols(now.date().isoformat()), set()
        )
        adaptive_symbols = self.cohort_check("adaptive symbols", self.adaptive.symbols, set())
        quotes = self.broker.quotes(
            sorted(set(symbols) | cohort_symbols | adaptive_symbols | {"SPY"})
        )
        self.experiments.mark(quotes, now, closing=closing)
        self.cohort_check("mark", lambda: self.cohorts.mark(quotes, now))
        self.cohort_check("adaptive mark", lambda: self.adaptive.mark(quotes, now))
        self.benchmarks(quotes, now)

    def apply_exit_intent(self, holding, now, attempted_exits):
        # An already validated exit is bound to the current holding identity;
        # executing it requires broker reconciliation, not another quote fetch.
        # Keep its intent when cancellation/submission is pending or fails.
        key = "exit-intent:" + holding["symbol"]
        intent = self.store.get(key)
        if intent and (
            intent.get("plan_id") != holding["plan_id"]
            or intent.get("branch") != holding["branch"]
        ):
            self.store.set(key, None)
            return
        if (intent and holding["symbol"] not in attempted_exits
                and 0 <= (now - timestamp(intent["at"])).total_seconds() < 300):
            attempted_exits.add(holding["symbol"])
            if self.engine.exit_holding(holding["symbol"], intent["reason"]):
                self.store.set(key, None)

    def apply_pending_exits(self, now, attempted_exits=None):
        attempted_exits = set() if attempted_exits is None else attempted_exits
        for holding in self.store.rows("SELECT * FROM holdings"):
            self.apply_exit_intent(holding, now, attempted_exits)
        return attempted_exits

    def market_tick(self, now, close, attempted_exits=None):
        market_started, market_time = time.monotonic(), now
        attempted_exits = self.apply_pending_exits(now, attempted_exits)
        plans = self.engine.plans()
        exploration_plans = self.store.get("exploration_shadow_plans", [])
        cohort_symbols = self.cohort_check(
            "symbols", lambda: self.cohorts.symbols(now.date().isoformat()), set()
        )
        adaptive_symbols = self.cohort_check("adaptive symbols", self.adaptive.symbols, set())
        symbols = sorted(
            {p["symbol"] for p in plans + exploration_plans}
            | {h["symbol"] for h in self.store.rows("SELECT * FROM holdings")}
            | {"SPY", "QQQ", "TLT"}
            | {x["symbol"] for x in self.store.rows("SELECT * FROM shadow WHERE state='open'")}
            | cohort_symbols
            | adaptive_symbols
            | set(UNIVERSE)
        )
        quotes = self.broker.quotes(symbols)
        now = market_time + timedelta(seconds=max(0, time.monotonic() - market_started))
        self.store.set("quotes", quotes)
        if now >= close:
            self.store.set("market_open", False)
            return
        calendar = self.store.get("calendar:" + now.date().isoformat(), [])
        session = session_times(calendar, now.date().isoformat())
        self.benchmarks(quotes, now)
        brief = self.store.get("brief", {})
        self.cohort_check(
            "filter sampling funnel",
            lambda: self.experiments.record_funnel(plans, exploration_plans, quotes, now),
        )
        from agent_trader.strategies.adaptive import candidate_filter

        for h in self.store.rows("SELECT * FROM holdings"):
            plan_rows = self.store.rows("SELECT payload FROM plans WHERE id=?", (h["plan_id"],))
            q = quotes.get(h["symbol"])
            if plan_rows and q:
                try:
                    bid, _ = quote_values(q, now)
                    owned_plan = json.loads(plan_rows[0]["payload"])
                    if bid >= owned_plan["target"] and h["symbol"] not in attempted_exits:
                        self.store.set(
                            "exit-intent:" + h["symbol"],
                            {
                                "at": now.isoformat(),
                                "reason": "Recorded target reached on a fresh quote",
                                "plan_id": h["plan_id"],
                                "branch": h["branch"],
                            },
                        )
                except ValueError:
                    pass
                self.apply_exit_intent(h, now, attempted_exits)
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
        for p in exploration_plans:
            q = quotes.get(p["symbol"])
            if not q or p["branch"] == "options" or not p.get("event_risk_known"):
                continue
            try:
                if any(
                    timestamp(e["observed_at"]).tzinfo is None
                    or not now - timedelta(hours=24)
                    <= timestamp(e["observed_at"])
                    <= now + timedelta(minutes=5)
                    for e in p["evidence"]
                ):
                    continue
                self.experiments.consider(p, q, brief.get("regime"), now)
            except (ValueError, KeyError, TypeError):
                continue
        self.experiments.mark(quotes, now)
        if session:
            self.cohort_check(
                "entry observations", lambda: self.cohorts.observe(quotes, now, *session)
            )
            self.cohort_check("mark", lambda: self.cohorts.mark(quotes, now))
            self.cohort_check(
                "adaptive observations", lambda: self.adaptive_tick(quotes, now, *session)
            )

    def adaptive_tick(self, quotes, now, opened, closed):
        from .intelligence import capture_observations

        packet = self.store.get("market_packet", {})
        key = (
            "observation-slot:"
            + now.date().isoformat()
            + ":"
            + str(int((now - opened).total_seconds() // 900))
        )
        if not self.store.get(key):
            captured_packet = {
                "observed_at": now.isoformat(),
                "capture_mode": "quote_monitor",
                "data_feed": packet.get("data_feed", "Alpaca free IEX"),
                "universe": sorted(quotes),
                "daily_indicators": packet.get("daily_indicators", {}),
                "market": {s: {"latestQuote": q} for s, q in quotes.items()},
            }
            self.store.memory_put(
                "research-input:" + now.isoformat(),
                "research_input",
                {
                    "day": now.date().isoformat(),
                    "observed_at": now.isoformat(),
                    "packet": captured_packet,
                    "origin": "quarter_hour_quote_observation",
                },
            )
            capture_observations(self.store, captured_packet, now=now)
            self.store.set(key, True)
        if self.adaptive.symbols():
            key = "adaptive-calendar:" + now.date().isoformat()
            sessions = self.store.get(key)
            if sessions is None:
                rows = self.store.rows(
                    "SELECT registered_at FROM adaptive_contracts ORDER BY registered_at LIMIT 1"
                )
                earliest = (
                    timestamp(rows[0]["registered_at"]).astimezone(ET).date()
                    if rows
                    else now.date()
                )
                sessions = self.broker.calendar_range(
                    (earliest - timedelta(days=10)).isoformat(),
                    (now.date() + timedelta(days=120)).isoformat(),
                )
                self.store.set(key, sessions)
            self.adaptive.observe(quotes, packet, now, opened, closed, sessions)
        self.adaptive.mark(quotes, now)

    def pending_research_validation(self, day):
        draft = self.store.get("exploration_draft", {})
        revision = draft.get("revision")
        if revision and self.store.get("exploration_validated_draft") != revision:
            return self.launch(
                "research-validation:" + revision,
                "research_validation",
                {"revision": revision},
                day,
            )
        return False

    def launch_exploration(self, now, close):
        from .exploration import sprint_active
        from .intelligence import observation_context

        day = now.date().isoformat()
        ids = [r["id"] for r in observation_context(self.store).get("records", [])]
        new_observations = bool(set(ids) - set(self.store.get("exploration_observation_ids", [])))
        stale_cards = any(
            c.get("expires_at") and timestamp(c["expires_at"]) <= now
            for c in self.store.get("research_catalogue", [])
            if c.get("state") == "reviewed_for_testing"
        )
        if (
            (sprint_active(self.store) or new_observations or stale_cards or now.weekday() == 0)
            and self.store.get("exploration_day") != day
            and now >= now.replace(hour=8, minute=35, second=0, microsecond=0)
            and now
            < min(
                close - timedelta(minutes=60),
                now.replace(hour=9, minute=15, second=0, microsecond=0),
            )
        ):
            return self.launch("exploration:" + day, "exploration", {"observation_ids": ids}, day)
        return False

    def launch_candidate(self, now, close):
        if not current_execution_verified(self.store.get("readiness", {})) or not self.store.get(
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

    def run(self, *, ownership=None):
        from .ownership import runtime_ownership

        try:
            with runtime_ownership(self.config.state_dir, ownership):
                try:
                    self._run_owned()
                finally:
                    # Do not release execution ownership while a research/publisher
                    # worker can still write state. Systemd retains its stop timeout.
                    try:
                        self.pool.shutdown(wait=True, cancel_futures=True)
                        try:
                            self.finish_shutdown_task()
                        finally:
                            self.publisher_pool.shutdown(wait=True, cancel_futures=True)
                        self.store.set("status", "Local supervisor stopped; independent watchdog owns recovery.")
                        self.store.event("supervisor_stopped", {"pid": os.getpid()})
                    finally:
                        self.close()
        except BaseException:
            # A rejected lease never enters the owned loop, but this instance
            # still owns the resources acquired by its constructor.
            self.close()
            raise


    def finish_shutdown_task(self):
        """Keep completed evidence without applying execution decisions on stop."""
        if not self.future or not self.future.done():
            return
        key, role, context, day = self.task
        safe_roles = {
            "deep_research", "deep_research_review", "weekly", "monthly",
            "quota_refresh", "accounting_refresh", "options_coverage",
        }
        if not self.future.cancelled() and role in safe_roles:
            self.finish_task()
            return
        try:
            result = self.future.result()
        except Exception as exc:
            # A canceled/failed worker has no completed result to preserve.
            completed = self.store.job_end(key, False, {
                "role": role, "outcome": "shutdown_worker_incomplete",
                "error_type": type(exc).__name__,
            })
            if not completed:
                raise RuntimeError("Shutdown task ownership changed") from exc
        else:
            import hashlib

            captured = utc_now()
            identity = hashlib.sha256((key + ":" + captured).encode()).hexdigest()[:24]
            with self.store.transaction():
                self.store.memory_put("shutdown-result:" + identity, "deferred_agent_result", {
                    "task_key": key, "role": role, "day": day, "captured_at": captured,
                    "outcome": "deferred_shutdown", "result": result, "context": context,
                    "authority": "Private retained reply only; not an approval or applied result.",
                })
                record_application_outcome(self.store, key, "deferred")
                completed = self.store.job_end(key, False, {
                    "role": role, "outcome": "deferred_shutdown",
                    "reason": "Completed reply retained; application requires a fresh scheduled task.",
                })
                if not completed:
                    raise RuntimeError("Shutdown task ownership changed")
                self.store.event("agent_task_deferred", {
                    "role": role, "reason": "Supervisor shutdown; completed reply retained privately.",
                })
        self.future = None
        self.task = None
        self.store.set("active_task", None)

    def _run_owned(self):
        from .store import process_owner

        self.store.job_owner = process_owner("supervisor")
        self.store.recover_jobs(owner_kind="supervisor")
        self.store.set("preflight_day", None)
        self.store.event(
            "startup", {"summary": "Local supervisor started; recovering durable state."}
        )

        def stop(signum, *_):
            LOG.info("Supervisor received signal %s; stopping", signum)
            self.store.event("supervisor_stopping", {"signal": signum, "pid": os.getpid()})
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
                    getattr(exc, "operation_details", None),
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
    def launch_position_review(self, now):
        holdings = [
            h
            for h in self.store.rows("SELECT * FROM holdings")
            if not (h["plan_id"] or "").startswith("operational-smoke")
        ]
        if not holdings:
            return False
        update = (self.store.get("material_change") or {}).get("at", "")
        key = f"position:{now.date().isoformat()}:{now.hour}:{update}"
        quotes = self.broker.quotes([h["symbol"] for h in holdings])
        positions = []
        for holding in holdings:
            rows = self.store.rows("SELECT payload FROM plans WHERE id=?", (holding["plan_id"],))
            positions.append(
                {
                    "holding": holding,
                    "plan": json.loads(rows[0]["payload"]) if rows else None,
                    "quote": quotes.get(holding["symbol"]),
                }
            )
        context = {
            "positions": positions,
            "brief": self.store.get("brief", {}),
            "latest_events": self.store.get("pulses", [])[:2],
            "now": now.isoformat(),
        }
        return self.launch(key, "position_review", context, now.date().isoformat())


def publish_worker(config):
    store = Store(config.state_dir / "trader.sqlite3")
    try:
        return publish(config, store)
    finally:
        store.close()
