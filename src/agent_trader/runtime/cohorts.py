"""Preregistered forward quote cohorts, separate from execution and promotion."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta

from .config import ET
from .engine import quote_values, timestamp
from .exploration import RULES, clean_bars, rule_signal
from .store import dumps

VERSION = "fixed-signal-v1"
PROTOCOL = {
    "version": VERSION,
    "signals": "Prior completed Alpaca IEX daily bars only; provider daily closes are not guaranteed consolidated closing-auction prices. Six fixed rules. Raw reversal is not a classified non-fundamental liquidity shock.",
    "entry": "First observed valid ask from actual market open +5 through +30 minutes, never a reconstructed fill.",
    "exit": "First valid bid from actual close -12 minutes through the close on holding session 1 or 5; missing exits are not evaluable.",
    "quote_validation": "Bid/ask finite, positive, ordered; bid >= $5; quote age between -5 and 90 seconds; spread / midpoint <=0.5% and spread / ask <=0.5%.",
    "cost_formula": "gross=exit_bid/entry_ask-1; net=gross-0.002-(entry_ask-entry_bid)/entry_ask-(exit_ask-exit_bid)/exit_ask; stress=net-0.003. Ask/bid already includes spread; the extra spread terms are conservative additional assumed penalties, not measured fees.",
    "reporting_window": "Twenty broker-calendar entry sessions fixed before the first observation, followed by four possible swing maturation sessions. No optional extension to obtain a winner; descriptive results only.",
    "denominator": "Preregister every eligible rule/symbol/horizon opportunity. Missing prior-session data and non-overlap exclusions are reported separately. Missing entry or exit quotes are not evaluable, never zeros or fills. Net means condition on evaluable observations; show their count against all preregistered opportunities.",
    "unit": "Holding-horizon returns per unit opportunity, cash=0 for observed signal abstentions; average within entry date then across entry dates. Symbols and variants are correlated; entry dates are not proven independent observations.",
    "comparison": "Historical bar-open/close screens differ from this forward quote protocol. They are hypothesis-generation evidence only.",
    "authority": "No broker orders, allocated capital, automatic promotion, causal controls, annualized return or profitability claim.",
}


def register_study(store, sessions, now):
    old = store.get("cohort_study")
    if old:
        protocol_hash = hashlib.sha256(dumps(PROTOCOL).encode()).hexdigest()
        if old.get("protocol_sha256") != protocol_hash:
            first = next(s for s in sessions if s["date"] == old["entry_dates"][0])
            before_open = now < datetime.fromisoformat(first["date"] + "T" + first["open"]).replace(
                tzinfo=ET
            )
            if not before_open or store.rows("SELECT count(*) n FROM cohort_observations")[0]["n"]:
                raise ValueError("A started cohort protocol cannot be silently amended")
            store.set("cohort-study-protocol:" + old["protocol_sha256"], old)
            old = {
                **old,
                "protocol": PROTOCOL,
                "protocol_sha256": protocol_hash,
                "amended_at": now.isoformat(),
            }
            store.set("cohort_study", old)
            store.event(
                "cohort_registered",
                {
                    "summary": "Pre-observation source qualification clarified; original protocol hash archived, no outcomes observed.",
                    "protocol_sha256": protocol_hash,
                },
            )
        return old
    future = [
        s
        for s in sorted(sessions, key=lambda s: s["date"])
        if datetime.fromisoformat(s["date"] + "T" + s["open"]).replace(tzinfo=ET) > now
    ]
    if len(future) < 24:
        return None
    study = {
        "id": VERSION + ":" + future[0]["date"],
        "registered_at": now.isoformat(),
        "entry_dates": [s["date"] for s in future[:20]],
        "report_after": datetime.fromisoformat(future[23]["date"] + "T" + future[23]["close"])
        .replace(tzinfo=ET)
        .isoformat(),
        "protocol": PROTOCOL,
        "protocol_sha256": hashlib.sha256(dumps(PROTOCOL).encode()).hexdigest(),
    }
    store.set("cohort_study", study)
    return study


def normalized_screen(screen):
    """A derived view only. Frozen raw observations/hash/split remain untouched."""
    result = {k: v for k, v in screen.items() if k != "trials"}
    result["metric_contract"] = {
        "unit": "net holding-horizon return per equal-weight unit opportunity, including cash abstentions",
        "aggregation": "Mean across symbol opportunities within an entry session, then mean across entry sessions",
        "not": "Not a portfolio daily return, executed-trade return, independent sample count, Sharpe ratio or annualized return",
        "costs": "20bp base / 50bp stressed assumed round trip",
    }
    result["trials"] = []
    for trial in screen.get("trials", []):
        t = {k: v for k, v in trial.items() if k not in ("development", "holdout")}
        for partition in ("development", "holdout"):
            old = trial.get(partition, {})
            t[partition] = {
                "entry_sessions": old.get("sessions"),
                "unit_opportunities": old.get("opportunities"),
                "signals": old.get("signals"),
                "mean_horizon_net_return": old.get("mean_daily_net"),
                "mean_horizon_stressed_return": old.get("mean_daily_stress"),
                "mean_horizon_baseline_return": old.get("mean_daily_baseline"),
            }
        result["trials"].append(t)
    return result


def freeze_signals(store, bars, sessions, now=None, for_day=None):
    now = (now or datetime.now(ET)).astimezone(ET)
    day = for_day or now.date().isoformat()
    if for_day:
        next_session = next(
            (
                s
                for s in sorted(sessions, key=lambda s: s["date"])
                if datetime.fromisoformat(s["date"] + "T" + s["open"]).replace(tzinfo=ET) > now
            ),
            None,
        )
        if not next_session or next_session["date"] != for_day:
            return None
        previous_sessions = [s for s in sessions if s["date"] < for_day]
        if not previous_sessions or now < datetime.fromisoformat(
            previous_sessions[-1]["date"] + "T20:20:00"
        ).replace(tzinfo=ET):
            return None  # do not freeze a still-forming prior-session daily bar
    study = register_study(store, sessions, now)
    key = "cohort-signals:" + day
    if store.get(key):
        return store.get(key)
    today = next((x for x in sessions if x["date"] == day), None)
    if (
        not study
        or day not in study["entry_dates"]
        or not today
        or now >= datetime.fromisoformat(day + "T" + today["open"]).replace(tzinfo=ET)
    ):
        return None  # no same-session reconstruction or post-open universe selection
    data = clean_bars(bars, day)
    market = data.get("SPY", [])
    risk_on = bool(len(market) >= 21 and market[-1]["c"] > sum(x["c"] for x in market[-20:]) / 20)
    flags = {}
    previous = max((x["day"] for rows in data.values() for x in rows), default=None)
    for symbol, history in data.items():
        if len(history) < 21 or history[-1]["day"] != previous:
            continue
        flags[symbol] = {rule: rule_signal(rule, history[-21:], risk_on) for rule in RULES}
    if not flags:
        return None
    payload = {
        "day": day,
        "version": VERSION,
        "frozen_at": now.isoformat(),
        "last_completed_session": previous,
        "flags": flags,
        "sessions": sessions,
        "data_sha256": hashlib.sha256(
            json.dumps(data, sort_keys=True, allow_nan=False).encode()
        ).hexdigest(),
    }
    entry_deadline = datetime.fromisoformat(day + "T" + today["open"]).replace(
        tzinfo=ET
    ) + timedelta(minutes=30)
    overlap_excluded = 0
    with store.transaction():
        store.set(key, payload)
        # Keep the exact normalized inputs privately; a hash alone cannot replay
        # a decision after the data provider revises a historical bar.
        store.set("cohort-inputs:" + day, data)
        for symbol, rules in flags.items():
            for branch in ("intraday", "swing"):
                for rule, signal in rules.items():
                    if store.rows(
                        "SELECT id FROM cohort_observations WHERE branch=? AND rule=? AND symbol=? AND state='open'",
                        (branch, rule, symbol),
                    ):
                        overlap_excluded += 1
                        continue
                    identity = ":".join((VERSION, day, branch, rule, symbol))
                    rid = hashlib.sha256(identity.encode()).hexdigest()[:28]
                    store.db.execute(
                        "INSERT OR IGNORE INTO cohort_expected VALUES(?,?,?,?,?,?)",
                        (
                            rid,
                            day,
                            branch,
                            rule,
                            symbol,
                            dumps(
                                {
                                    "signal": bool(signal),
                                    "entry_deadline": entry_deadline.isoformat(),
                                    "study_id": study["id"],
                                }
                            ),
                        ),
                    )
    from .research import UNIVERSE

    store.set(
        "cohort-exclusions:" + day,
        {
            "missing_history": sorted(set(UNIVERSE) - set(flags)),
            "overlap_opportunities": overlap_excluded,
        },
    )
    store.event(
        "cohort_registered",
        {
            "summary": "Fixed forward signal cohort frozen before the open; no orders or paper capital.",
            "day": day,
            "symbols": len(flags),
            "protocols": 12,
            "data_sha256": payload["data_sha256"],
        },
    )
    return payload


class ForwardLab:
    def __init__(self, store):
        self.store = store

    def symbols(self, day):
        prepared = self.store.get("cohort-signals:" + day, {})
        return set(prepared.get("flags", {})) | {
            r["symbol"]
            for r in self.store.rows("SELECT symbol FROM cohort_observations WHERE state='open'")
        }

    def observe(self, quotes, now, opened, closed):
        self.expire(now)
        day = now.astimezone(ET).date().isoformat()
        prepared = self.store.get("cohort-signals:" + day, {})
        if (
            not prepared
            or now < opened + timedelta(minutes=5)
            or now >= opened + timedelta(minutes=30)
        ):
            return
        sessions = sorted(
            (s for s in prepared.get("sessions", []) if s["date"] >= day), key=lambda x: x["date"]
        )
        with self.store.transaction():
            for symbol, flags in prepared["flags"].items():
                try:
                    bid, ask = quote_values(quotes.get(symbol, {}), now)
                    if bid < 5 or (ask - bid) / ask > 0.005:
                        continue
                except (ValueError, KeyError, TypeError):
                    continue
                for branch, holding in (("intraday", 1), ("swing", 5)):
                    if len(sessions) < holding or sessions[0]["date"] != day:
                        continue
                    exit_session = sessions[holding - 1]
                    deadline = datetime.fromisoformat(
                        exit_session["date"] + "T" + exit_session["close"]
                    ).replace(tzinfo=ET)
                    for rule, eligible in flags.items():
                        if self.store.rows(
                            "SELECT id FROM cohort_observations WHERE branch=? AND rule=? AND symbol=? AND state='open'",
                            (branch, rule, symbol),
                        ):
                            continue
                        identity = ":".join((VERSION, day, branch, rule, symbol))
                        row_id = hashlib.sha256(identity.encode()).hexdigest()[:28]
                        if not self.store.rows(
                            "SELECT id FROM cohort_expected WHERE id=?", (row_id,)
                        ):
                            continue
                        payload = {
                            "version": VERSION,
                            "signal_day": day,
                            "entered_at": now.isoformat(),
                            "entry_ask": ask,
                            "signal": bool(eligible),
                            "holding_sessions": holding,
                            "exit_at": (deadline - timedelta(minutes=12)).isoformat(),
                            "session_close": deadline.isoformat(),
                            "data_sha256": prepared["data_sha256"],
                            "entry_spread_fraction": (ask - bid) / ask,
                            "assumed_cost_fraction": 0.002,
                            "unit": "holding-horizon unit-opportunity return, not portfolio P&L",
                            "promotion_eligible": False,
                        }
                        self.store.db.execute(
                            "INSERT OR IGNORE INTO cohort_observations VALUES(?,?,?,?,?,?,?)",
                            (row_id, day, branch, rule, symbol, "open", dumps(payload)),
                        )

    def expire(self, now):
        with self.store.transaction():
            for row in self.store.rows(
                "SELECT e.* FROM cohort_expected e LEFT JOIN cohort_observations o ON o.id=e.id WHERE o.id IS NULL"
            ):
                p = json.loads(row["payload"])
                if now >= timestamp(p["entry_deadline"]):
                    p.update(
                        {
                            "reason": "No valid entry quote observed before the preregistered cutoff",
                            "closed_at": now.isoformat(),
                        }
                    )
                    self.store.db.execute(
                        "INSERT OR IGNORE INTO cohort_observations VALUES(?,?,?,?,?,?,?)",
                        (
                            row["id"],
                            row["day"],
                            row["branch"],
                            row["rule"],
                            row["symbol"],
                            "not_evaluable",
                            dumps(p),
                        ),
                    )
            for row in self.store.rows(
                "SELECT id,payload FROM cohort_observations WHERE state='open'"
            ):
                p = json.loads(row["payload"])
                if now >= timestamp(p["session_close"]):
                    p.update(
                        {
                            "reason": "No verified quote exit observed before the recorded session close",
                            "closed_at": now.isoformat(),
                        }
                    )
                    self.store.db.execute(
                        "UPDATE cohort_observations SET state='not_evaluable',payload=? WHERE id=?",
                        (dumps(p), row["id"]),
                    )

    def mark(self, quotes, now):
        self.expire(now)
        with self.store.transaction():
            for row in self.store.rows("SELECT * FROM cohort_observations WHERE state='open'"):
                p = json.loads(row["payload"])
                if now < timestamp(p["exit_at"]):
                    continue
                try:
                    bid, ask = quote_values(quotes.get(row["symbol"], {}), now)
                    if bid < 5 or (ask - bid) / ask > 0.005:
                        continue
                except (ValueError, KeyError, TypeError):
                    continue
                gross = bid / p["entry_ask"] - 1
                if abs(gross) > 0.30:
                    p.update(
                        {
                            "reason": "Large price discontinuity; corporate-action/market-move attribution is unverified",
                            "closed_at": now.isoformat(),
                        }
                    )
                    state = "not_evaluable"
                else:
                    cost = 0.002 + p["entry_spread_fraction"] + (ask - bid) / ask
                    p.update(
                        {
                            "exit_bid": bid,
                            "closed_at": now.isoformat(),
                            "observed_baseline_horizon_return": gross - cost,
                            "observed_signal_horizon_return": gross - cost if p["signal"] else 0.0,
                            "stressed_signal_horizon_return": gross - cost - 0.003
                            if p["signal"]
                            else 0.0,
                        }
                    )
                    state = "closed"
                self.store.db.execute(
                    "UPDATE cohort_observations SET state=?,payload=? WHERE id=?",
                    (state, dumps(p), row["id"]),
                )

    def summary(self):
        trials = []
        for branch in ("intraday", "swing"):
            for rule, description in RULES.items():
                rows = self.store.rows(
                    "SELECT day,state,payload FROM cohort_observations WHERE branch=? AND rule=?",
                    (branch, rule),
                )
                closed = [
                    (r["day"], json.loads(r["payload"])) for r in rows if r["state"] == "closed"
                ]
                groups = {}
                baselines, stressed = {}, {}
                for day, p in closed:
                    groups.setdefault(day, []).append(p["observed_signal_horizon_return"])
                    baselines.setdefault(day, []).append(p["observed_baseline_horizon_return"])
                    stressed.setdefault(day, []).append(p["stressed_signal_horizon_return"])
                means = [sum(v) / len(v) for v in groups.values()]
                baseline_means = [sum(v) / len(v) for v in baselines.values()]
                stress_means = [sum(v) / len(v) for v in stressed.values()]
                trials.append(
                    {
                        "branch": branch,
                        "rule": rule,
                        "description": description,
                        "open": sum(r["state"] == "open" for r in rows),
                        "closed": len(closed),
                        "preregistered_opportunities": self.store.rows(
                            "SELECT count(*) n FROM cohort_expected WHERE branch=? AND rule=?",
                            (branch, rule),
                        )[0]["n"],
                        "entry_sessions": len(groups),
                        "not_evaluable": sum(r["state"] == "not_evaluable" for r in rows),
                        "mean_horizon_net_return": sum(means) / len(means) if means else None,
                        "mean_horizon_baseline_return": sum(baseline_means) / len(baseline_means)
                        if baseline_means
                        else None,
                        "mean_horizon_stressed_return": sum(stress_means) / len(stress_means)
                        if stress_means
                        else None,
                    }
                )
        return {
            "version": VERSION,
            "protocols": 12,
            "trials": trials,
            "broker_orders_allowed": False,
            "automatic_promotion": False,
            "study": self.store.get("cohort_study"),
            "exclusions": [
                {"day": r["key"].split(":", 1)[1], **json.loads(r["value"])}
                for r in self.store.rows(
                    "SELECT key,value FROM kv WHERE key LIKE 'cohort-exclusions:%' ORDER BY key DESC LIMIT 30"
                )
            ],
            "protocol": PROTOCOL,
            "unit": "Net holding-horizon returns per unit opportunity, averaged within entry session then across entry sessions",
            "limitations": [
                "Forward quote observations, not guaranteed fills or allocated paper P&L.",
                "All symbols/variants share market exposure; counts are not independent evidence.",
                "Ask entry / bid exit plus 20bp and spread buffers; stressed costs add 30bp.",
                "Entry window 09:35–10:00; exits twelve minutes before actual close on holding session 1 or 5.",
                "Missing exit quotes or large unverified discontinuities are not evaluable; no retrospective fills.",
                "Historical screens use bar open/close; this forward protocol uses first observed quotes after 09:35 / before close, so results are not a direct replication.",
                "Fixed present-day universe; no causal, portfolio or profitability inference from this cohort.",
            ],
        }
