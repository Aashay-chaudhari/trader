"""Additive observation receipts and descriptive weights; never changes a study."""

from __future__ import annotations

import hashlib
import json

from .store import dumps


def content_hash(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def record_quote(store, ledger, observation_id, phase, quote, now, calculation):
    """Call in the observation's transaction, only when that transition succeeds.

    Historical rows stay without receipts. A later quote cannot replace the first
    contemporaneous receipt, including when a retry follows a committed write.
    """
    if ledger not in ("cohort", "adaptive", "shadow") or phase not in ("entry", "exit"):
        raise ValueError("Unsupported observation receipt")
    payload = {
        "version": "observation-quote-receipt-v1",
        "ledger": ledger,
        "observation_id": observation_id,
        "phase": phase,
        "observed_at": now.isoformat(),
        "quote": {key: quote[key] for key in ("bp", "ap", "t")},
        "calculation": calculation,
    }
    receipt = {**payload, "sha256": content_hash(payload)}
    key = f"observation-quote:{ledger}:{observation_id}:{phase}"
    old = store.get(key)
    if old is not None:
        if old != receipt:
            raise ValueError("Observation quote receipt is immutable")
        return old
    store.db.execute("INSERT INTO kv VALUES(?,?)", (key, dumps(receipt)))
    return receipt


def date_composition(observations):
    """Describe equal-entry-date weights without calling them independent samples.

    Input is (entry_date, net_return, active_signal) for evaluable observations.
    The effective count here is deliberately not a statistical effective sample
    size: overlapping holding periods and market correlation are not estimated.
    """
    groups = {}
    for day, net, signal in observations:
        groups.setdefault(day, []).append((net, signal))
    count, dates = len(observations), len(groups)
    rows = [
        {
            "day": day,
            "closed_opportunities": len(values),
            "active_signals": sum(bool(signal) for _, signal in values),
            "entry_date_weight": 1 / dates,
            "per_opportunity_weight": 1 / (dates * len(values)),
            "mean_net": sum(net for net, _ in values) / len(values),
        }
        for day, values in sorted(groups.items())
    ]
    sizes = [len(values) for values in groups.values()]
    return {
        "closed_opportunities": count,
        "closed_entry_dates": dates,
        "by_entry_date": rows,
        "uneven_date_composition": len(set(sizes)) > 1,
        "smallest_date_opportunities": min(sizes) if sizes else 0,
        "largest_date_opportunities": max(sizes) if sizes else 0,
        "maximum_opportunity_weight": max(
            (r["per_opportunity_weight"] for r in rows), default=None
        ),
        "weight_concentration_vs_equal_opportunities": count / (dates * min(sizes))
        if sizes
        else None,
        "interpretation": "Equal entry-date weights; date counts and symbols are not independent replications.",
    }


def paired_estimators(samples):
    composition = date_composition(
        [
            (
                p["day"],
                p["challenger_return"],
                p.get("challenger_trades", p["challenger_return"] != 0),
            )
            for p in samples
        ]
    )
    dates = composition["by_entry_date"]
    opportunity = sum(p["challenger_return"] for p in samples) / len(samples) if samples else None
    entry_date = sum(p["mean_net"] for p in dates) / len(dates) if dates else None
    paired = {}
    for p in samples:
        paired.setdefault(p["day"], []).append(p["challenger_return"] - p["incumbent_return"])
    return {
        "opportunity_weighted_absolute_net": opportunity,
        "entry_date_weighted_absolute_net": entry_date,
        "entry_date_weighted_paired_net": sum(sum(v) / len(v) for v in paired.values())
        / len(paired)
        if paired
        else None,
        "absolute_positive_disagreement": opportunity is not None
        and (opportunity > 0) != (entry_date > 0),
        "composition": composition,
    }
