from __future__ import annotations

import hashlib
import json
from datetime import datetime, time, timedelta

from .config import ET
from .engine import quote_values, timestamp
from .store import dumps, utc_now


class Experiments:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def eligibility_reason(plan, quote, now):
        """Explain the existing observation gates without granting order approval."""
        try:
            if plan["branch"] == "options":
                return "options_research_only"
            expiry = timestamp(plan["expires_at"])
            if expiry.tzinfo is None:
                return "invalid_plan"
            if now >= expiry:
                return "expired_plan"
            if not plan.get("event_risk_known"):
                return "event_risk_unknown"
            evidence = plan.get("evidence", [])
            if not evidence or any(
                timestamp(item["observed_at"]).tzinfo is None
                or not now - timedelta(hours=24)
                <= timestamp(item["observed_at"])
                <= now + timedelta(minutes=5)
                for item in evidence
            ):
                return "evidence_not_fresh"
            if not quote:
                return "missing_quote"
            try:
                _, ask = quote_values(quote, now)
            except (ValueError, KeyError, TypeError):
                return "invalid_or_stale_quote"
            if not plan["entry_low"] <= ask <= plan["entry_high"]:
                return "outside_entry_interval"
            return "eligible_for_observation"
        except (ValueError, KeyError, TypeError):
            return "invalid_plan"

    def record_funnel(self, plans, exploration_plans, quotes, now):
        """Retain one eligibility snapshot per five-minute slot, never synthetic samples.

        Counts describe supplied plans at a tick. They are neither independent
        opportunities nor evidence that research ought to have produced a trade.
        """
        now = now.astimezone(ET)
        day = now.date().isoformat()
        slot = now.hour * 12 + now.minute // 5
        key = "experiment-funnel:" + day
        history = self.store.get(key, {"day": day, "slots": {}})
        slot_key = str(slot)
        if slot_key in history["slots"]:
            return history["slots"][slot_key]
        branches = {}
        for branch in ("intraday", "swing"):
            rows = [(p, False) for p in plans if p.get("branch") == branch]
            rows += [(p, True) for p in exploration_plans if p.get("branch") == branch]
            reasons = {}
            for plan, _ in rows:
                reason = self.eligibility_reason(
                    plan, quotes.get(plan.get("symbol")), now
                )
                reasons[reason] = reasons.get(reason, 0) + 1
            branches[branch] = {
                "executable_plans": sum(not research for _, research in rows),
                "research_plans": sum(research for _, research in rows),
                "reasons": reasons,
                "state": "no_valid_plan_stream" if not rows else "plan_stream_present",
            }
        snapshot = {"as_of": now.isoformat(), "branches": branches}
        history["slots"][slot_key] = snapshot
        self.store.set(key, history)
        self.store.set("experiment_funnel_latest", snapshot)
        return snapshot

    def funnel(self):
        """Compact, read-only diagnosis; missing historical instrumentation stays unknown."""
        latest = self.store.get("experiment_funnel_latest")
        branches = {}
        plans = self.store.rows(
            "SELECT branch,count(*) n FROM plans WHERE state IN ('planned','approved') GROUP BY branch"
        )
        research = self.store.get("exploration_shadow_plans", [])
        for branch in ("intraday", "swing"):
            active = self.store.rows(
                "SELECT count(*) n FROM experiments WHERE branch=? AND state='shadow'", (branch,)
            )[0]["n"]
            samples = {
                r["state"]: r["n"]
                for r in self.store.rows(
                    "SELECT s.state,count(*) n FROM shadow s JOIN experiments e "
                    "ON e.id=s.experiment WHERE e.branch=? AND e.state='shadow' GROUP BY s.state",
                    (branch,),
                )
            }
            queued = next((r["n"] for r in plans if r["branch"] == branch), 0)
            research_count = sum(p.get("branch") == branch for p in research)
            if not active:
                blocker = "no_active_challengers"
            elif not queued and not research_count:
                blocker = "no_plan_inputs"
            elif samples.get("open"):
                blocker = "awaiting_observed_exits"
            else:
                blocker = "inspect_recorded_eligibility"
            branches[branch] = {
                "active_challengers": active,
                "queued_plans": queued,
                "research_plans": research_count,
                "closed_samples": samples.get("closed", 0),
                "open_samples": samples.get("open", 0),
                "not_evaluable": samples.get("not_evaluable", 0),
                "current_bottleneck": blocker,
            }
        return {
            "branches": branches,
            "latest_eligibility": latest,
            "tracking": "prospective_five_minute_snapshots" if latest else "not_yet_observed",
            "interpretation": (
                "Filters compare valid plan inputs; no plan means no filter sample. "
                "Resolve documented data/event gaps or accept justified abstention. "
                "Do not force plans, weaken gates, or substitute fixed/adaptive-study samples. "
                "Eligibility counts are repeated plan snapshots, not independent trials."
            ),
        }

    def register(self, proposal):
        required = {
            "id",
            "branch",
            "hypothesis",
            "exact_change",
            "parent_version",
            "minimum_sessions",
            "minimum_samples",
            "cost_model",
            "metrics",
        }
        if not required <= proposal.keys() or proposal["branch"] not in (
            "intraday",
            "swing",
            "options",
        ):
            raise ValueError("Incomplete experiment specification")
        if int(proposal["minimum_sessions"]) < 20 or int(proposal["minimum_samples"]) < 30:
            raise ValueError("Insufficient forward evidence requirements")
        if self.store.rows("SELECT id FROM experiments WHERE id=?", (proposal["id"],)):
            return False
        if (
            len(
                self.store.rows(
                    "SELECT id FROM experiments WHERE branch=? AND state='shadow'",
                    (proposal["branch"],),
                )
            )
            >= 6
        ):
            return False
        for existing in self.store.rows(
            "SELECT payload FROM experiments WHERE branch=? AND state='shadow'",
            (proposal["branch"],),
        ):
            old = json.loads(existing["payload"])
            if (
                old["exact_change"] == proposal["exact_change"]
                and old["parent_version"] == proposal["parent_version"]
            ):
                return False
        # Only preimplemented filters or isolated validated code are executable.
        # narrative proposals must go through a tested code release first.
        incumbent = self.store.get("incumbent_filter:" + proposal["branch"])
        expected_parent = incumbent["id"] if incumbent else "pilot-v1"
        if proposal["parent_version"] != expected_parent:
            raise ValueError("Experiment must name the current incumbent version")
        supported = proposal["exact_change"] in (
            "require_risk_on",
            "avoid_risk_off",
            "higher_confidence_075",
            "higher_confidence_085",
            "reward_risk_2",
        ) or (proposal["exact_change"].startswith("code:") and bool(proposal.get("source")))
        state = "shadow" if supported and proposal["branch"] != "options" else "proposed"
        self.store.db.execute(
            "INSERT INTO experiments VALUES(?,?,?,?,?)",
            (proposal["id"], proposal["branch"], state, dumps(proposal), utc_now()),
        )
        self.store.event(
            "experiment_registered",
            {"id": proposal["id"], "state": state, "hypothesis": proposal["hypothesis"]},
            proposal["branch"],
        )
        return True

    def consider(self, plan, quote, regime, now):
        if self.eligibility_reason(plan, quote, now) != "eligible_for_observation":
            return
        for experiment in self.store.rows(
            "SELECT * FROM experiments WHERE branch=? AND state='shadow'", (plan["branch"],)
        ):
            self._consider_one(experiment, plan, quote, regime, now)

    def _consider_one(self, experiment, plan, quote, regime, now):
        _, ask = quote_values(quote, now)
        spec = json.loads(experiment["payload"])
        active = self.store.get("incumbent_filter:" + plan["branch"])
        if spec["parent_version"] != (active["id"] if active else "pilot-v1"):
            # A daily evaluator may not have marked the old experiment stale yet.
            # Never pair a new incumbent with an old parent's contract.
            return
        passes = self.filter_passes(spec, plan, regime)
        sid = hashlib.sha256((experiment["id"] + plan["id"]).encode()).hexdigest()[:24]
        local_now = now.astimezone(ET)
        day = local_now.date().isoformat()
        calendar = self.store.get("calendar:" + day, [])
        observation_end = None
        if plan["branch"] == "swing":
            exit_deadline = (now + timedelta(days=14)).isoformat()
        elif calendar:
            closed = datetime.fromisoformat(day + "T" + calendar[0]["close"]).replace(tzinfo=ET)
            exit_deadline = (closed - timedelta(minutes=12)).isoformat()
            observation_end = closed.isoformat()
        else:
            exit_deadline = plan["expires_at"]
            observation_end = datetime.combine(
                local_now.date() + timedelta(days=1), time.min, tzinfo=ET
            ).isoformat()
        payload = {
            "day": day,
            "eligibility_version": "plan-evidence-v2",
            "eligibility_scope": (
                "Fresh priced plan with verified event risk and fresh cited evidence. "
                "Both executable and research-only plan inputs use these gates; "
                "this is not broker approval, sizing or a fill."
            ),
            "entry": ask,
            "entered_at": now.isoformat(),
            "stop": plan["stop"],
            "target": plan["target"],
            "expires_at": exit_deadline,
            "entry_deadline": plan["expires_at"],
            "observation_end": observation_end,
            "branch": plan["branch"],
            "plan_id": plan["id"],
            "challenger_trades": passes,
            "incumbent_trades": self.permits(plan, regime),
            "incumbent_return": None,
            "challenger_return": None,
            "assumptions": "Forward quote observation only; $1 unit exposure; round-trip 20bp plus observed spread. No fill guarantee.",
        }
        self.store.db.execute(
            "INSERT OR IGNORE INTO shadow VALUES(?,?,?,?,?,?)",
            (sid, experiment["id"], plan["symbol"], plan["branch"], "open", dumps(payload)),
        )

    def mark(self, quotes, now, closing=False):
        for row in self.store.rows("SELECT * FROM shadow WHERE state='open'"):
            p = json.loads(row["payload"])
            if row["branch"] == "intraday":
                # Missing the closing observation never becomes a next-session
                # price. Older rows lack a stored calendar close: the entry-day
                # boundary is the minimum defensible expiry for those records.
                end = p.get("observation_end")
                missed = now >= timestamp(end) if end else (
                    now.astimezone(ET).date().isoformat() > p["day"]
                )
                if missed:
                    p.update(
                        {
                            "not_evaluable_reason": "missing_valid_intraday_exit",
                            "marked_at": now.isoformat(),
                        }
                    )
                    self.store.db.execute(
                        "UPDATE shadow SET state='not_evaluable',payload=? WHERE id=?",
                        (dumps(p), row["id"]),
                    )
                    continue
            q = quotes.get(row["symbol"])
            if not q:
                continue
            try:
                bid, ask = quote_values(q, now)
            except (ValueError, KeyError, TypeError):
                continue
            exit_due = (
                bid <= p["stop"]
                or bid >= p["target"]
                or now >= timestamp(p["expires_at"])
                or (closing and row["branch"] == "intraday")
            )
            if not exit_due:
                continue
            # First observed exit price, never a fictional fill at the stop/target.
            ret = bid / p["entry"] - 1 - 0.002 - (ask - bid) / p["entry"]
            p.update(
                {
                    "exit": bid,
                    "exit_at": now.isoformat(),
                    "incumbent_return": ret if p.get("incumbent_trades", True) else 0.0,
                    "challenger_return": ret if p["challenger_trades"] else 0.0,
                }
            )
            self.store.db.execute(
                "UPDATE shadow SET state='closed',payload=? WHERE id=?", (dumps(p), row["id"])
            )

    def evaluate(self):
        for branch in ("intraday", "swing", "options"):
            active = self.store.get("incumbent_filter:" + branch)
            if not active:
                continue
            latest = self.store.rows(
                "SELECT value FROM equity WHERE branch=? ORDER BY id DESC LIMIT 1", (branch,)
            )
            value = latest[0]["value"] if latest else 10000
            if value <= active.get("equity_at_promotion", 10000) * 0.98:
                self.store.set("incumbent_filter:" + branch, active.get("previous_incumbent"))
                self.store.db.execute(
                    "UPDATE experiments SET state='rolled_back' WHERE id=?", (active["id"],)
                )
                self.store.event(
                    "strategy_rolled_back",
                    {
                        "id": active["id"],
                        "reason": "Fixed rollback threshold: 2% equity loss since promotion",
                    },
                    branch,
                )
        promoted = []
        for e in self.store.rows("SELECT * FROM experiments WHERE state='shadow'"):
            spec = json.loads(e["payload"])
            rows = self.store.rows(
                "SELECT payload FROM shadow WHERE experiment=? AND state='closed'", (e["id"],)
            )
            samples = [json.loads(r["payload"]) for r in rows]
            sessions = len({x["day"] for x in samples})
            eligibility_versions = {
                x.get("eligibility_version", "legacy_unversioned") for x in samples
            }
            if len(eligibility_versions) > 1:
                key = "experiment-mixed-eligibility:" + e["id"]
                if not self.store.get(key):
                    self.store.event(
                        "experiment_review",
                        {
                            "id": e["id"],
                            "promoted": False,
                            "reason": "Mixed observation eligibility versions require a new prospective contract",
                            "eligibility_versions": sorted(eligibility_versions),
                        },
                        e["branch"],
                    )
                    self.store.set(key, True)
                continue
            incumbent = self.store.get("incumbent_filter:" + e["branch"])
            current_parent = incumbent["id"] if incumbent else "pilot-v1"
            if spec["parent_version"] != current_parent:
                self.store.db.execute(
                    "UPDATE experiments SET state='stale_parent' WHERE id=?", (e["id"],)
                )
                continue
            if sessions < spec["minimum_sessions"] or len(samples) < spec["minimum_samples"]:
                continue
            # Only predeclared doubling-session review looks; don't repeatedly
            # test significance every day after reaching minimum evidence.
            look = 0
            while spec["minimum_sessions"] * 2 ** (look + 1) <= sessions:
                look += 1
            look_key = "experiment-look:" + e["id"]
            if self.store.get(look_key, -1) >= look:
                continue
            self.store.set(look_key, look)
            # Daily paired differences avoid treating correlated same-day trades as
            # independent. Conservative sign consistency + lower-bound requirement.
            import numpy as np

            daily = {}
            for x in samples:
                daily.setdefault(x["day"], []).append(
                    x["challenger_return"] - x["incumbent_return"]
                )
            deltas = np.array([sum(v) / len(v) for v in daily.values()])
            family_trials = self.store.rows(
                "SELECT count(*) AS n FROM experiments WHERE branch=?", (e["branch"],)
            )[0]["n"]
            # Conservative fixed-trial + repeated-look penalty; not a guarantee
            # of statistical validity for dependent/nonstationary market data.
            import math

            critical = max(
                3.0, math.sqrt(2 * math.log(2 * max(1, family_trials) * (look + 1) ** 2 / 0.05))
            )
            lower = float(deltas.mean() - critical * deltas.std(ddof=1) / np.sqrt(len(deltas)))
            net = sum(x["challenger_return"] for x in samples) / len(samples)
            if lower <= 0 or (deltas > 0).mean() < 0.6 or net <= 0:
                self.store.event(
                    "experiment_review",
                    {
                        "id": e["id"],
                        "sessions": sessions,
                        "samples": len(samples),
                        "lower_bound": lower,
                        "promoted": False,
                        "review_look": look,
                        "family_trials": family_trials,
                        "critical_multiplier": critical,
                        "absolute_mean_net": net,
                    },
                    e["branch"],
                )
                continue
            # Promotion is filter activation within fixed policy; arbitrary code
            # changes cannot pass through this path.
            self.store.db.execute("UPDATE experiments SET state='promoted' WHERE id=?", (e["id"],))
            self.store.set(
                "incumbent_filter:" + e["branch"],
                {
                    "id": e["id"],
                    "filter": spec["exact_change"],
                    "source": spec.get("source"),
                    "stage": "25% pilot risk",
                    "promoted_at": utc_now(),
                    "previous_incumbent": self.store.get("incumbent_filter:" + e["branch"]),
                    "equity_at_promotion": next(
                        iter(
                            self.store.rows(
                                "SELECT value FROM equity WHERE branch=? ORDER BY id DESC LIMIT 1",
                                (e["branch"],),
                            )
                        ),
                        {"value": 10000},
                    )["value"],
                },
            )
            self.store.event(
                "strategy_promoted",
                {
                    "id": e["id"],
                    "sessions": sessions,
                    "samples": len(samples),
                    "lower_bound": lower,
                    "review_look": look,
                    "family_trials": family_trials,
                    "critical_multiplier": critical,
                    "absolute_mean_net": net,
                },
                e["branch"],
            )
            candidate = self.store.get("maintenance_candidate")
            if candidate and e["id"] == "code-" + candidate["id"]:
                self.store.set(
                    "maintenance_candidate",
                    {**candidate, "state": "active_reduced_risk", "activated_at": utc_now()},
                )
            promoted.append(e["id"])
        return promoted

    def permits(self, plan, regime):
        active = self.store.get("incumbent_filter:" + plan["branch"])
        if not active:
            return True
        return self.filter_passes(
            {"exact_change": active["filter"], "source": active.get("source")}, plan, regime
        )

    @staticmethod
    def filter_passes(spec, plan, regime):
        if spec["exact_change"].startswith("code:"):
            from .maintenance import evaluate_filter

            return evaluate_filter(spec["source"], plan, {"regime": regime})
        if spec["exact_change"] == "require_risk_on":
            return regime == "risk_on"
        if spec["exact_change"] == "avoid_risk_off":
            return regime in ("risk_on", "mixed")
        if spec["exact_change"] == "reward_risk_2":
            return (plan["target"] - plan["entry_high"]) / (plan["entry_high"] - plan["stop"]) >= 2
        if spec["exact_change"] == "higher_confidence_085":
            return plan["confidence"] >= 0.85
        if spec["exact_change"] == "higher_confidence_075":
            return plan["confidence"] >= 0.75
        raise ValueError("Unsupported experiment filter")

    def progress(self):
        summaries = {}
        funnel = self.funnel()["branches"]
        for e in self.store.rows("SELECT id,branch FROM experiments"):
            closed = [
                json.loads(r["payload"])
                for r in self.store.rows(
                    "SELECT payload FROM shadow WHERE experiment=? AND state='closed'", (e["id"],)
                )
            ]
            days = {x["day"] for x in closed}
            summaries[e["id"]] = {
                "samples": len(closed),
                "sessions": len(days),
                "eligibility_versions": sorted(
                    {x.get("eligibility_version", "legacy_unversioned") for x in closed}
                ),
                "open_observations": self.store.rows(
                    "SELECT count(*) AS n FROM shadow WHERE experiment=? AND state='open'",
                    (e["id"],),
                )[0]["n"],
                "not_evaluable_observations": self.store.rows(
                    "SELECT count(*) AS n FROM shadow WHERE experiment=? AND state='not_evaluable'",
                    (e["id"],),
                )[0]["n"],
                "current_bottleneck": funnel.get(e["branch"], {}).get(
                    "current_bottleneck", "options_research_only"
                ),
                "mean_paired_net": sum(
                    x["challenger_return"] - x["incumbent_return"] for x in closed
                )
                / len(closed)
                if closed
                else None,
                "status": "preliminary_forward_observations" if closed else "awaiting_observations",
                "warning": "Early evidence; correlated trades are not independent and no promotion is implied.",
            }
        return summaries
