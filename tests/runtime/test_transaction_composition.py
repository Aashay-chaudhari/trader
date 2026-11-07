"""Nested transactions preserve publication and job-claim commit boundaries."""

from contextlib import closing
from datetime import datetime, timezone
import sqlite3

import pytest

from agent_trader.runtime import experiments
from agent_trader.runtime.adaptive_lab import AdaptiveLab
from agent_trader.runtime.experiments import Experiments
from agent_trader.runtime.exploration import record_report, record_validation
from tests.runtime.test_adaptive_lab import contract as adaptive_contract
from tests.runtime.test_exploration import contract, draft, validation


def test_successful_child_remains_invisible_and_rolls_back_with_parent(store):
    with closing(sqlite3.connect(store.path)) as observer:
        with pytest.raises(RuntimeError):
            with store.transaction():
                store.set("outer", 1)
                with store.transaction():
                    store.set("inner", 2)
                assert observer.execute("SELECT key FROM kv WHERE key IN ('outer','inner')").fetchall() == []
                raise RuntimeError("later batch item failed")
    assert store.get("outer") is None and store.get("inner") is None
    assert not store.db.in_transaction


def test_caught_child_failure_preserves_parent_work_and_pending_completion(store):
    assert store.job_start("parent-job") and store.job_start("child-job")
    child_owner = store._job_claims["child-job"]
    with store.transaction():
        store.set("before", True)
        assert store.job_end("parent-job", True, {})
        with pytest.raises(ValueError):
            with store.transaction():
                store.set("rejected-child", True)
                assert store.job_end("child-job", True, {})
                raise ValueError("domain rejection")
        assert store.get("before") is True
        assert store.get("rejected-child") is None
        assert store._job_claims["child-job"] == child_owner
        assert "parent-job" in store._job_claims
        store.set("after", True)
    assert "parent-job" not in store._job_claims
    assert store._job_claims["child-job"] == child_owner
    assert store.rows("SELECT state FROM jobs WHERE key='child-job'")[0]["state"] == "running"
    assert store.get("after") is True


def test_nested_completion_is_not_released_until_outer_commit(store):
    assert store.job_start("deferred")
    owner = store._job_claims["deferred"]
    with store.transaction():
        with store.transaction():
            assert store.job_end("deferred", True, {})
        assert store._job_claims["deferred"] == owner
    assert "deferred" not in store._job_claims


def test_outer_commit_failure_retains_nested_completion_for_retry(store):
    assert store.job_start("commit-failure")
    owner = store._job_claims["commit-failure"]
    store.db.execute("CREATE TABLE parent(id INTEGER PRIMARY KEY)")
    store.db.execute("CREATE TABLE child(id INTEGER REFERENCES parent(id) DEFERRABLE INITIALLY DEFERRED)")
    with pytest.raises(sqlite3.IntegrityError):
        with store.transaction():
            with store.transaction():
                assert store.job_end("commit-failure", True, {})
                store.db.execute("INSERT INTO child VALUES(7)")
            assert store._job_claims["commit-failure"] == owner
    assert store._job_claims["commit-failure"] == owner
    assert store.rows("SELECT state FROM jobs WHERE key='commit-failure'")[0]["state"] == "running"
    assert not store.rows("SELECT * FROM child")
    with store.transaction():
        assert store.job_end("commit-failure", True, {"retry": True})
    assert "commit-failure" not in store._job_claims


def test_repeated_provisional_completion_for_same_owner_releases_once(store):
    assert store.job_start("repeat")
    owner = store._job_claims["repeat"]
    with store.transaction():
        with store.transaction():
            assert store.job_end("repeat", True, {"step": 1})
        # Exercise repeated provisional state transitions under one claim token.
        store.db.execute("UPDATE jobs SET state='running' WHERE key='repeat'")
        with store.transaction():
            assert store.job_end("repeat", True, {"step": 2})
        assert store._job_claims["repeat"] == owner
    assert "repeat" not in store._job_claims
    assert store.rows("SELECT state FROM jobs WHERE key='repeat'")[0]["state"] == "done"


def test_nested_completion_never_releases_newer_claim(store):
    assert store.job_start("replacement")
    with store.transaction():
        with store.transaction():
            assert store.job_end("replacement", True, {})
        store._job_claims["replacement"] = "newer-owner-token"
    assert store._job_claims["replacement"] == "newer-owner-token"


