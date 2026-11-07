import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from agent_trader.runtime import agent, cli, supervisor
from agent_trader.runtime.ownership import RuntimeBusy, runtime_ownership
from agent_trader.runtime.store import Store
from tests.runtime.test_agent_diagnostics import FakeRPC, quota


@pytest.mark.parametrize("command", [
    "run", "tick", "doctor", "reset", "smoke", "explore", "research-test", "agent-check",
])
def test_cli_cannot_open_operational_state_while_an_owner_is_active(config, monkeypatch, command):
    monkeypatch.setattr(cli.Config, "load", lambda: config)
    monkeypatch.setattr(cli, "dispatch", lambda *a, **k: pytest.fail("Command ran without ownership"))
    arguments = ["agent-trader", command]
    if command == "reset":
        arguments += ["--confirm", "RESET"]
    monkeypatch.setattr("sys.argv", arguments)
    with runtime_ownership(config.state_dir):
        with pytest.raises(SystemExit, match="supervisor or another operational command"):
            cli.main()
    assert not (config.state_dir / "trader.sqlite3").exists()


def test_reset_holds_ownership_through_broker_check_and_archive(config, monkeypatch):
    def checked_reset(*args):
        with pytest.raises(RuntimeBusy):
            with runtime_ownership(config.state_dir):
                pytest.fail("Reset released its lock before changing state")
        return {"reset": "checked"}

    monkeypatch.setattr(cli, "_reset_application", checked_reset)
    assert cli.reset_application(config, "RESET") == {"reset": "checked"}
    with runtime_ownership(config.state_dir):
        pass  # The complete operation has now released its lock.


def test_explicit_nested_lease_does_not_authorize_another_thread_or_later_use(config):
    with runtime_ownership(config.state_dir) as lease:
        with runtime_ownership(config.state_dir, lease):
            pass

        def other_thread():
            with pytest.raises(RuntimeBusy, match="lease"):
                with runtime_ownership(config.state_dir, lease):
                    pass

        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(other_thread).result()
    with pytest.raises(RuntimeBusy, match="lease"):
        with runtime_ownership(config.state_dir, lease):
            pass


def test_single_tick_finishes_applies_result_and_closes_workers_under_lock(config, monkeypatch):
    calls = []

    class FakePool:
        def shutdown(self, **kwargs):
            calls.append("shutdown")

    class FakeSupervisor:
        def __init__(self, config):
            self.store = SimpleNamespace(close=lambda: calls.append("closed"))
            self.pool = self.publisher_pool = FakePool()

        def tick(self):
            assert self.store.job_owner["kind"] == "supervisor"
            calls.append("tick")

        def finish_task(self):
            with pytest.raises(RuntimeBusy):
                with runtime_ownership(config.state_dir):
                    pass
            calls.append("applied")

    monkeypatch.setattr(supervisor, "Supervisor", FakeSupervisor)
    with runtime_ownership(config.state_dir) as lease:
        cli.dispatch(config, SimpleNamespace(command="tick"), ownership=lease)
    assert calls == ["tick", "shutdown", "applied", "shutdown", "shutdown", "closed"]


def test_supervisor_keeps_lock_until_live_worker_has_stopped(config, broker, monkeypatch):
    monkeypatch.setattr(supervisor, "Broker", lambda _: broker)
    instance = supervisor.Supervisor(config)
    entered = threading.Event()
    release = threading.Event()

    def worker():
        entered.set()
        assert release.wait(timeout=5)

    def loop():
        instance.pool.submit(worker)
        assert entered.wait(timeout=5)

    def contender():
        assert entered.wait(timeout=5)
        try:
            with pytest.raises(RuntimeBusy):
                with runtime_ownership(config.state_dir):
                    pass
        finally:
            release.set()

    monkeypatch.setattr(instance, "_run_owned", loop)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            check = pool.submit(contender)
            instance.run()
            check.result()
        with runtime_ownership(config.state_dir):
            pass
    finally:
        release.set()
        instance.pool.shutdown(wait=True)
        instance.publisher_pool.shutdown(wait=True)
        instance.store.close()


def test_connectivity_check_accounts_both_turns_and_switches_on_isolated_thread(config, monkeypatch):
    seen = []

    class CheckedRPC(FakeRPC):
        def run(self, thread_id, prompt, model, *args, **kwargs):
            seen.append((thread_id, model, kwargs))
            return super().run(thread_id, prompt, model, *args, **kwargs)

    monkeypatch.setattr(agent, "CodexRPC", CheckedRPC)
    assert cli.check_agent(config)["inference"] == ["wait", "wait"]
    assert [r[0] for r in seen] == [None, "private-thread"]
    assert [r[1] for r in seen] == [config.light_model, config.decision_model]
    assert all(r[2]["max_searches"] == 0 for r in seen)
    store = Store(config.state_dir / "trader.sqlite3")
    try:
        usage = store.rows("SELECT role,input_tokens,payload FROM usage")
        assert len(usage) == 2
        assert all(r["role"] == "connectivity_check" and r["input_tokens"] == 120 for r in usage)
        assert all(json.loads(r["payload"])["state"] == "completed" for r in usage)
    finally:
        store.close()


@pytest.mark.parametrize("stop_after", [0, 1])
def test_connectivity_check_cannot_bypass_account_reserve(config, monkeypatch, stop_after):
    class LimitedRPC(FakeRPC):
        calls = 0

        def rate_limits(self):
            return quota(80 if self.calls >= stop_after else 10)

    monkeypatch.setattr(agent, "CodexRPC", LimitedRPC)
    with pytest.raises(agent.AgentUnavailable, match="reserve"):
        cli.check_agent(config)
    assert LimitedRPC.calls == stop_after


