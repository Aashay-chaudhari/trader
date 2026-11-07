import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from agent_trader.runtime import agent
from agent_trader.runtime.budget import budget_check
from agent_trader.runtime.config import ET
from agent_trader.runtime.models import Decision
from agent_trader.runtime.store import Store, dumps
from tests.runtime.test_agent_diagnostics import FakeRPC


@pytest.mark.parametrize("roles,seed_role,boundary", [
    (("research", "probe_research"), "research", 16),
    (("decision", "position_review"), "decision", 20),
    (("retrospective", "research_audit"), "retrospective", 24),
    (("deep_research", "deep_research_review"), "deep_research", 96),
])
def test_concurrent_connections_reserve_only_one_remaining_call(
    config, monkeypatch, roles, seed_role, boundary
):
    path = config.state_dir / "trader.sqlite3"
    day = datetime.now(ET).date().isoformat()
    prior_task_day = (datetime.now(ET).date() - timedelta(days=1)).isoformat()
    seed = Store(path)
    try:
        for _ in range(boundary - 1):
            seed.db.execute(
                "INSERT INTO usage(at,day,role,model,input_tokens,cached_tokens,output_tokens,payload) "
                "VALUES(?,?,?,?,0,0,0,?)",
                (datetime.now(timezone.utc).isoformat(), day, seed_role, "test", dumps({"state": "completed"})),
            )
    finally:
        seed.close()
    barrier = threading.Barrier(2)
    network_calls = []
    checked_connections = []

    class ConcurrentRPC(FakeRPC):
        def rate_limits(self):
            result = super().rate_limits()
            if self.quota_reads == 1:
                barrier.wait(timeout=10)
            return result

        def run(self, *args, **kwargs):
            # Inference must begin after committing the reservation. Another
            # connection can write immediately while the network work runs.
            audit = Store(path)
            try:
                audit.set("concurrent-network-write", True)
                network_calls.append(audit.rows("SELECT count(*) n FROM usage")[0]["n"])
            finally:
                audit.close()
            return super().run(*args, **kwargs)

    def checked_budget(store, quota, role, now):
        checked_connections.append(id(store.db))
        assert store.db.in_transaction, "Admission must hold the short SQLite write lock"
        result = budget_check(store, quota, role, now)
        # Widen the historical check/insert race. The second connection must wait
        # for this transaction and then observe the first counted reservation.
        time.sleep(0.05)
        return result

    monkeypatch.setattr(agent, "CodexRPC", ConcurrentRPC)
    monkeypatch.setattr(agent, "budget_check", checked_budget)

    def call(role):
        try:
            agent.run_task(
                config, role, "PRIVATE research input", Decision,
                config.research_model, "low", prior_task_day,
                task_key="PRIVATE-job:" + role,
            )
            return "admitted"
        except agent.AgentUnavailable:
            return "denied"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(call, roles))
    assert sorted(results) == ["admitted", "denied"]
    assert len(set(checked_connections)) == 2
    assert network_calls == [boundary]
    store = Store(path)
    try:
        assert store.rows("SELECT count(*) n FROM usage")[0]["n"] == boundary
        latest = store.rows("SELECT day,payload FROM usage ORDER BY id DESC LIMIT 1")[0]
        payload = json.loads(latest["payload"])
        assert latest["day"] == day  # A delayed prior-day task cannot bypass today's cap.
        assert payload["task_day"] == prior_task_day
        assert payload["state"] == "completed"
        skips = store.rows("SELECT payload FROM events WHERE kind='budget_skip'")
        assert len(skips) == 1
        skip = json.loads(skips[0]["payload"])
        assert set(skip) == {"role", "reason"}
        assert "ceiling reached" in skip["reason"]
        assert "PRIVATE" not in json.dumps(store.rows("SELECT payload FROM events"))
    finally:
        store.close()
