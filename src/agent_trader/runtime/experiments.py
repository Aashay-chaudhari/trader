from __future__ import annotations

import hashlib
import json
from datetime import timedelta

from .engine import quote_values, timestamp
from .store import dumps, utc_now


class Experiments:
    def __init__(self, store):
        self.store = store

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
        if plan["branch"] == "options":
            return
        bid, ask = quote_values(quote, now)
        if not plan["entry_low"] <= ask <= plan["entry_high"] or now >= timestamp(
            plan["expires_at"]
        ):
            return
        for experiment in self.store.rows(
            "SELECT * FROM experiments WHERE branch=? AND state='shadow'", (plan["branch"],)
        ):
            self._consider_one(experiment, plan, quote, regime, now)

    def _consider_one(self, experiment, plan, quote, regime, now):
        _, ask = quote_values(quote, now)
        spec = json.loads(experiment["payload"])
        passes = self.filter_passes(spec, plan, regime)
        sid = hashlib.sha256((experiment["id"] + plan["id"]).encode()).hexdigest()[:24]
        calendar = self.store.get("calendar:" + now.date().isoformat(), [])
        if plan["branch"] == "swing":
            exit_deadline = (now + timedelta(days=14)).isoformat()
        elif calendar:
            from .config import ET
            from datetime import datetime

            exit_deadline = (
                datetime.fromisoformat(now.date().isoformat() + "T" + calendar[0]["close"]).replace(
                    tzinfo=ET
                )
                - timedelta(minutes=12)
            ).isoformat()
        else:
            exit_deadline = plan["expires_at"]
        payload = {
            "day": now.date().isoformat(),
            "entry": ask,
            "entered_at": now.isoformat(),
            "stop": plan["stop"],
            "target": plan["target"],
            "expires_at": exit_deadline,
            "entry_deadline": plan["expires_at"],
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
            q = quotes.get(row["symbol"])
            if not q:
                continue
            try:
                bid, ask = quote_values(q, now)
            except ValueError:
                continue
            p = json.loads(row["payload"])
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
        for e in self.store.rows("SELECT id FROM experiments"):
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
                "open_observations": self.store.rows(
                    "SELECT count(*) AS n FROM shadow WHERE experiment=? AND state='open'",
                    (e["id"],),
                )[0]["n"],
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
