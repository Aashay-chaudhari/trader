"""Prospectively registered declarative observations. Never imports a broker client.

New ideas can acquire evidence without an executable trading plan. Every version
retains its specification, denominators and provenance; no result authorizes trades.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .config import ET, RESEARCH_UNIVERSE
from .observation_audit import date_composition, record_quote
from .store import dumps


class NumericPredicate(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    field: Literal[
        "return_1d",
        "return_3d",
        "return_5d",
        "price_vs_sma20",
        "gap_from_prior_close",
        "relative_gap_spy",
    ]
    operator: Literal["gte", "lte"]
    value: float = Field(ge=-1, le=1)


ResearchSymbol = Literal[tuple(RESEARCH_UNIVERSE)]


class AdaptiveContract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{4,70}$")
    hypothesis_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{4,70}$")
    branch: Literal["intraday", "swing"]
    symbols: list[ResearchSymbol] = Field(min_length=1, max_length=6)
    predicates: list[NumericPredicate] = Field(min_length=1, max_length=3)
    hypothesis: str = Field(min_length=15, max_length=1000)
    falsification: str = Field(min_length=15, max_length=1000)
    minimum_sessions: int = Field(ge=20, le=60, default=20)
    minimum_signals: int = Field(ge=30, le=1000, default=30)

    @model_validator(mode="after")
    def supported_symbols(self):
        if len(self.symbols) != len(set(self.symbols)) or not set(self.symbols) <= set(
            RESEARCH_UNIVERSE
        ):
            raise ValueError("Use distinct symbols from the fixed liquid research universe")
        if self.minimum_signals > self.minimum_sessions * len(self.symbols):
            raise ValueError("Signal target exceeds the maximum opportunities in the fixed study")
        return self


PROTOCOL = {
    "version": "adaptive-observation-v1",
    "entry": "First valid ask from open+15m inclusive to open+30m exclusive; all predicates ANDed.",
    "features": "Returns and price_vs_sma20 use the previous actual session's completed daily close. gap_from_prior_close uses the entry-observation ask / prior close - 1; relative_gap_spy subtracts the same contemporaneous SPY ask change. These are not opening-auction gaps.",
    "inputs": "Same-ET-day private archived packet, at most two hours old, no future capture; prior daily data must match the preceding actual broker session. Unknown is not false.",
    "exit": "First valid bid in close-12m through close exclusive on actual holding session 1 or 5. Missing observations are not evaluable; no later price backfill.",
    "costs": "ask-to-bid gross minus assumed20bp base /50bp stressed round trip; spreads already reflected in ask/bid, no fill guarantee.",
    "unit": "Holding-horizon unit opportunity, cash=0 for observed false signals. Same-symbol always-long comparator, no portfolio allocation or broker P&L.",
    "authority": "Descriptive research only. No automatic promotion, orders, significance test or profitability certification.",
}


def _stamp(value):
    stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("Timestamp must include timezone")
    return stamp


def _hash(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _time(session, field):
    return datetime.fromisoformat(session["date"] + "T" + session[field]).replace(tzinfo=ET)


def _quote(quote, now):
    from .engine import quote_values

    bid, ask = quote_values(quote, now)
    if bid < 5 or (ask - bid) / ask > 0.005:
        raise ValueError("Research price/spread gate")
    return bid, ask


class AdaptiveLab:
    def __init__(self, store):
        self.store = store
        store.db.executescript("""
        CREATE TABLE IF NOT EXISTS adaptive_contracts(
          id TEXT PRIMARY KEY, branch TEXT NOT NULL, state TEXT NOT NULL,
          registered_at TEXT NOT NULL, registered_day TEXT NOT NULL,
          specification_sha256 TEXT NOT NULL, fingerprint TEXT NOT NULL UNIQUE,
          payload TEXT NOT NULL, schedule TEXT);
        CREATE TABLE IF NOT EXISTS adaptive_observations(
          id TEXT PRIMARY KEY, contract_id TEXT NOT NULL, day TEXT NOT NULL,
          symbol TEXT NOT NULL, state TEXT NOT NULL, payload TEXT NOT NULL,
          UNIQUE(contract_id,day,symbol));
        CREATE INDEX IF NOT EXISTS adaptive_open ON adaptive_observations(state,day);
        """)

    def register(self, contract, now=None):
        now = _stamp(now or datetime.now(ET)).astimezone(ET)
        c = (
            contract
            if isinstance(contract, AdaptiveContract)
            else AdaptiveContract.model_validate(contract)
        )
        spec = c.model_dump(mode="json")
        spec["symbols"] = sorted(spec["symbols"])
        spec["predicates"] = sorted(
            spec["predicates"], key=lambda p: (p["field"], p["operator"], p["value"])
        )
        digest = _hash({"contract": spec, "protocol": PROTOCOL})
        old = self.store.rows(
            "SELECT specification_sha256 FROM adaptive_contracts WHERE id=?", (c.id,)
        )
        if old:
            if old[0]["specification_sha256"] != digest:
                raise ValueError(
                    "Adaptive contract IDs are immutable; a change needs a new version"
                )
            return False
        # A renamed idea with the same observations is not an independent trial.
        identity = {k: spec[k] for k in ("branch", "symbols", "predicates", "minimum_sessions")}
        fingerprint = _hash({"definition": identity, "protocol": PROTOCOL})
        if self.store.rows("SELECT id FROM adaptive_contracts WHERE fingerprint=?", (fingerprint,)):
            return False
        if (
            self.store.rows(
                "SELECT count(*) n FROM adaptive_contracts WHERE branch=? AND state='active'",
                (c.branch,),
            )[0]["n"]
            >= 6
        ):
            return False
        self.store.db.execute(
            "INSERT INTO adaptive_contracts VALUES(?,?,?,?,?,?,?,?,NULL)",
            (
                c.id,
                c.branch,
                "active",
                now.isoformat(),
                now.date().isoformat(),
                digest,
                fingerprint,
                dumps(spec),
            ),
        )
        self.store.event(
            "adaptive_registered",
            {
                "id": c.id,
                "summary": "Prospective observation contract registered; no trading authority.",
                "specification_sha256": digest,
            },
        )
        return True

    def symbols(self):
        symbols = set()
        for row in self.store.rows("SELECT payload FROM adaptive_contracts WHERE state='active'"):
            spec = json.loads(row["payload"])
            symbols.update(spec["symbols"])
            if any(p["field"] == "relative_gap_spy" for p in spec["predicates"]):
                symbols.add("SPY")
        return symbols | {
            r["symbol"]
            for r in self.store.rows("SELECT symbol FROM adaptive_observations WHERE state='open'")
        }

    def _bind(self, row, sessions, now):
        if not self._compatible(row):
            self._binding_status(
                row["id"],
                "Registered protocol differs from this code version; observations held",
                now,
            )
            return
        if row["schedule"]:
            return
        spec = json.loads(row["payload"])
        sessions = sorted({s["date"]: s for s in sessions}.values(), key=lambda s: s["date"])
        # Calendar must cover registration, not begin later and silently skip dates.
        if not sessions or sessions[0]["date"] > row["registered_day"]:
            self._binding_status(
                row["id"], "Calendar does not cover registration day and its previous session", now
            )
            return
        future = [s for s in sessions if s["date"] > row["registered_day"]]
        holding = 1 if spec["branch"] == "intraday" else 5
        required = spec["minimum_sessions"] + holding - 1
        if len(future) < required:
            self._binding_status(
                row["id"],
                f"Calendar has {len(future)} future sessions; fixed protocol requires {required}",
                now,
            )
            return
        selected = future[:required]
        schedule = {
            "bound_at": now.isoformat(),
            "entry_dates": [s["date"] for s in selected[: spec["minimum_sessions"]]],
            "sessions": selected,
            "protocol": PROTOCOL,
        }
        with self.store.transaction():
            self.store.db.execute(
                "UPDATE adaptive_contracts SET schedule=? WHERE id=? AND schedule IS NULL",
                (dumps(schedule), row["id"]),
            )
            for index, session in enumerate(selected[: spec["minimum_sessions"]]):
                previous = max(s["date"] for s in sessions if s["date"] < session["date"])
                exit_session = selected[index + holding - 1]
                for symbol in spec["symbols"]:
                    oid = _hash([row["id"], session["date"], symbol])[:28]
                    payload = {
                        "registered_at": row["registered_at"],
                        "specification_sha256": row["specification_sha256"],
                        "previous_session": previous,
                        "holding_sessions": holding,
                        "entry_start": (_time(session, "open") + timedelta(minutes=15)).isoformat(),
                        "entry_deadline": (
                            _time(session, "open") + timedelta(minutes=30)
                        ).isoformat(),
                        "exit_start": (
                            _time(exit_session, "close") - timedelta(minutes=12)
                        ).isoformat(),
                        "session_close": _time(exit_session, "close").isoformat(),
                    }
                    self.store.db.execute(
                        "INSERT OR IGNORE INTO adaptive_observations VALUES(?,?,?,?,?,?)",
                        (oid, row["id"], session["date"], symbol, "pending", dumps(payload)),
                    )
        self._binding_status(row["id"], "Fixed future session window registered", now)

    def _binding_status(self, contract_id, reason, now):
        key = "adaptive-binding:" + contract_id
        if self.store.get(key, {}).get("reason") != reason:
            self.store.set(key, {"reason": reason, "at": now.isoformat()})

    @staticmethod
    def _compatible(row):
        return row["specification_sha256"] == _hash(
            {"contract": json.loads(row["payload"]), "protocol": PROTOCOL}
        )

    def _features(self, spec, symbol, quote, quotes, packet, now, expected_previous):
        observed = _stamp(packet["observed_at"])
        if (
            observed.astimezone(ET).date() != now.astimezone(ET).date()
            or not 0 <= (now - observed).total_seconds() <= 7200
        ):
            raise ValueError("Market packet is stale, future dated or from another session")
        archive = self.store.rows(
            "SELECT at,payload FROM memory WHERE id=? AND layer='research_input'",
            ("research-input:" + packet["observed_at"],),
        )
        if not archive:
            raise ValueError("Market input has no private contemporaneous archive")
        saved = json.loads(archive[0]["payload"])
        if not observed <= _stamp(archive[0]["at"]) <= now or _hash(saved.get("packet")) != _hash(
            packet
        ):
            raise ValueError("Market input archive is future dated or differs from supplied input")
        daily = packet.get("daily_indicators", {}).get(symbol, {})
        if daily.get("asof") != expected_previous:
            raise ValueError("Daily inputs are missing or not from the previous broker session")
        _, ask = _quote(quote, now)
        result = {}
        for predicate in spec["predicates"]:
            field = predicate["field"]
            if field in ("return_1d", "return_3d", "return_5d"):
                value = float(daily[field])
            elif field == "price_vs_sma20":
                prior, average = float(daily["last_daily_close"]), float(daily["sma20"])
                if prior <= 0 or average <= 0:
                    raise ValueError("Missing positive prior close or average")
                value = prior / average - 1
            else:
                close = float(daily["last_daily_close"])
                if close <= 0:
                    raise ValueError("Missing positive prior close")
                value = ask / close - 1
                if field == "relative_gap_spy":
                    spy = packet.get("daily_indicators", {}).get("SPY", {})
                    if spy.get("asof") != expected_previous or float(spy["last_daily_close"]) <= 0:
                        raise ValueError("SPY prior-session comparison unavailable")
                    _, spy_ask = _quote(quotes.get("SPY", {}), now)
                    value -= spy_ask / float(spy["last_daily_close"]) - 1
            if not math.isfinite(value):
                raise ValueError("Nonfinite feature")
            result[field] = value
        return result

    def bind_calendar(self, sessions, now):
        """Freeze future opportunity dates without observing or inventing prices."""
        now = _stamp(now).astimezone(ET)
        for contract in self.store.rows("SELECT * FROM adaptive_contracts WHERE state='active'"):
            self._bind(contract, sessions, now)

    def observe(self, quotes, packet, now, opened, closed, sessions):
        now = _stamp(now).astimezone(ET)
        self.bind_calendar(sessions, now)
        self.expire(now)
        if opened + timedelta(minutes=15) <= now < min(opened + timedelta(minutes=30), closed):
            rows = self.store.rows(
                "SELECT o.*,c.payload contract FROM adaptive_observations o JOIN adaptive_contracts c ON c.id=o.contract_id WHERE o.state='pending' AND o.day=?",
                (now.date().isoformat(),),
            )
            for row in rows:
                p = json.loads(row["payload"])
                if not _stamp(p["entry_start"]) <= now < _stamp(p["entry_deadline"]):
                    continue
                spec = json.loads(row["contract"])
                if p["specification_sha256"] != _hash({"contract": spec, "protocol": PROTOCOL}):
                    continue
                try:
                    q = quotes.get(row["symbol"], {})
                    bid, ask = _quote(q, now)
                    features = self._features(
                        spec, row["symbol"], q, quotes, packet, now, p["previous_session"]
                    )
                    signal = all(
                        features[x["field"]] >= x["value"]
                        if x["operator"] == "gte"
                        else features[x["field"]] <= x["value"]
                        for x in spec["predicates"]
                    )
                except (KeyError, ValueError, TypeError, ZeroDivisionError) as exc:
                    p["last_missing_reason"] = str(exc)[:200]
                    self.store.db.execute(
                        "UPDATE adaptive_observations SET payload=? WHERE id=?",
                        (dumps(p), row["id"]),
                    )
                    continue
                p.update(
                    {
                        "entered_at": now.isoformat(),
                        "entry_ask": ask,
                        "entry_bid": bid,
                        "signal": signal,
                        "features": features,
                        "input_reference": "research-input:" + packet["observed_at"],
                        "input_sha256": _hash(packet),
                        "quote": q,
                        "promotion_eligible": False,
                    }
                )
                with self.store.transaction():
                    updated = self.store.db.execute(
                        "UPDATE adaptive_observations SET state='open',payload=? WHERE id=? AND state='pending'",
                        (dumps(p), row["id"]),
                    )
                    if updated.rowcount:
                        record_quote(
                            self.store,
                            "adaptive",
                            row["id"],
                            "entry",
                            q,
                            now,
                            {
                                "entry_ask": ask,
                                "assumed_base_cost_fraction": 0.002,
                                "input_sha256": p["input_sha256"],
                                "specification_sha256": p["specification_sha256"],
                            },
                        )
        self.mark(quotes, now)

    def expire(self, now):
        for row in self.store.rows(
            "SELECT * FROM adaptive_observations WHERE state IN ('pending','open')"
        ):
            p = json.loads(row["payload"])
            deadline = p["entry_deadline"] if row["state"] == "pending" else p["session_close"]
            if now < _stamp(deadline):
                continue
            p.update(
                {
                    "closed_at": now.isoformat(),
                    "reason": "Entry window missed; no valid quote and complete known inputs"
                    if row["state"] == "pending"
                    else "Exit window missed; no valid quote before recorded close",
                }
            )
            self.store.db.execute(
                "UPDATE adaptive_observations SET state='not_evaluable',payload=? WHERE id=?",
                (dumps(p), row["id"]),
            )
        self._complete()

    def mark(self, quotes, now):
        self.expire(now)
        for row in self.store.rows(
            "SELECT o.*,c.payload contract FROM adaptive_observations o JOIN adaptive_contracts c ON c.id=o.contract_id WHERE o.state='open'"
        ):
            p = json.loads(row["payload"])
            if p["specification_sha256"] != _hash(
                {"contract": json.loads(row["contract"]), "protocol": PROTOCOL}
            ):
                continue
            if not _stamp(p["exit_start"]) <= now < _stamp(p["session_close"]):
                continue
            try:
                bid, ask = _quote(quotes.get(row["symbol"], {}), now)
            except (KeyError, ValueError, TypeError):
                continue
            gross = bid / p["entry_ask"] - 1
            if abs(gross) > 0.30:
                state = "not_evaluable"
                p["reason"] = (
                    "Large price discontinuity; corporate action versus market move unverified"
                )
            else:
                state = "closed"
                p.update(
                    {
                        "exit_bid": bid,
                        "exit_ask": ask,
                        "baseline_net": gross - 0.002,
                        "baseline_stressed": gross - 0.005,
                        "signal_net": gross - 0.002 if p["signal"] else 0.0,
                        "signal_stressed": gross - 0.005 if p["signal"] else 0.0,
                        "cash_return": 0.0,
                    }
                )
            p["closed_at"] = now.isoformat()
            with self.store.transaction():
                updated = self.store.db.execute(
                    "UPDATE adaptive_observations SET state=?,payload=? WHERE id=? AND state='open'",
                    (state, dumps(p), row["id"]),
                )
                if updated.rowcount:
                    record_quote(
                        self.store,
                        "adaptive",
                        row["id"],
                        "exit",
                        quotes[row["symbol"]],
                        now,
                        {
                            "entry_ask": p["entry_ask"],
                            "gross": gross,
                            "outcome": state,
                            "assumed_base_cost_fraction": 0.002,
                            "assumed_stressed_cost_fraction": 0.005,
                            "baseline_net": p.get("baseline_net"),
                            "signal": p["signal"],
                            "signal_net": p.get("signal_net"),
                        },
                    )
        self._complete()

    def _complete(self):
        self.store.db.execute(
            "UPDATE adaptive_contracts SET state='completed' WHERE state='active' AND schedule IS NOT NULL AND NOT EXISTS(SELECT 1 FROM adaptive_observations o WHERE o.contract_id=adaptive_contracts.id AND o.state IN ('pending','open'))"
        )

    def summary(self):
        trials = []
        for row in self.store.rows("SELECT * FROM adaptive_contracts ORDER BY registered_at,id"):
            spec = json.loads(row["payload"])
            observations = self.store.rows(
                "SELECT day,state,payload FROM adaptive_observations WHERE contract_id=?",
                (row["id"],),
            )
            closed = [
                (r["day"], json.loads(r["payload"])) for r in observations if r["state"] == "closed"
            ]
            dates = sorted({d for d, _ in closed})

            def means(selected):
                groups = {}
                for day, p in selected:
                    groups.setdefault(day, []).append(p)
                result = {}
                for key in ("signal_net", "signal_stressed", "baseline_net", "baseline_stressed"):
                    daily = [sum(p[key] for p in ps) / len(ps) for ps in groups.values()]
                    result[key] = sum(daily) / len(daily) if daily else None
                return result

            signals = sum(bool(p["signal"]) for _, p in closed)
            trials.append(
                {
                    **spec,
                    "state": row["state"],
                    "registered_at": row["registered_at"],
                    "specification_sha256": row["specification_sha256"],
                    "protocol_compatible": self._compatible(row),
                    "schedule": json.loads(row["schedule"]) if row["schedule"] else None,
                    "binding_status": self.store.get(
                        "adaptive-binding:" + row["id"], {"reason": "Awaiting broker calendar"}
                    ),
                    "preregistered_opportunities": len(observations),
                    "pending": sum(r["state"] == "pending" for r in observations),
                    "open": sum(r["state"] == "open" for r in observations),
                    "closed": len(closed),
                    "closed_signals": signals,
                    "closed_sessions": len(dates),
                    "date_composition": date_composition(
                        [(day, p["signal_net"], p["signal"]) for day, p in closed]
                    ),
                    "not_evaluable": sum(r["state"] == "not_evaluable" for r in observations),
                    "cumulative": means(closed),
                    "recent_five_entry_sessions": means(
                        [(d, p) for d, p in closed if d in dates[-5:]]
                    ),
                    "minimum_evidence_counts_met": len(dates) >= spec["minimum_sessions"]
                    and signals >= spec["minimum_signals"],
                    "promotion_eligible": False,
                }
            )
        return {
            "version": PROTOCOL["version"],
            "trials": trials,
            "trial_count": len(trials),
            "broker_orders_allowed": False,
            "automatic_promotion": False,
            "protocol": PROTOCOL,
            "limitations": [
                "Descriptive conditional means, not portfolio returns, executable fills or proof of edge.",
                "Symbols, variants and overlapping swing horizons are dependent. Recent results are diagnostics, not tuning or promotion gates.",
                "All preregistered opportunities and missing observations remain in denominators; return means condition on evaluable outcomes.",
            ],
        }

    def context(self, max_trials=6):
        summary = self.summary()
        fields = (
            "id",
            "hypothesis_id",
            "branch",
            "state",
            "symbols",
            "predicates",
            "closed",
            "closed_signals",
            "closed_sessions",
            "not_evaluable",
            "preregistered_opportunities",
            "cumulative",
            "recent_five_entry_sessions",
        )
        return {
            "trial_count": summary["trial_count"],
            "trials": [{k: t[k] for k in fields} for t in summary["trials"][-max_trials:]],
            "authority": PROTOCOL["authority"],
            "unit": PROTOCOL["unit"],
            "limitations": summary["limitations"],
        }


def context(store, max_trials=6):
    return AdaptiveLab(store).context(max_trials=max_trials)
