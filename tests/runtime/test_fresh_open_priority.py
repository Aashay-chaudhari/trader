"""Protect the one-off fresh-open deadline without changing trading gates."""

from concurrent.futures import Future
from datetime import datetime

import pytest

from agent_trader.runtime.config import ET
from agent_trader.runtime.supervisor import Supervisor
from tests.runtime import test_scheduler_priorities as scheduler_tests
from tests.runtime.test_operational_session import clock as session_clock

scheduler = scheduler_tests.scheduler


def pending_review(scheduler, broker, monkeypatch, now, *, plans=()):
    day = scheduler_tests.prepare(scheduler, broker, monkeypatch, now)
    scheduler.store.set("exploration_draft", {"revision": "overdue-review"})
    monkeypatch.setattr(scheduler, "pending_research_validation", Supervisor.pending_research_validation.__get__(scheduler))
    monkeypatch.setattr(scheduler, "smoke", lambda *args: None)
    monkeypatch.setattr(scheduler.engine, "ensure_protection", lambda **kwargs: None)
    monkeypatch.setattr(scheduler.engine, "plans", lambda *args: list(plans))
    launches = []

    def launch(key, role, context, day):
        launches.append((key, role))
        scheduler.future = Future()
        return True

    monkeypatch.setattr(scheduler, "launch", launch)
    return day, launches


def test_last_fresh_open_minute_precedes_overdue_validation_without_discarding_review(scheduler, broker, monkeypatch):
    now = datetime(2026, 11, 6, 10, 14, tzinfo=ET)
    day, launches = pending_review(scheduler, broker, monkeypatch, now)
    scheduler.tick(now)
    assert launches == [("fresh-open-research:" + day, "research")]
    assert scheduler.store.get("exploration_validated_draft") is None
    # Completing the fresh pass does not silently mark the research review done.
    scheduler.future = None
    later = now.replace(minute=16)
    monkeypatch.setattr(broker, "clock", lambda: session_clock(later, next_day="2026-11-09"))
    scheduler.tick(later)
    assert launches[-1] == ("research-validation:overdue-review", "research_validation")
    assert broker.submissions == 0


@pytest.mark.parametrize("hour,minute,plans", [
    (10, 14, [{"id": "valid-existing-plan"}]),
    (9, 44, []),
    (10, 15, []),
])
def test_existing_plans_or_outside_fresh_window_preserve_review_priority(scheduler, broker, monkeypatch, hour, minute, plans):
    now = datetime(2026, 11, 6, hour, minute, tzinfo=ET)
    _, launches = pending_review(scheduler, broker, monkeypatch, now, plans=plans)
    scheduler.tick(now)
    assert launches == [("research-validation:overdue-review", "research_validation")]
    assert broker.submissions == 0


@pytest.mark.parametrize("role", ["position_review", "options_coverage"])
def test_position_and_bounded_data_work_keep_priority_over_fresh_research(scheduler, broker, monkeypatch, role):
    now = datetime(2026, 11, 6, 10, 14, tzinfo=ET)
    day, launches = pending_review(scheduler, broker, monkeypatch, now)
    method = "launch_position_review" if role == "position_review" else "launch_options_coverage"
    monkeypatch.setattr(scheduler, method, lambda *args: scheduler.launch("priority:" + day, role, {}, day))
    scheduler.tick(now)
    assert launches == [("priority:" + day, role)]
    assert broker.submissions == 0
