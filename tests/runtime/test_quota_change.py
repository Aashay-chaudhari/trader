import copy
import json

import pytest

from agent_trader.runtime import agent
from agent_trader.runtime.store import Store
from tests.runtime.test_agent_diagnostics import FakeRPC, quota, run


def windows():
    first = quota(10)
    first["windows"].append({**first["windows"][0], "bucket": "private-provider-limit-id", "usedPercent": 70})
    return first


def test_quota_delta_matches_most_consumed_identity_across_reordered_buckets():
    before = windows()
    after = copy.deepcopy(before)
    after["windows"].reverse()
    after["windows"][0]["usedPercent"] = 71
    delta, reported, basis = agent.quota_change(before, after)
    assert delta == 1 and reported
    assert basis["before_used_percent"] == 70 and basis["after_used_percent"] == 71
    assert "private-provider-limit-id" not in json.dumps(basis)
    assert "external usage" in basis["scope"]
    assert agent.quota_change({"windows": before["windows"][::-1]}, after) == (delta, reported, basis)


@pytest.mark.parametrize("change", ["reset", "bucket", "kind", "duration", "missing", "duplicate"])
def test_changed_or_ambiguous_window_is_not_compared_to_another_percentage_scale(change):
    before = windows()
    after = copy.deepcopy(before)
    selected = after["windows"][1]
    if change == "reset":
        selected["resetsAt"] += 604800
        selected["usedPercent"] = 1
    elif change == "bucket":
        selected["bucket"] = "different"
    elif change == "kind":
        selected["kind"] = "secondary"
    elif change == "duration":
        selected["windowDurationMins"] += 10080
    elif change == "missing":
        after["windows"].pop()
    else:
        after["windows"].append(copy.deepcopy(selected))
    delta, reported, basis = agent.quota_change(before, after)
    assert delta == 0 and not reported
    assert basis["status"] == "reset_or_unavailable"
    assert basis["after_used_percent"] is None


def test_counter_decrease_is_not_falsely_reported_as_observed_zero_consumption():
    before = windows()
    after = copy.deepcopy(before)
    after["windows"][1]["usedPercent"] = 69
    delta, reported, basis = agent.quota_change(before, after)
    assert delta == 0 and not reported and basis["status"] == "counter_decreased"


def test_task_persists_safe_comparison_basis_without_summing_other_bucket_changes(config, monkeypatch):
    before = windows()
    after = copy.deepcopy(before)
    after["windows"].reverse()
    after["windows"][0]["usedPercent"] = 71
    after["windows"][1]["usedPercent"] = 12

    class ReorderedRPC(FakeRPC):
        def rate_limits(self):
            self.quota_reads += 1
            return before if self.quota_reads == 1 else after

    monkeypatch.setattr(agent, "CodexRPC", ReorderedRPC)
    run(config)
    store = Store(config.state_dir / "trader.sqlite3")
    try:
        row = store.rows("SELECT quota_delta,payload FROM usage")[0]
        payload = json.loads(row["payload"])
        assert row["quota_delta"] == 1  # Neither 61 from reordering nor 3 from summing buckets.
        assert payload["quota_delta_reported"] is True
        assert payload["quota_delta_basis"]["after_used_percent"] == 71
        events = json.dumps(store.rows("SELECT payload FROM events WHERE kind='agent_task'"))
        assert "private-provider-limit-id" not in events
    finally:
        store.close()
