"""Explicit, independently reviewed prospective policy for filter promotion."""

from __future__ import annotations

import json
from datetime import datetime

from .observation_audit import content_hash
from .store import dumps

POLICY = {
    "version": "paired-entry-date-absolute-v2",
    "absolute_return": "Both equal-entry-date and equal-opportunity challenger means must be strictly positive.",
    "paired_return": "Existing entry-date paired lower bound, sign consistency, family/look penalty and doubling looks remain unchanged.",
    "eligibility": "Existing parent, observation eligibility, costs, sample/session minima, risk and rollback gates remain unchanged.",
    "migration": "Only shadow experiments with zero observations and no prior review look; no historical reinterpretation.",
}
POLICY_SHA256 = content_hash(POLICY)


def _stamp(value):
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("Promotion policy timestamps require timezone")
    return stamp


def policy_key(experiment_id):
    return "experiment-promotion-policy:" + experiment_id


def _valid_review(review, effective):
    return (
        isinstance(review, dict)
        and review.get("approved") is True
        and review.get("independent") is True
        and review.get("policy_sha256") == POLICY_SHA256
        and all(
            isinstance(review.get(key), str) and review[key].strip()
            for key in ("author", "reviewer", "validation")
        )
        and review["author"] != review["reviewer"]
        and _stamp(review["reviewed_at"]) <= effective
    )


def approval_key():
    return "promotion-policy-approval:" + POLICY_SHA256


def approve_promotion_policy(store, *, effective_at, review):
    """Record one independent policy approval for future experiment registrations."""
    try:
        valid = _valid_review(review, _stamp(effective_at))
    except (KeyError, TypeError, ValueError, AttributeError):
        valid = False
    if not valid:
        raise ValueError("Independent approval of this exact policy is required")
    payload = {
        "policy": POLICY,
        "policy_sha256": POLICY_SHA256,
        "effective_at": effective_at,
        "review": review,
        "scope": "Future experiment registrations only; existing studies need explicit migration.",
    }
    receipt = {**payload, "approval_sha256": content_hash(payload)}
    with store.transaction():
        old = store.get(approval_key())
        if old is not None:
            if old != receipt:
                raise ValueError("Global promotion policy approval is immutable")
            return old
        store.db.execute("INSERT INTO kv VALUES(?,?)", (approval_key(), dumps(receipt)))
        store.event("promotion_policy_approved", receipt)
    return receipt


def _global_approval(store):
    try:
        receipt = store.get(approval_key())
        if (
            receipt
            and receipt["policy_sha256"] == POLICY_SHA256
            and content_hash(receipt["policy"]) == POLICY_SHA256
            and receipt["approval_sha256"]
            == content_hash({k: v for k, v in receipt.items() if k != "approval_sha256"})
            and _valid_review(receipt["review"], _stamp(receipt["effective_at"]))
        ):
            return receipt
    except (KeyError, TypeError, ValueError, AttributeError):
        pass
    return None


def pin_approved_policy(store, experiment_id, spec, registered_at):
    """Called inside new registration's transaction; never migrates old studies."""
    approval = _global_approval(store)
    if not approval:
        return None
    cutoff = max(_stamp(registered_at), _stamp(approval["effective_at"])).isoformat()
    payload = {
        "experiment_id": experiment_id,
        "experiment_sha256": content_hash(spec),
        "policy": POLICY,
        "policy_sha256": POLICY_SHA256,
        "effective_at": cutoff,
        "observations_at_registration": 0,
        "review": approval["review"],
        "global_approval_sha256": approval["approval_sha256"],
    }
    receipt = {**payload, "receipt_sha256": content_hash(payload)}
    store.db.execute("INSERT INTO kv VALUES(?,?)", (policy_key(experiment_id), dumps(receipt)))
    store.event("promotion_policy_registered", receipt, spec["branch"])
    return receipt


