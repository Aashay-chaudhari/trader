"""Private broker-activity receipts and an explicit fee/cash reconciliation bridge.

Intake never changes branch cash. A separate explicit application step can book
only fees tied to fully matched owned executions; uncertainty stays unattributed.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation

from .config import ET
from .engine import timestamp
from .store import dumps, utc_now


def _decimal(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Invalid broker activity amount") from exc
    if not result.is_finite():
        raise ValueError("Non-finite broker activity amount")
    return result


def _hash(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _fill_day(activity):
    stamp = timestamp(activity["transaction_time"])
    if stamp.tzinfo is None:
        raise ValueError("Activity timestamp lacks timezone")
    return stamp.astimezone(ET).date().isoformat()


class Accounting:
    def __init__(self, store):
        self.store = store
        store.db.executescript("""
        CREATE TABLE IF NOT EXISTS broker_activities(
          id TEXT PRIMARY KEY, activity_type TEXT NOT NULL,
          content_hash TEXT NOT NULL, payload TEXT NOT NULL, first_seen TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS booked_fees(
          activity_id TEXT PRIMARY KEY REFERENCES broker_activities(id),
          branch TEXT NOT NULL, amount TEXT NOT NULL, receipt_hash TEXT NOT NULL,
          evidence TEXT NOT NULL, booked_at TEXT NOT NULL);
        """)

    def refresh(self, broker):
        """Broker GETs and private receipt intake only; no ledger adjustment."""
        return self.record(broker.account_activities(), complete_history=True)

    def record(self, activities, *, complete_history=False, observed_at=None):
        observed_at = observed_at or utc_now()
        identities, normalized = set(), []
        for activity in activities:
            identity = activity.get("id") if isinstance(activity, dict) else None
            kind = activity.get("activity_type") if isinstance(activity, dict) else None
            if not isinstance(identity, str) or not identity or identity in identities:
                raise ValueError("Missing or duplicate broker activity identity")
            if not isinstance(kind, str) or not kind:
                raise ValueError("Missing broker activity type")
            identities.add(identity)
            normalized.append((identity, kind, _hash(activity), dumps(activity), observed_at))
        receipt_hash = _hash(sorted((r[0], r[2]) for r in normalized))
        with self.store.transaction():
            for row in normalized:
                prior = self.store.rows(
                    "SELECT content_hash FROM broker_activities WHERE id=?", (row[0],)
                )
                if prior and prior[0]["content_hash"] != row[2]:
                    raise ValueError(
                        "Broker activity identity changed; preserve original and review"
                    )
                self.store.db.execute(
                    "INSERT OR IGNORE INTO broker_activities VALUES(?,?,?,?,?)", row
                )
            self.store.set(
                "account_activity_receipt",
                {
                    "observed_at": observed_at,
                    "receipt_hash": receipt_hash,
                    "complete_history": bool(complete_history),
                    "activity_ids": sorted(identities),
                },
            )
        return self.summary()

    def _snapshot(self):
        receipt = self.store.get("account_activity_receipt", {})
        allowed = set(receipt.get("activity_ids", []))
        activities = [
            json.loads(row["payload"])
            for row in self.store.rows("SELECT id,payload FROM broker_activities")
            if row["id"] in allowed
        ]
        return receipt, activities

    def _owned_fills(self, activities):
        """Match the complete execution stream to durable ledger orders exactly."""
        grouped = defaultdict(list)
        for activity in activities:
            if activity.get("activity_type") == "FILL":
                grouped[activity.get("order_id")].append(activity)
        matched = {}
        for order_id, fills in grouped.items():
            orders = self.store.rows("SELECT * FROM orders WHERE broker_id=?", (order_id,))
            if len(orders) != 1:
                continue
            order = orders[0]
            if order["branch"] not in ("intraday", "swing", "options"):
                continue
            try:
                quantity = sum((_decimal(f["qty"]) for f in fills), Decimal(0))
                notional = sum(
                    (_decimal(f["qty"]) * _decimal(f["price"]) for f in fills), Decimal(0)
                )
                if quantity <= 0 or notional <= 0:
                    continue
                if abs(quantity - _decimal(order["filled"])) > Decimal("0.00000001"):
                    continue
                if abs(notional - _decimal(order["notional"])) > Decimal("0.000001"):
                    continue
                if any(
                    f.get("symbol") != order["symbol"]
                    or f.get("side") != order["side"]
                    or f.get("type") != "fill"
                    or _decimal(f["qty"]) <= 0
                    or _decimal(f["price"]) <= 0
                    for f in fills
                ):
                    continue
                for fill in fills:
                    _fill_day(fill)
                    matched[fill["id"]] = order["branch"]
            except (ValueError, TypeError, KeyError):
                continue
        return matched

    def candidates(self):
        """Private allocation candidates. IDs and raw descriptions never go public."""
        receipt, activities = self._snapshot()
        owned = self._owned_fills(activities)
        fills_by_day = defaultdict(list)
        invalid_fill_date = False
        for activity in activities:
            if activity["activity_type"] == "FILL":
                try:
                    fills_by_day[_fill_day(activity)].append(activity)
                except (ValueError, KeyError, TypeError):
                    invalid_fill_date = True
        results = []
        for activity in activities:
            if activity["activity_type"] != "FEE":
                continue
            result = {
                "activity_id": activity["id"],
                "branch": None,
                "amount": None,
                "trade_date": None,
                "category": "other",
                "reason": "incomplete_history",
                "attribution_status": "unattributed",
            }
            results.append(result)
            try:
                amount = _decimal(activity.get("net_amount"))
                result["amount"] = str(amount)
                category = activity.get("activity_sub_type")
                result["category"] = category if category in ("CAT", "REG") else "other"
                day = date.fromisoformat(activity["date"]).isoformat()
                result["trade_date"] = day
                if not receipt.get("complete_history"):
                    continue
                if invalid_fill_date:
                    result["reason"] = "fill_date_coverage_unverified"
                    continue
                if (
                    activity.get("status") != "executed"
                    or activity.get("currency") != "USD"
                    or amount >= 0
                ):
                    result["reason"] = "not_a_posted_usd_fee_debit"
                    continue
                fills = fills_by_day.get(day, [])
                direct_order = activity.get("order_id")
                if direct_order:
                    fills = [f for f in fills if f.get("order_id") == direct_order]
                    linkage = "broker_order_id_and_trade_date"
                else:
                    # Only known daily transaction-fee formats establish trade-day
                    # linkage. Provider description/account identifiers stay private.
                    description = str(activity.get("description", ""))
                    if category == "CAT":
                        match = re.fullmatch(
                            r"CAT fee for proceed of (\d+) trades on (\d{4}-\d{2}-\d{2}) by .+",
                            description,
                        )
                        linked = bool(match and match[2] == day and int(match[1]) == len(fills))
                    elif category == "REG":
                        match = re.fullmatch(
                            r"REG fee for proceed of \$([\d.]+) on (\d{4}-\d{2}-\d{2}) by .+",
                            description,
                        )
                        proceeds = sum(
                            (
                                _decimal(f["qty"]) * _decimal(f["price"])
                                for f in fills
                                if f.get("side") == "sell"
                            ),
                            Decimal(0),
                        )
                        linked = bool(match and match[2] == day and _decimal(match[1]) == proceeds)
                    else:
                        linked = False
                    if not linked:
                        result["reason"] = "fee_trade_linkage_unverified"
                        continue
                    linkage = "verified_daily_transaction_fee_and_unique_owned_branch"
                if not fills or any(f["id"] not in owned for f in fills):
                    result["reason"] = "missing_external_or_unmatched_fill"
                    continue
                branches = {owned[f["id"]] for f in fills}
                if len(branches) != 1:
                    result["reason"] = "ambiguous_multiple_branches"
                    continue
                result.update(
                    branch=branches.pop(),
                    reason=linkage,
                    attribution_status="attributed_unbooked",
                    matched_fill_ids=[f["id"] for f in fills],
                )
                booked = self.store.rows(
                    "SELECT * FROM booked_fees WHERE activity_id=?", (activity["id"],)
                )
                if booked:
                    if (
                        booked[0]["branch"] != result["branch"]
                        or _decimal(booked[0]["amount"]) != amount
                    ):
                        raise ValueError("Booked fee no longer matches evidence")
                    result["attribution_status"] = "booked"
            except (ValueError, KeyError, TypeError):
                result.update(
                    branch=None,
                    reason="invalid_or_inconsistent_fee_evidence",
                    attribution_status="unattributed",
                )
        return results

    def book_attributed_fees(self, activity_ids, *, expected_receipt_hash):
        """Explicit, atomic and idempotent local bookkeeping; never a broker action."""
        identities = set(activity_ids)
        with self.store.transaction():
            receipt = self.store.get("account_activity_receipt", {})
            if not expected_receipt_hash or receipt.get("receipt_hash") != expected_receipt_hash:
                raise ValueError("Activity receipt changed; review before booking")
            candidates = {c["activity_id"]: c for c in self.candidates()}
            selected = [candidates.get(identity) for identity in identities]
            if any(
                not c or c["attribution_status"] not in ("attributed_unbooked", "booked")
                for c in selected
            ):
                raise ValueError("Fee attribution is not unambiguous")
            if not self.summary()["cash_bridge"]["arithmetic_matches"]:
                # This also prevents charging a fee twice after an out-of-band
                # ledger adjustment that lacks our application receipt.
                raise ValueError("Unbooked fees do not match the cash bridge; review first")
            for candidate in selected:
                if candidate["attribution_status"] == "booked":
                    continue
                self.store.db.execute(
                    "INSERT INTO booked_fees VALUES(?,?,?,?,?,?)",
                    (
                        candidate["activity_id"],
                        candidate["branch"],
                        candidate["amount"],
                        expected_receipt_hash,
                        dumps(candidate),
                        utc_now(),
                    ),
                )
                cursor = self.store.db.execute(
                    "UPDATE branches SET cash=cash+? WHERE name=?",
                    (float(_decimal(candidate["amount"])), candidate["branch"]),
                )
                if cursor.rowcount != 1:
                    raise ValueError("Fee branch unavailable")
                self.store.event(
                    "fee_booked",
                    {k: candidate[k] for k in ("amount", "category", "trade_date", "reason")},
                    candidate["branch"],
                )
        return self.summary()

    def summary(self):
        receipt, activities = self._snapshot()
        candidates = self.candidates()
        fees = [
            {
                k: c[k]
                for k in (
                    "trade_date",
                    "category",
                    "amount",
                    "branch",
                    "attribution_status",
                    "reason",
                )
            }
            for c in candidates
        ]
        unbooked = sum(
            (
                _decimal(c["amount"])
                for c in candidates
                if c["attribution_status"] == "attributed_unbooked"
            ),
            Decimal(0),
        )
        ledger_cash = sum(
            (_decimal(b["cash"]) for b in self.store.rows("SELECT cash FROM branches")), Decimal(0)
        )
        broker_value = self.store.get("account", {}).get("cash")
        broker_cash = _decimal(broker_value) if broker_value is not None else None
        gap = broker_cash - ledger_cash if broker_cash is not None else None
        remainder = gap - unbooked if gap is not None else None
        return {
            "observed_at": receipt.get("observed_at"),
            "complete_history": receipt.get("complete_history", False),
            "activity_counts": dict(Counter(a["activity_type"] for a in activities)),
            "fee_count": len(fees),
            "fees": fees[-50:],
            "omitted_fee_rows": max(0, len(fees) - 50),
            "cash_bridge": {
                "ledger_cash": float(ledger_cash),
                "broker_cash": float(broker_cash) if broker_cash is not None else None,
                "broker_cash_observed_at": self.store.get("last_reconciled"),
                "broker_minus_ledger": float(gap) if gap is not None else None,
                "attributed_unbooked_fee_net": float(unbooked),
                "remaining_after_attributed_fees": float(remainder)
                if remainder is not None
                else None,
                "arithmetic_matches": bool(
                    remainder is not None and abs(remainder) < Decimal("0.000001")
                ),
            },
            "basis": "Broker activity receipts explain cash differences; intake does not book fees. Only explicitly applied, uniquely linked fees change branch cash. Unknown transfers, corrections and ambiguous fees require review. Raw IDs/descriptions remain private.",
        }


def accounting_summary(store):
    """Public read-only summary without creating tables during export."""
    if not store.rows(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='broker_activities'"
    ):
        return {
            "observed_at": None,
            "complete_history": False,
            "fees": [],
            "basis": "Account activity intake has not run.",
        }
    instance = Accounting.__new__(Accounting)
    instance.store = store
    return instance.summary()
