"""Explicit synthetic broker session receipts for isolated runtime tests."""

from datetime import timedelta

from agent_trader.runtime.config import ET
from agent_trader.runtime.operational_session import EVIDENCE_VERSION


def approve(store, plan, now):
    """An explicitly accepted current decision, independent of session evidence."""
    store.db.execute("UPDATE plans SET state='approved' WHERE id=?", (plan["id"],))
    store.set("approval:" + plan["id"], {"at": now.isoformat(), "decision": {
        "plan_id": plan["id"], "action": "approve", "evidence_fresh": True,
        "reason": "Synthetic approval for the exact tested plan.", "contradictions": [],
    }})


def install(store, now, opened=None, closed=None, clock_at=None):
    now = now.astimezone(ET)
    opened = (opened or now.replace(hour=9, minute=30, second=0, microsecond=0)).astimezone(ET)
    closed = (closed or now.replace(hour=16, minute=0, second=0, microsecond=0)).astimezone(ET)
    clock_at = (clock_at or now).astimezone(ET)
    is_open = opened <= clock_at < closed
    next_open = opened if clock_at < opened else opened + timedelta(days=1)
    next_close = closed if clock_at < closed else closed + timedelta(days=1)
    proof = {
        "version": EVIDENCE_VERSION,
        "day": now.date().isoformat(),
        "calendar_raw": [
            {
                "date": now.date().isoformat(),
                "open": opened.strftime("%H:%M"),
                "close": closed.strftime("%H:%M"),
            }
        ],
        "clock_raw": {
            "is_open": is_open,
            "timestamp": clock_at.isoformat(),
            "next_open": next_open.isoformat(),
            "next_close": next_close.isoformat(),
        },
        "calendar_receipt": {"requested_at": now.isoformat(), "received_at": now.isoformat()},
        "clock_receipt": {"requested_at": now.isoformat(), "received_at": now.isoformat()},
        "source_errors": [],
    }
    store.set("operational_session", proof)
    store.set("market_open", is_open)
    return proof