@pytest.mark.parametrize("role", ["decision", "position_review", "pulse", "maintenance", "retrospective"])
def test_shutdown_retains_completed_reply_without_applying_operational_authority(
    config, broker, monkeypatch, role
):
    from concurrent.futures import Future
    from agent_trader.runtime.store import dumps, utc_now

    monkeypatch.setattr(supervisor, "Broker", lambda _: broker)
    instance = supervisor.Supervisor(config)
    key, day = "shutdown-task", "2026-11-07"
    result = {"private_reply": "retained evidence", "action": "approve"}
    try:
        assert instance.store.job_start(key)
        instance.store.db.execute(
            "INSERT INTO usage(at,day,role,model,input_tokens,cached_tokens,output_tokens,payload) "
            "VALUES(?,?,?,?,120,30,40,?)",
            (utc_now(), day, role, "test", dumps({
                "task_key": key, "state": "completed", "terminal_outcome": "validated",
                "application_outcome": "pending",
            })),
        )
        instance.task = (key, role, {"private_context": "original request"}, day)
        instance.future = Future()
        instance.future.set_result(result)
        monkeypatch.setattr(instance, "finish_task", lambda: pytest.fail("Unsafe shutdown application"))
        instance.finish_shutdown_task()
        assert broker.submissions == 0
        assert instance.future is None and instance.store.get("active_task") is None
        assert instance.store.rows("SELECT state FROM jobs")[0]["state"] == "failed"
        receipt = instance.store.rows("SELECT payload FROM memory WHERE layer='deferred_agent_result'")
        assert json.loads(receipt[0]["payload"])["result"] == result
        usage = instance.store.rows("SELECT input_tokens,output_tokens,payload FROM usage")[0]
        assert usage["input_tokens"] == 120 and usage["output_tokens"] == 40
        assert json.loads(usage["payload"])["application_outcome"] == "deferred"
        assert "private_reply" not in dumps(instance.store.rows("SELECT payload FROM events"))
    finally:
        instance.pool.shutdown(wait=True)
        instance.publisher_pool.shutdown(wait=True)
        instance.store.close()


def test_shutdown_applies_a_completed_report_under_ownership(config, broker, monkeypatch):
    from concurrent.futures import Future

    monkeypatch.setattr(supervisor, "Broker", lambda _: broker)
    instance = supervisor.Supervisor(config)
    day, key = "2026-11-07", "weekly:2026-11-07"
    report = {"summary": "Bounded retrospective evidence", "proposed_lessons": []}
    try:
        assert instance.store.job_start(key)
        instance.task = (key, "weekly", {}, day)
        instance.future = Future()
        instance.future.set_result(report)
        monkeypatch.setattr(instance, "_run_owned", lambda: None)
        instance.run()
        assert instance.store.get(key) == report
        assert instance.store.rows("SELECT state FROM jobs")[0]["state"] == "done"
        assert broker.submissions == 0
        assert instance.future is None
    finally:
        instance.pool.shutdown(wait=True)
        instance.publisher_pool.shutdown(wait=True)
        instance.store.close()


def test_shutdown_retention_failure_rolls_back_claim_and_retries_atomically(config, broker, monkeypatch):
    from concurrent.futures import Future
    from agent_trader.runtime.store import dumps, utc_now

    monkeypatch.setattr(supervisor, "Broker", lambda _: broker)
    instance = supervisor.Supervisor(config)
    key = "shutdown-atomic-retry"
    try:
        assert instance.store.job_start(key)
        instance.store.db.execute("INSERT INTO usage(at,day,role,payload) VALUES(?,?,?,?)", (
            utc_now(), "2026-11-07", "decision", dumps({"task_key": key, "state": "completed", "terminal_outcome": "validated", "application_outcome": "pending"}),
        ))
        instance.task = (key, "decision", {"private_context": "frozen"}, "2026-11-07")
        instance.future = Future()
        instance.future.set_result({"action": "approve", "private_reply": "retain only"})
        event = instance.store.event

        def fail_event(kind, *args, **kwargs):
            if kind == "agent_task_deferred":
                raise RuntimeError("injected deferred receipt failure")
            return event(kind, *args, **kwargs)

        monkeypatch.setattr(instance.store, "event", fail_event)
        with pytest.raises(RuntimeError, match="injected deferred receipt failure"):
            instance.finish_shutdown_task()
        assert not instance.store.rows("SELECT id FROM memory WHERE layer='deferred_agent_result'")
        assert instance.store.rows("SELECT state FROM jobs")[0]["state"] == "running"
        assert key in instance.store._job_claims and instance.future is not None
        assert json.loads(instance.store.rows("SELECT payload FROM usage")[0]["payload"])["application_outcome"] == "pending"
        monkeypatch.setattr(instance.store, "event", event)
        instance.finish_shutdown_task()
        assert instance.store.rows("SELECT state FROM jobs")[0]["state"] == "failed"
        assert len(instance.store.rows("SELECT id FROM memory WHERE layer='deferred_agent_result'")) == 1
        assert json.loads(instance.store.rows("SELECT payload FROM usage")[0]["payload"])["application_outcome"] == "deferred"
        assert key not in instance.store._job_claims and instance.future is None
        assert broker.submissions == 0
    finally:
        instance.pool.shutdown(wait=True)
        instance.publisher_pool.shutdown(wait=True)
        instance.store.close()