def install_promotion_policy(store, experiment_ids, *, effective_at, review):
    """Maintenance migration; root records actual independent review after tests.

    Idempotent exact receipt replay is allowed even after collection starts.
    Changing its cutoff, reviewer, policy or frozen contract is never allowed.
    """
    if not experiment_ids or len(set(experiment_ids)) != len(experiment_ids):
        raise ValueError("Select distinct existing experiments")
    effective = _stamp(effective_at)
    try:
        valid = _valid_review(review, effective)
    except (KeyError, TypeError, ValueError, AttributeError):
        valid = False
    if not valid:
        raise ValueError("Independent approval and validation of this exact policy are required")
    installed = []
    with store.transaction():
        for experiment_id in experiment_ids:
            found = store.rows("SELECT * FROM experiments WHERE id=?", (experiment_id,))
            if not found:
                raise ValueError("Unknown experiment")
            row = found[0]
            spec = json.loads(row["payload"])
            payload = {
                "experiment_id": experiment_id,
                "experiment_sha256": content_hash(spec),
                "policy": POLICY,
                "policy_sha256": POLICY_SHA256,
                "effective_at": effective_at,
                "observations_at_registration": 0,
                "review": review,
            }
            receipt = {**payload, "receipt_sha256": content_hash(payload)}
            old = store.get(policy_key(experiment_id))
            if old is not None:
                if old != receipt:
                    raise ValueError("Promotion policy receipt is immutable")
                installed.append(old)
                continue
            parent = store.get("incumbent_filter:" + row["branch"])
            if (
                row["state"] != "shadow"
                or spec["parent_version"] != (parent["id"] if parent else "pilot-v1")
                or store.rows("SELECT id FROM shadow WHERE experiment=? LIMIT 1", (experiment_id,))
                or store.get("experiment-look:" + experiment_id) is not None
                or _stamp(row["at"]) > effective
            ):
                raise ValueError(
                    "Policy requires an unreviewed current-parent shadow experiment with zero observations"
                )
            store.db.execute(
                "INSERT INTO kv VALUES(?,?)", (policy_key(experiment_id), dumps(receipt))
            )
            store.event("promotion_policy_registered", receipt, row["branch"])
            installed.append(receipt)
    return installed


def policy_status(store, experiment_id, spec, samples=()):
    try:
        receipt = store.get(policy_key(experiment_id))
        if receipt is None:
            return {"ready": False, "reason": "independent_prospective_policy_review_required"}
        payload = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
        cutoff = _stamp(receipt["effective_at"])
        valid = (
            receipt.get("experiment_id") == experiment_id
            and receipt.get("observations_at_registration") == 0
            and receipt.get("policy_sha256") == POLICY_SHA256
            and content_hash(receipt.get("policy")) == POLICY_SHA256
            and receipt.get("experiment_sha256") == content_hash(spec)
            and receipt.get("receipt_sha256") == content_hash(payload)
            and _valid_review(receipt.get("review"), cutoff)
        )
        if not valid:
            return {"ready": False, "reason": "promotion_policy_receipt_mismatch"}
        if receipt.get("global_approval_sha256"):
            approval = _global_approval(store)
            if not approval or approval["approval_sha256"] != receipt["global_approval_sha256"]:
                return {"ready": False, "reason": "global_promotion_policy_approval_mismatch"}
        for sample in samples:
            if (
                sample.get("promotion_policy_receipt_sha256") != receipt["receipt_sha256"]
                or not sample.get("entered_at")
                or _stamp(sample["entered_at"]) < cutoff
            ):
                return {
                    "ready": False,
                    "reason": "observations_outside_prospective_promotion_policy",
                }
    except (KeyError, TypeError, ValueError, AttributeError):
        return {"ready": False, "reason": "promotion_policy_receipt_mismatch"}
    return {
        "ready": True,
        "version": POLICY["version"],
        "receipt_sha256": receipt["receipt_sha256"],
        "effective_at": receipt["effective_at"],
    }