def test_child_rollback_discards_only_its_new_admission_claim(store):
    with store.transaction():
        assert store.job_start("kept")
        with pytest.raises(ValueError):
            with store.transaction():
                assert store.job_start("discarded")
                raise ValueError("reject child")
        assert "discarded" not in store._job_claims
        assert "kept" in store._job_claims
    assert store.job_end("kept", True, {})
    assert not store.rows("SELECT * FROM jobs WHERE key='discarded'")


def test_outer_rollback_discards_successful_child_admission(store):
    with pytest.raises(RuntimeError):
        with store.transaction():
            assert store.job_start("not-durable")
            raise RuntimeError("batch failed")
    assert "not-durable" not in store._job_claims
    assert not store.rows("SELECT * FROM jobs WHERE key='not-durable'")
    assert store.job_start("not-durable")


def test_unmanaged_transaction_is_not_adopted_or_committed(store):
    store.db.execute("BEGIN IMMEDIATE")
    store.set("caller-owned", True)
    try:
        with pytest.raises(RuntimeError, match="unmanaged"):
            with store.transaction():
                pytest.fail("Unmanaged transaction must remain caller-owned")
        assert store.db.in_transaction
    finally:
        store.db.execute("ROLLBACK")
    assert store.get("caller-owned") is None


def test_unmanaged_job_completion_conservatively_retains_claim(store):
    assert store.job_start("external-completion")
    owner = store._job_claims["external-completion"]
    store.db.execute("BEGIN IMMEDIATE")
    assert store.job_end("external-completion", True, {})
    store.db.execute("COMMIT")
    assert store._job_claims["external-completion"] == owner


@pytest.mark.parametrize("failed_sql", ["ROLLBACK TO SAVEPOINT", "RELEASE SAVEPOINT"])
def test_uncertain_child_rollback_poison_prevents_partial_outer_commit(store, monkeypatch, failed_sql):
    assert store.job_start("poisoned-batch")
    owner = store._job_claims["poisoned-batch"]
    connection = store.db

    class FailedCleanup:
        failed = False

        def __getattr__(self, name):
            return getattr(connection, name)

        def execute(self, sql, *args):
            if sql.startswith(failed_sql) and not self.failed:
                self.failed = True
                raise sqlite3.OperationalError("Injected savepoint cleanup failure")
            return connection.execute(sql, *args)

    monkeypatch.setattr(store, "db", FailedCleanup())
    with pytest.raises(RuntimeError, match="full rollback") as caught:
        with store.transaction():
            store.set("sibling-before", True)
            try:
                with store.transaction():
                    store.set("rejected-item", True)
                    assert store.job_end("poisoned-batch", True, {})
                    raise ValueError("Expected domain rejection")
            except ValueError:
                pass
            store.set("sibling-after", True)
    assert isinstance(caught.value.__cause__, ValueError)
    assert "Transaction rollback failed" in caught.value.__cause__.__notes__[0]
    assert not store.db.in_transaction
    assert all(store.get(key) is None for key in ("sibling-before", "rejected-item", "sibling-after"))
    assert store._job_claims["poisoned-batch"] == owner
    assert store.rows("SELECT state FROM jobs WHERE key='poisoned-batch'")[0]["state"] == "running"
    with store.transaction():
        assert store.job_end("poisoned-batch", True, {"retry": True})
    assert "poisoned-batch" not in store._job_claims


def test_registration_rejection_with_failed_rollback_forces_entire_batch_rollback(store, monkeypatch):
    registry = Experiments(store)
    proposal = contract("require_risk_on")
    assert store.job_start("registration-batch")
    owner, connection = store._job_claims["registration-batch"], store.db

    class FailedRollback:
        def __getattr__(self, name):
            return getattr(connection, name)

        def execute(self, sql, *args):
            if sql.startswith("ROLLBACK TO SAVEPOINT"):
                raise sqlite3.OperationalError("Injected registration rollback failure")
            return connection.execute(sql, *args)

    def domain_reject(*args):
        raise ValueError("Rejected policy after experiment insert")

    monkeypatch.setattr(store, "db", FailedRollback())
    monkeypatch.setattr(experiments, "pin_approved_policy", domain_reject)
    with pytest.raises(RuntimeError, match="full rollback") as caught:
        with store.transaction():
            store.set("sibling-before-registration", True)
            assert store.job_end("registration-batch", True, {})
            with pytest.raises(ValueError, match="Rejected policy"):
                registry.register(proposal)
            # The item-level rejection is caught as it is by result application,
            # but uncertain rollback cannot turn the remaining batch into a commit.
            assert store.rows("SELECT id FROM experiments") == [{"id": proposal["id"]}]
            store.set("sibling-after-registration", True)
    assert isinstance(caught.value.__cause__, ValueError)
    assert not store.rows("SELECT * FROM experiments")
    assert store.get("sibling-before-registration") is None
    assert store.get("sibling-after-registration") is None
    assert store._job_claims["registration-batch"] == owner
    assert store.rows("SELECT state FROM jobs WHERE key='registration-batch'")[0]["state"] == "running"
    assert not store.db.in_transaction


