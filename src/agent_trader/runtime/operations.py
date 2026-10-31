"""Bounded operational evidence for review; no broker or mutation authority."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from .config import ET
from .store import utc_now


def operational_evidence(day, store):
    start = datetime.fromisoformat(day).replace(tzinfo=ET).astimezone(timezone.utc).isoformat()
    selected = store.rows(
        "SELECT symbol,branch,side,qty,status,filled,notional,plan_id,at,payload FROM orders "
        "WHERE at>=? OR status NOT IN ('filled','canceled','expired','rejected','replaced','done_for_day') "
        "ORDER BY at DESC LIMIT 16",
        (start,),
    )
    orders = []
    for r in selected:
        p = json.loads(r.pop("payload"))
        orders.append(
            {
                **r,
                "broker_times": {
                    k: p[k]
                    for k in ("updated_at", "filled_at", "canceled_at", "expired_at", "failed_at")
                    if p.get(k)
                },
            }
        )
    checks = []
    for r in store.rows(
        "SELECT key,value FROM kv WHERE key LIKE 'smoke:____-__-__' AND key>=? ORDER BY key DESC LIMIT 8",
        ("smoke:" + day,),
    ):
        d = r["key"].split(":", 1)[1]
        p = json.loads(r["value"])
        check = {
            k: p[k]
            for k in (
                "state",
                "at",
                "expires_at",
                "cancel_requested_at",
                "confirmed_at",
                "verified_at",
                "reason",
                "entry_order_status",
                "entry_filled_qty",
                "exit_filled_qty",
            )
            if k in p
        }
        entry = store.rows(
            "SELECT status,filled,payload FROM orders WHERE plan_id=? AND side='buy'",
            ("operational-smoke-" + d,),
        )
        if entry:
            payload = json.loads(entry[0]["payload"])
            check.update(
                {
                    "entry_status_from_broker_ledger": entry[0]["status"],
                    "entry_filled_qty": entry[0]["filled"],
                    "broker_canceled_at": payload.get("canceled_at"),
                }
            )
        checks.append({"day": d, **check})
    incidents = []
    for r in store.rows(
        "SELECT at,kind,payload FROM events WHERE at>=? AND kind IN ('incident','cohort_error','reconciliation_block') ORDER BY id DESC LIMIT 8",
        (start,),
    ):
        p = json.loads(r["payload"])
        incidents.append(
            {
                "at": r["at"],
                "kind": r["kind"],
                "facts": {
                    k: str(p[k])[:450]
                    for k in ("code", "reason", "summary", "errors", "error_type")
                    if k in p
                },
            }
        )
    findings = []
    for r in store.rows(
        "SELECT payload FROM memory WHERE layer='operational_finding' ORDER BY at DESC LIMIT 4"
    ):
        p = json.loads(r["payload"])
        findings.append(
            {k: p[k] for k in ("id", "state", "summary", "evidence", "verification") if k in p}
        )
    ready = store.get("readiness", {})
    result = {
        "snapshot_scope": "Current operational state and later diagnoses at as_of; do not treat them as knowledge available during an earlier reviewed period.",
        "as_of": utc_now(),
        "period_start_utc": start,
        "execution_verified": bool(ready.get("execution_verified")),
        "execution_verified_at": ready.get("execution_verified_at"),
        "reconciled": store.get("reconciled", False),
        "last_reconciled": store.get("last_reconciled"),
        "reconciliation_errors": store.get("reconciliation_errors", [])[:8],
        "broker_open_orders": store.get("broker_open_orders"),
        "execution_checks": checks,
        "order_status_counts": store.rows(
            "SELECT status,count(*) n FROM orders WHERE at>=? OR status NOT IN ('filled','canceled','expired','rejected','replaced','done_for_day') GROUP BY status",
            (start,),
        ),
        "selected_orders": orders,
        "order_selection": "Latest sixteen period or still-active orders; broker payload/IDs excluded, confirmation timestamps retained",
        "incident_counts": store.rows(
            "SELECT kind,count(*) n FROM events WHERE at>=? AND kind IN ('incident','cohort_error','reconciliation_block') GROUP BY kind",
            (start,),
        ),
        "recent_incident_details": incidents,
        "diagnosed_findings": findings,
        "maintenance_scope": "Automated code maintenance may edit only the pure adaptive strategy filter. Runtime/operational repairs are durable proposals for developer review, never automatic changes to the kernel.",
        "evidence_contract": "Submitted, cancellation-requested, broker-confirmed terminal status and reconciled fills are distinct. A tested code repair is not a successful live-session fill/exit. Ledger confirmations are as of last_reconciled; do not call available terminal states unknown. Strategy abstention alone does not prove profitable judgment.",
    }
    original_sizes = {
        k: len(result[k])
        for k in (
            "selected_orders",
            "recent_incident_details",
            "execution_checks",
            "diagnosed_findings",
        )
    }
    while len(json.dumps(result)) > 8000:
        field = next((k for k in original_sizes if len(result[k]) > 1), None)
        if field is None:
            break
        result[field].pop()  # complete records only, full state remains in SQLite
    result["omitted_details_for_budget"] = {
        k: n - len(result[k]) for k, n in original_sizes.items()
    }
    return result
