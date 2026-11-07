from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from time import monotonic

from .config import ET
from .broker import BrokerError
from .models import Plan
from .store import dumps, utc_now

# done_for_day can resume on the next session; GTC reservations and recovery
# must retain it until the broker confirms an actual terminal state.
TERMINAL = {"filled", "canceled", "expired", "rejected", "replaced"}
EXECUTION_KERNEL = "paper-execution-20261107-r2"


def current_execution_verified(readiness):
    """Historical success certifies a required kernel only when versions match.

    Legacy metadata without an explicit requirement retains its old meaning;
    production preflight always installs this release's required version.
    """
    required = readiness.get("required_execution_kernel")
    return bool(
        readiness.get("execution_verified")
        and (not required or readiness.get("verified_execution_kernel") == required)
    )


def order_id(*parts):
    return "lab-" + hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:36]


def timestamp(value):
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def quote_values(q, now):
    bid, ask = float(q.get("bp", 0)), float(q.get("ap", 0))
    if not (math.isfinite(bid) and math.isfinite(ask) and 0 < bid <= ask):
        raise ValueError("Missing or crossed quote")
    age = (now - timestamp(q["t"])).total_seconds()
    if age < -5 or age > 90:
        raise ValueError("Quote is stale or in the future")
    if (ask - bid) / ((ask + bid) / 2) > 0.005:
        raise ValueError("Spread exceeds 0.5%")
    return bid, ask