def test_adaptive_constructor_does_not_commit_enclosing_transaction(store):
    with pytest.raises(RuntimeError):
        with store.transaction():
            store.set("must-roll-back", True)
            AdaptiveLab(store)
            assert store.db.in_transaction
            raise RuntimeError("later application failure")
    assert store.get("must-roll-back") is None
    assert not store.rows("SELECT name FROM sqlite_master WHERE name='adaptive_contracts'")


@pytest.mark.parametrize("kind", ["adaptive", "experiment"])
def test_registration_rolls_back_its_insert_when_event_fails_and_parent_continues(store, monkeypatch, kind):
    registry = AdaptiveLab(store) if kind == "adaptive" else Experiments(store)
    proposal = adaptive_contract() if kind == "adaptive" else contract("require_risk_on")
    table = "adaptive_contracts" if kind == "adaptive" else "experiments"
    event_kind = "adaptive_registered" if kind == "adaptive" else "experiment_registered"
    original = store.event

    def reject_event(event, *args, **kwargs):
        if event == event_kind:
            raise ValueError("domain failure after insert")
        return original(event, *args, **kwargs)

    monkeypatch.setattr(store, "event", reject_event)
    with store.transaction():
        store.set("outer-survives", True)
        with pytest.raises(ValueError):
            registry.register(proposal)
        assert not store.rows("SELECT * FROM " + table)
    assert store.get("outer-survives") is True


def test_report_event_failure_leaves_no_partial_draft(store, monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(store, "event", lambda *a, **k: (_ for _ in ()).throw(sqlite3.OperationalError("write failure")))
    with pytest.raises(sqlite3.OperationalError):
        record_report(store, draft(now), now.date().isoformat())
    assert store.get("exploration_draft") is None
    assert store.get("exploration_sessions") is None


def test_validation_late_storage_failure_rolls_back_reviews_and_registrations(store):
    now = datetime.now(timezone.utc)
    record_report(store, draft(now), now.date().isoformat())
    old = contract("avoid_risk_off", eid="existing-trial")
    Experiments(store).register(old)
    before_events = store.rows("SELECT * FROM events")
    store.db.execute("CREATE TRIGGER reject_validation BEFORE INSERT ON kv WHEN NEW.key='exploration_validated_draft' BEGIN SELECT RAISE(ABORT,'late storage failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match="late storage failure"):
        record_validation(store, validation())
    assert store.get("research_catalogue") is None
    assert store.get("exploration_report") is None
    assert not store.rows("SELECT * FROM memory WHERE layer='research_review'")
    assert store.rows("SELECT id FROM experiments") == [{"id": "existing-trial"}]
    assert store.rows("SELECT * FROM events") == before_events
    assert not store.rows("SELECT name FROM sqlite_master WHERE name='adaptive_contracts'")


def test_expected_registration_rejection_keeps_other_review_items(store, monkeypatch):
    now = datetime.now(timezone.utc)
    report = draft(now)
    bad = contract("higher_confidence_075", eid="expected-rejection")
    report["experiments"].append(bad)
    report["hypotheses"][0]["experiment_ids"].append(bad["id"])
    record_report(store, report, now.date().isoformat())
    original = experiments.pin_approved_policy

    def domain_reject(store, identity, *args):
        if identity == bad["id"]:
            raise ValueError("expected domain validation rejection")
        return original(store, identity, *args)

    monkeypatch.setattr(experiments, "pin_approved_policy", domain_reject)
    record_validation(store, validation())
    assert len(store.rows("SELECT * FROM experiments")) == 1
    assert not store.rows("SELECT * FROM experiments WHERE id=?", (bad["id"],))
    assert store.get("research_catalogue")[0]["state"] == "reviewed_for_testing"
    assert len(store.rows("SELECT * FROM events WHERE kind='experiment_rejected'")) == 1
    assert len(store.rows("SELECT * FROM memory WHERE layer='research_review'")) == 1