class Engine:
    def __init__(self, config, store, broker):
        self.config, self.store, self.broker = config, store, broker

    def add_plans(self, plans, day):
        for plan in plans:
            p = plan if isinstance(plan, Plan) else Plan.model_validate(plan)
            old = self.store.rows("SELECT payload FROM plans WHERE id=?", (p.id,))
            payload = p.model_dump(mode="json")
            if old and json.loads(old[0]["payload"]) != payload:
                raise ValueError("Plan IDs are immutable; revised plans need a new ID")
            self.store.db.execute(
                "INSERT OR IGNORE INTO plans VALUES(?,?,?,?,?)",
                (p.id, day, p.branch, "planned", dumps(payload)),
            )

    def plans(self, states=("planned", "approved")):
        placeholders = ",".join("?" for _ in states)
        return [
            json.loads(r["payload"])
            for r in self.store.rows(
                f"SELECT payload FROM plans WHERE state IN ({placeholders})", states
            )
        ]

    def ingest_order(self, order, branch, plan_id):
        with self.store.transaction():
            known = self.store.rows("SELECT * FROM orders WHERE broker_id=?", (order["id"],))
            cid = order.get("client_order_id") or (
                known[0]["client_id"] if known else f"broker-{order['id']}"
            )
            if known and known[0]["client_id"] != cid:
                raise ValueError("Broker order identity changed")
            self.store.db.execute(
                """INSERT OR IGNORE INTO orders
              (client_id,broker_id,branch,symbol,side,qty,status,plan_id,payload,at)
              VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    cid,
                    order["id"],
                    branch,
                    order["symbol"],
                    order["side"],
                    float(order["qty"]),
                    order["status"],
                    plan_id,
                    dumps(order),
                    utc_now(),
                ),
            )
            row = self.store.rows("SELECT * FROM orders WHERE client_id=?", (cid,))[0]
            if (
                row["symbol"] != order["symbol"]
                or row["side"] != order["side"]
                or row["branch"] != branch
                or row["plan_id"] != plan_id
                or (row["broker_id"] and row["broker_id"] != order["id"])
            ):
                raise ValueError("Broker order does not match its owned intent")
            qty = float(order.get("filled_qty") or 0)
            price = float(order.get("filled_avg_price") or 0)
            requested = float(order["qty"])
            if (
                not math.isfinite(qty)
                or not math.isfinite(price)
                or not math.isfinite(requested)
                or requested <= 0
                or qty < 0
                or qty > requested + 1e-8
                or (qty > 0 and price <= 0)
            ):
                raise ValueError("Invalid broker fill quantity/price")
            if abs(requested - row["qty"]) > 1e-8:
                parents = self.store.rows(
                    "SELECT payload FROM orders WHERE side='buy' AND symbol=? AND branch=? AND plan_id=?",
                    (row["symbol"], branch, plan_id),
                )
                protective_leg = order["side"] == "sell" and any(
                    leg.get("id") == order["id"]
                    for parent in parents
                    for leg in json.loads(parent["payload"]).get("legs", []) or []
                )
                if not protective_leg or requested > row["qty"]:
                    raise ValueError("Broker quantity differs from the authorized intent")
            notional = qty * price
            if not math.isfinite(notional):
                raise ValueError("Invalid broker fill notional")
            delta = qty - row["filled"]
            if delta < -1e-8:
                raise ValueError("Broker cumulative fill quantity decreased")
            if abs(delta) <= 1e-8 and abs(notional - row["notional"]) > 1e-6:
                raise ValueError("Broker corrected fill notional; explicit ledger review required")
            if delta > 1e-8:
                money = notional - row["notional"]
                if money <= 0:
                    raise ValueError("Broker incremental fill notional is inconsistent")
                holdings = self.store.rows(
                    "SELECT * FROM holdings WHERE symbol=?", (order["symbol"],)
                )
                h = holdings[0] if holdings else None
                if order["side"] == "buy":
                    if h and h["branch"] != branch:
                        raise ValueError("Overlapping branch ownership")
                    self.store.db.execute(
                        "UPDATE branches SET cash=cash-? WHERE name=?", (money, branch)
                    )
                    self.store.db.execute(
                        """INSERT INTO holdings VALUES(?,?,?,?,?)
                      ON CONFLICT(symbol) DO UPDATE SET qty=qty+excluded.qty, cost=cost+excluded.cost""",
                        (order["symbol"], branch, delta, money, plan_id),
                    )
                else:
                    if not h or h["branch"] != branch or delta > h["qty"] + 1e-7:
                        raise ValueError("Sell fill exceeds owned position")
                    self.store.db.execute(
                        "UPDATE branches SET cash=cash+? WHERE name=?", (money, branch)
                    )
                    remaining = h["qty"] - delta
                    if remaining < 1e-7:
                        self.store.db.execute(
                            "DELETE FROM holdings WHERE symbol=?", (order["symbol"],)
                        )
                    else:
                        self.store.db.execute(
                            "UPDATE holdings SET qty=?,cost=? WHERE symbol=?",
                            (remaining, h["cost"] * remaining / h["qty"], order["symbol"]),
                        )
                self.store.event(
                    "fill",
                    {
                        "symbol": order["symbol"],
                        "side": order["side"],
                        "qty": delta,
                        "price": money / delta,
                        "plan_id": plan_id,
                    },
                    branch,
                )
            self.store.db.execute(
                """UPDATE orders SET broker_id=?,status=?,qty=?,filled=?,notional=?,payload=?
              WHERE client_id=?""",
                (order["id"], order["status"], requested, qty, notional, dumps(order), cid),
            )
        for leg in order.get("legs") or []:
            self.ingest_order(leg, branch, plan_id)

    def reconcile(self, now=None):
        now = now or datetime.now(timezone.utc)
        self.store.set("reconciled", False)
        for row in self.store.rows(
            "SELECT * FROM orders WHERE status NOT IN (%s)" % ",".join("?" for _ in TERMINAL),
            tuple(TERMINAL),
        ):
            order = (
                self.broker.order(row["broker_id"])
                if row["broker_id"]
                else self.broker.by_client(row["client_id"])
            )
            if order:
                self.ingest_order(order, row["branch"], row["plan_id"])
            elif row["status"] == "prepared":
                # A process can die between persisting intent and submitting it. Never
                # blindly resubmit an ambiguous intent after recovery.
                self.store.event("ambiguous_order", {"client_id": row["client_id"]}, row["branch"])
                raise ValueError("Unresolved prepared order; submission outcome must be inspected")
        # Retrieve bracket legs even after the parent is filled; fills on protective
        # orders must never be lost merely because the parent reached a terminal state.
        for h in self.store.rows("SELECT * FROM holdings"):
            parents = self.store.rows(
                "SELECT * FROM orders WHERE plan_id=? AND side='buy'", (h["plan_id"],)
            )
            for row in parents:
                if row["broker_id"]:
                    self.ingest_order(
                        self.broker.order(row["broker_id"]), row["branch"], row["plan_id"]
                    )
        account = self.broker.account()
        positions = self.broker.positions()
        open_orders = self.broker.orders()
        if any(
            not math.isfinite(float(account[key])) or float(account[key]) < 0
            for key in ("cash", "equity")
        ):
            raise ValueError("Broker account cash/equity is not a valid nonnegative balance")
        if any(
            not math.isfinite(float(position[key]))
            for position in positions
            for key in ("qty", "market_value")
        ):
            raise ValueError("Broker position quantity/value is not finite")
        if len({p["symbol"] for p in positions}) != len(positions):
            raise ValueError("Broker returned duplicate position symbols")
        known = {r["broker_id"] for r in self.store.rows("SELECT broker_id FROM orders")}
        unknown_orders = [o for o in open_orders if o["id"] not in known]
        ledger = {h["symbol"]: h for h in self.store.rows("SELECT * FROM holdings")}
        actual = {p["symbol"]: p for p in positions}
        mismatches = []
        for symbol in set(ledger) | set(actual):
            a = float(actual.get(symbol, {}).get("qty", 0))
            b = ledger.get(symbol, {}).get("qty", 0)
            if abs(a - b) > 1e-6:
                mismatches.append(symbol)
        if (
            account.get("status") != "ACTIVE"
            or account.get("trading_blocked")
            or account.get("account_blocked")
        ):
            mismatches.append("account_blocked")
        # Deposits, corporate actions, or external trading must not silently alter
        # branch results. Reconciliation failure closes entry gates.
        ledger_cash = sum(r["cash"] for r in self.store.rows("SELECT cash FROM branches"))
        if abs(ledger_cash - float(account["cash"])) > 1.0:
            mismatches.append("cash_ledger")
        self.store.set(
            "account",
            {
                k: account.get(k)
                for k in ["status", "cash", "equity", "buying_power", "options_trading_level"]
            },
        )
        self.store.set("broker_positions", positions)
        self.store.set("broker_open_orders", len(open_orders))
        self.store.set(
            "reconciliation_errors",
            mismatches + (["external_open_orders"] if unknown_orders else []),
        )
        valid = not mismatches and not unknown_orders
        self.store.set("reconciled", valid)
        self.store.set("last_reconciled", now.isoformat())
        marks = {p["symbol"]: float(p["market_value"]) for p in positions}
        day = now.astimezone(ET).date().isoformat()
        for branch in self.store.rows("SELECT * FROM branches"):
            equity = branch["cash"] + sum(
                marks.get(h["symbol"], h["cost"])
                for h in ledger.values()
                if h["branch"] == branch["name"]
            )
            high = max(branch["high_water"], equity)
            previous = self.store.rows(
                "SELECT value FROM equity WHERE branch=? AND day<? ORDER BY id DESC LIMIT 1",
                (branch["name"], day),
            )
            key = f"sod:{day}:{branch['name']}"
            if self.store.get(key) is None:
                self.store.set(key, previous[0]["value"] if previous else equity)
            loss = equity - self.store.get(key)
            reason = (
                "Daily loss threshold reached"
                if loss <= -200
                else ("10% high-water drawdown" if equity <= high * 0.9 else "")
            )
            self.store.db.execute(
                "UPDATE branches SET high_water=? WHERE name=?", (high, branch["name"])
            )
            if reason:
                if reason == "Daily loss threshold reached":
                    self.store.set("daily-halt:" + branch["name"], day)
                self.store.db.execute(
                    "UPDATE branches SET paused=1,pause_reason=? WHERE name=?",
                    (reason, branch["name"]),
                )
            self.store.db.execute(
                "INSERT OR IGNORE INTO equity(at,day,branch,value) VALUES(?,?,?,?)",
                (now.isoformat(), day, branch["name"], equity),
            )
            # Daily halts expire on a new session, drawdown halts do not.
            if (
                not reason
                and branch["pause_reason"] == "Daily loss threshold reached"
                and loss > -200
                and self.store.get("daily-halt:" + branch["name"]) != day
            ):
                self.store.db.execute(
                    "UPDATE branches SET paused=0,pause_reason='' WHERE name=?", (branch["name"],)
                )
        if not valid:
            self.store.event(
                "reconciliation_block", {"errors": self.store.get("reconciliation_errors")}
            )
        return valid

    def validate_entry(self, plan, quote, now, close):
        if (
            not self.config.execution
            or now.astimezone(ET).date().isoformat() < self.config.start_date
        ):
            raise ValueError("Paper execution disabled or start date not reached")
        if not self.store.get("market_open", False):
            raise ValueError("Broker regular session is not confirmed open")
        if not current_execution_verified(self.store.get("readiness", {})):
            raise ValueError("Execution smoke check not verified")
        if not self.store.get("reconciled"):
            raise ValueError("Broker/ledger not reconciled")
        age = (now - timestamp(self.store.get("last_reconciled"))).total_seconds()
        if age > 90 or age < -5:
            raise ValueError("Account reconciliation stale")
        if self.store.get("research_refresh_required", False):
            raise ValueError("Material event requires fresh research before entry")
        if self.store.get("entry_budget_blocked", False):
            raise ValueError("Model/quota unavailable; new entries blocked")
        p = Plan.model_validate(plan)
        if p.branch == "options":
            raise ValueError("Options remain shadow-only with indicative data")
        if now >= p.expires_at or now >= close - timedelta(minutes=30):
            raise ValueError("Plan expired or entry cutoff reached")
        if not p.event_risk_known or p.confidence < 0.65:
            raise ValueError("Unresolved event risk or insufficient confidence")
        for source in p.evidence:
            observed = source.observed_at
            if observed.tzinfo is None or not -5 <= (now - observed).total_seconds() <= 86400:
                raise ValueError("Evidence stale or invalid")
        branch = self.store.rows("SELECT * FROM branches WHERE name=?", (p.branch,))[0]
        if branch["paused"]:
            raise ValueError(branch["pause_reason"])
        if self.store.rows("SELECT * FROM orders WHERE plan_id=?", (p.id,)):
            raise ValueError("Plan already submitted; no duplicate entry")
        if self.store.rows("SELECT * FROM holdings WHERE symbol=?", (p.symbol,)):
            raise ValueError("Symbol already held; overlapping branches/pyramiding blocked")
        if any(o["symbol"] == p.symbol for o in self.store.get("broker_pending", [])):
            raise ValueError("Symbol has pending order")
        if self.store.rows(
            "SELECT * FROM orders WHERE symbol=? AND status NOT IN (%s)"
            % ",".join("?" for _ in TERMINAL),
            (p.symbol, *TERMINAL),
        ):
            raise ValueError("Symbol has a pending order")
        bid, ask = quote_values(quote, now)
        if ask < 5:
            raise ValueError("Pilot universe excludes stocks below $5")
        if not p.entry_low <= ask <= p.entry_high:
            raise ValueError("Entry condition not satisfied")
        limit, stop, target = round(ask, 2), round(p.stop, 2), round(p.target, 2)
        if not 0 < stop < limit < target or not p.entry_low <= limit <= p.entry_high:
            raise ValueError("Rounded broker prices violate the plan's entry/risk interval")
        if (target - limit) / (limit - stop) < 1.5:
            raise ValueError("Reward/risk below 1.5")
        pending = self.store.rows(
            "SELECT * FROM orders WHERE branch=? AND side='buy' AND status NOT IN (%s)"
            % ",".join("?" for _ in TERMINAL),
            (p.branch, *TERMINAL),
        )
        owned_symbols = {
            h["symbol"]
            for h in self.store.rows("SELECT symbol FROM holdings WHERE branch=?", (p.branch,))
        }
        owned_symbols.update(r["symbol"] for r in pending)
        if len(owned_symbols) >= 5:
            raise ValueError("Maximum five positions/pending symbols per branch")
        reserved = sum(
            (r["qty"] - r["filled"]) * float(json.loads(r["payload"]).get("limit_price") or 0)
            for r in pending
        )
        aggregate_reserved = sum(
            (r["qty"] - r["filled"]) * float(json.loads(r["payload"]).get("limit_price") or 0)
            for r in self.store.rows(
                "SELECT * FROM orders WHERE side='buy' AND status NOT IN (%s)"
                % ",".join("?" for _ in TERMINAL),
                tuple(TERMINAL),
            )
        )
        cash = min(
            branch["cash"] - reserved, float(self.store.get("account")["cash"]) - aggregate_reserved
        )
        # Modest pilot sizing: 20% branch notional, $50 initial risk, within
        # the approved $100 ceiling. Aggregate planned stop exposure <= $300.
        exposure = 0
        for h in self.store.rows("SELECT * FROM holdings WHERE branch=?", (p.branch,)):
            rows = self.store.rows("SELECT payload FROM plans WHERE id=?", (h["plan_id"],))
            if rows:
                hp = json.loads(rows[0]["payload"])
                exposure += max(0, h["cost"] - h["qty"] * hp["stop"])
        for pending_order in pending:
            intent = json.loads(pending_order["payload"])
            pending_stop = float((intent.get("stop_loss") or {}).get("stop_price") or 0)
            pending_limit = float(intent.get("limit_price") or 0)
            exposure += max(0, pending_order["qty"] - pending_order["filled"]) * max(
                0, pending_limit - pending_stop
            )
        if exposure >= 300:
            raise ValueError("Aggregate branch risk limit")
        cost_per_share = limit * 0.001 + max(0, limit - bid)
        pilot_risk = 12.5 if self.store.get("incumbent_filter:" + p.branch) else 50
        qty = math.floor(
            min(
                2000 / limit,
                cash / limit,
                min(pilot_risk, 300 - exposure) / (limit - stop + cost_per_share),
            )
        )
        if qty < 1:
            raise ValueError("Insufficient unencumbered capital/risk capacity")
        return qty, limit

    def submit_intent(self, payload, branch, plan_id):
        cid = payload["client_order_id"]
        existing = self.store.rows("SELECT * FROM orders WHERE client_id=?", (cid,))
        if existing:
            return self.broker.by_client(cid)
        with self.store.transaction():
            self.store.db.execute(
                """INSERT INTO orders
              (client_id,branch,symbol,side,qty,status,plan_id,payload,at)
              VALUES(?,?,?,?,?,'prepared',?,?,?)""",
                (
                    cid,
                    branch,
                    payload["symbol"],
                    payload["side"],
                    float(payload["qty"]),
                    plan_id,
                    dumps(payload),
                    utc_now(),
                ),
            )
        try:
            order = self.broker.submit(payload)
        except Exception as exc:
            if isinstance(exc, BrokerError) and 400 <= exc.status < 500:
                self.store.db.execute(
                    "UPDATE orders SET status='rejected' WHERE client_id=?", (cid,)
                )
                self.store.event(
                    "order_rejected",
                    {"symbol": payload["symbol"], "http_status": exc.status},
                    branch,
                )
                raise
            # Recover the same broker order after a timeout. Unknown outcomes
            # remain prepared, closing entry gates until reconciled.
            order = self.broker.by_client(cid)
            if not order:
                raise
        self.ingest_order(order, branch, plan_id)
        return order

    def enter(self, plan, quote, now, close):
        started = monotonic()
        qty, limit = self.validate_entry(plan, quote, now, close)
        asset = self.broker.asset(plan["symbol"])
        if not asset.get("tradable") or asset.get("status") != "active":
            raise ValueError("Asset is not tradable")
        # Asset lookup may block. Recheck all time-sensitive gates immediately
        # before submission, using elapsed time rather than a stale tick timestamp.
        qty, limit = self.validate_entry(
            plan, quote, now + timedelta(seconds=max(0, monotonic() - started)), close
        )
        payload = {
            "symbol": plan["symbol"],
            "qty": str(qty),
            "side": "buy",
            "type": "limit",
            "limit_price": str(limit),
            "time_in_force": "gtc",
            "extended_hours": False,
            "order_class": "bracket",
            "client_order_id": order_id(plan["id"], "entry"),
            "take_profit": {"limit_price": str(round(plan["target"], 2))},
            "stop_loss": {"stop_price": str(round(plan["stop"], 2))},
        }
        order = self.submit_intent(payload, plan["branch"], plan["id"])
        self.store.db.execute("UPDATE plans SET state='submitted' WHERE id=?", (plan["id"],))
        self.store.event(
            "order_submitted",
            {"symbol": plan["symbol"], "qty": qty, "plan_id": plan["id"]},
            plan["branch"],
        )
        return order

    def execution_check_deadline(self, row, now):
        """Recognize only the exact persisted, bounded operational entry intent."""
        day = now.astimezone(ET).date().isoformat()
        stage = self.store.get("smoke:" + day, {})
        if (
            row["plan_id"] != "operational-smoke-" + day
            or row["client_id"] != order_id("smoke", day, "buy")
            or stage.get("entry_client_id") != row["client_id"]
            or row["branch"] != "intraday"
            or row["symbol"] != "SPY"
            or row["side"] != "buy"
            or row["qty"] != 1
            or stage.get("state") not in ("submitted", "cancel_requested")
        ):
            return None
        try:
            started, deadline = timestamp(stage["at"]), timestamp(stage["expires_at"])
            if (
                started.astimezone(ET).date().isoformat() == day
                and started <= now
                and deadline == started + timedelta(minutes=2)
            ):
                return deadline
        except (KeyError, TypeError, ValueError):
            pass
        return None

    def cancel_entries(self, now, close):
        for row in self.store.rows("SELECT * FROM orders WHERE side='buy'"):
            if row["status"] in TERMINAL or not row["broker_id"]:
                continue
            plans = self.store.rows("SELECT payload FROM plans WHERE id=?", (row["plan_id"],))
            check_deadline = self.execution_check_deadline(row, now)
            deadline = check_deadline or (
                timestamp(json.loads(plans[0]["payload"])["expires_at"]) if plans else None
            )
            expired = deadline is None or now >= deadline
            paused = self.store.rows("SELECT paused FROM branches WHERE name=?", (row["branch"],))[
                0
            ]["paused"]
            if expired or paused or now >= close - timedelta(minutes=30):
                reason = (
                    "branch_paused"
                    if paused
                    else "closing_cutoff"
                    if now >= close - timedelta(minutes=30)
                    else "missing_plan_or_intent"
                    if deadline is None
                    else "execution_check_timeout"
                    if check_deadline
                    else "plan_expired"
                )
                self.broker.cancel(row["broker_id"])
                if check_deadline:
                    key = "smoke:" + now.astimezone(ET).date().isoformat()
                    self.store.set(
                        key,
                        {
                            **self.store.get(key),
                            "state": "cancel_requested",
                            "cancel_requested_at": now.isoformat(),
                            "reason": reason,
                        },
                    )
                self.store.event(
                    "entry_cancellation_requested",
                    {
                        "symbol": row["symbol"],
                        "plan_id": row["plan_id"],
                        "reason": reason,
                        "observed_order_status": row["status"],
                    },
                    row["branch"],
                )

    @staticmethod
    def _is_liquidation_order(row):
        return (
            row["side"] == "sell"
            and str(row.get("plan_id") or "").startswith(("close:", "exit:"))
            and json.loads(row["payload"]).get("type") == "market"
        )

    def _submit_liquidation(self, holding, purpose, day):
        """Retry only a confirmed terminal attempt; ambiguous intents keep their ID."""
        if self.store.rows(
            "SELECT client_id FROM orders WHERE symbol=? AND status NOT IN (%s)"
            % ",".join("?" for _ in TERMINAL),
            (holding["symbol"], *TERMINAL),
        ):
            # A prior-day done_for_day order, held child, or unconfirmed cancel
            # may be absent from status=open responses and still resume later.
            return False
        scope = f"{purpose}:{day}:{holding['symbol']}"
        previous = self.store.rows(
            "SELECT * FROM orders WHERE plan_id=? AND side='sell' ORDER BY at,client_id", (scope,)
        )
        if any(row["status"] not in TERMINAL for row in previous):
            return False
        attempt = len(previous)
        payload = {
            "symbol": holding["symbol"],
            "qty": str(holding["qty"]),
            "side": "sell",
            "type": "market",
            "time_in_force": "day",
            "client_order_id": order_id(
                purpose, day, holding["symbol"], holding["plan_id"], attempt
            ),
        }
        self.store.event(
            "liquidation_attempt",
            {
                "symbol": holding["symbol"],
                "purpose": purpose,
                "attempt": attempt + 1,
                "quantity": holding["qty"],
                "previous_terminal_attempts": len(previous),
            },
            holding["branch"],
        )
        order = self.submit_intent(payload, holding["branch"], scope)
        return bool(order and order.get("status") not in {"rejected", "canceled", "expired"})

    def overdue_intraday(self, now):
        """Intraday holdings carried from an older or unverified entry session."""
        day = now.astimezone(ET).date().isoformat()
        overdue = []
        for holding in self.store.rows("SELECT * FROM holdings WHERE branch='intraday'"):
            parents = self.store.rows(
                "SELECT at,payload FROM orders WHERE plan_id=? AND side='buy' AND filled>0",
                (holding["plan_id"],),
            )
            entry_days = []
            try:
                for parent in parents:
                    payload = json.loads(parent["payload"])
                    entered = timestamp(
                        payload.get("filled_at") or payload.get("submitted_at") or parent["at"]
                    )
                    if entered.tzinfo is None:
                        raise ValueError("Unknown entry timezone")
                    entry_days.append(entered.astimezone(ET).date().isoformat())
            except (ValueError, TypeError, KeyError):
                entry_days = []
            if not entry_days or min(entry_days) < day or max(entry_days) > day:
                overdue.append(holding["symbol"])
        return overdue

    def close_intraday(self):
        if not self.store.get("reconciled"):
            raise ValueError("Cannot cancel protection while broker state is unreconciled")
        # Cancel owned outstanding intraday orders first, including bracket legs.
        rows = self.store.rows("SELECT * FROM orders WHERE branch='intraday'")
        for row in rows:
            if row["status"] not in TERMINAL and row["broker_id"]:
                if self._is_liquidation_order(row):
                    continue
                self.broker.cancel(row["broker_id"])
        self.reconcile()
        open_symbols = {o["symbol"] for o in self.broker.orders()}
        for h in self.store.rows("SELECT * FROM holdings WHERE branch='intraday'"):
            if h["symbol"] in open_symbols:
                continue
            if not self.store.get("reconciled"):
                raise ValueError("Cannot close mismatched ledger automatically")
            day = datetime.now(ET).date().isoformat()
            self._submit_liquidation(h, "close", day)

    def exit_holding(self, symbol, reason):
        rows = self.store.rows("SELECT * FROM holdings WHERE symbol=?", (symbol,))
        if not rows or not self.store.get("reconciled"):
            return False
        h = rows[0]
        # Cancel and confirm protective orders before an independent sell. Keep
        # existing protection until an exit has actually been authorized.
        for row in self.store.rows("SELECT * FROM orders WHERE symbol=?", (symbol,)):
            if row["status"] not in TERMINAL and row["broker_id"]:
                if self._is_liquidation_order(row):
                    continue
                self.broker.cancel(row["broker_id"])
        if not self.reconcile():
            return False
        if any(o["symbol"] == symbol for o in self.broker.orders()):
            return False
        rows = self.store.rows("SELECT * FROM holdings WHERE symbol=?", (symbol,))
        if not rows:
            return True
        h = rows[0]
        day = datetime.now(ET).date().isoformat()
        if not self._submit_liquidation(h, "exit", day):
            return False
        self.store.event(
            "decision", {"symbol": symbol, "action": "exit", "reason": reason}, h["branch"]
        )
        return True

    def ensure_protection(self):
        """Repair missing protective stops after rejected exits/canceled brackets."""
        if not self.store.get("reconciled"):
            return
        open_orders = self.broker.orders()

        def flatten(items):
            result = []
            for item in items:
                result.append(item)
                result.extend(flatten(item.get("legs") or []))
            return result

        open_orders = flatten(open_orders)
        for h in self.store.rows("SELECT * FROM holdings"):
            active = [
                o
                for o in open_orders
                if o["symbol"] == h["symbol"] and o.get("status") not in TERMINAL
            ]
            partial_entries = [
                o for o in active if o["side"] == "buy" and float(o.get("filled_qty") or 0) > 0
            ]
            if partial_entries:
                for order in active:
                    self.broker.cancel(order["id"])
                self.store.event(
                    "protection_repair",
                    {
                        "symbol": h["symbol"],
                        "reason": "Canceling partial entry remainder before protecting confirmed quantity",
                    },
                    h["branch"],
                )
                continue
            sells = [
                o
                for o in active
                if o["side"] == "sell" and o.get("status") not in ("held", "pending_cancel")
            ]
            protection = [
                o
                for o in sells
                if o.get("type") in ("stop", "stop_limit", "trailing_stop", "market")
            ]
            if (
                len(protection) == 1
                and abs(
                    float(protection[0].get("qty") or 0)
                    - float(protection[0].get("filled_qty") or 0)
                    - h["qty"]
                )
                <= 1e-8
            ):
                continue
            if active:
                # Cancel an incomplete OCO/protective configuration before creating
                # another sell; never stack competing exits on the same shares.
                for order in active:
                    self.broker.cancel(order["id"])
                continue
            rows = self.store.rows("SELECT payload FROM plans WHERE id=?", (h["plan_id"],))
            stop = json.loads(rows[0]["payload"])["stop"] if rows else None
            if stop is None:
                for o in self.store.rows(
                    "SELECT payload FROM orders WHERE symbol=? AND side='sell' ORDER BY at DESC",
                    (h["symbol"],),
                ):
                    data = json.loads(o["payload"])
                    if data.get("stop_price"):
                        stop = float(data["stop_price"])
                        break
            if stop is None:
                raise ValueError("Missing protective stop reference for owned holding")
            if abs(h["qty"] - round(h["qty"])) > 1e-8:
                self.exit_holding(
                    h["symbol"],
                    "Fractional partial fill cannot use whole-share protective stop; closing confirmed quantity",
                )
                continue
            q = self.broker.quotes([h["symbol"]]).get(h["symbol"], {})
            bid, _ = quote_values(q, datetime.now(timezone.utc))
            if bid <= stop:
                self.exit_holding(
                    h["symbol"], "Protective stop already breached while restoring protection"
                )
                continue
            attempt = self.store.rows(
                "SELECT count(*) n FROM orders WHERE symbol=? AND side='sell'", (h["symbol"],)
            )[0]["n"]
            payload = {
                "symbol": h["symbol"],
                "side": "sell",
                "qty": str(h["qty"]),
                "type": "stop",
                "stop_price": str(round(stop, 2)),
                "time_in_force": "gtc",
                "client_order_id": order_id("protect", h["plan_id"], attempt),
            }
            self.submit_intent(payload, h["branch"], h["plan_id"])
            self.store.event(
                "protection_repair",
                {
                    "symbol": h["symbol"],
                    "reason": "Broker-held stop restored for confirmed quantity",
                },
                h["branch"],
            )
