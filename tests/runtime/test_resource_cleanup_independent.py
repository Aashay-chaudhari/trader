"""Independent cleanup review: bounded retry and preservation of primary faults."""

import signal
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from agent_trader.runtime import agent, supervisor
from agent_trader.runtime.ownership import RuntimeBusy, runtime_ownership
from tests.runtime import test_resource_lifetime as resource_fixtures

rpc_parts = resource_fixtures.rpc_parts


def test_later_close_can_reap_after_both_initial_process_waits_timeout(rpc_parts):
    config, process, selector, signals = rpc_parts
    rpc = agent.CodexRPC(config)
    process.timeouts = 2
    with pytest.raises(subprocess.TimeoutExpired):
        rpc.close()
    assert process.returncode is None
    assert process.wait_calls == [5, 5]
    assert signals == [signal.SIGTERM, signal.SIGKILL]
    assert process.stdin.closed and process.stdout.closed
    with pytest.raises(agent.AgentUnavailable, match="closed"):
        rpc.send({"method": "no-further-io"})
    rpc.close()
    assert process.returncode == 0
    assert process.wait_calls == [5, 5, 5]
    assert signals == [signal.SIGTERM, signal.SIGKILL]
    rpc.close()
    assert process.wait_calls == [5, 5, 5]
    assert process.stdin.close_calls == process.stdout.close_calls == selector.close_calls == 1


def test_selector_close_failure_does_not_skip_pipes_and_can_be_retried(rpc_parts, monkeypatch):
    config, process, selector, signals = rpc_parts
    rpc = agent.CodexRPC(config)
    attempts = []
    original = selector.close

    def close():
        attempts.append(1)
        if len(attempts) == 1:
            raise OSError("injected selector close failure")
        original()

    monkeypatch.setattr(selector, "close", close)
    with pytest.raises(OSError, match="selector close"):
        rpc.close()
    assert process.returncode == 0 and process.stdin.closed and process.stdout.closed
    rpc.close()
    assert len(attempts) == 2 and selector.close_calls == 1
    assert process.wait_calls == [5] and signals == [signal.SIGTERM]
    assert process.stdin.close_calls == process.stdout.close_calls == 1


def test_constructor_failure_remains_primary_when_cleanup_also_fails(config, monkeypatch):
    store = resource_fixtures.MemoryStore()
    calls = []

    class BrokenClient:
        def close(self):
            calls.append("broker_close")
            raise OSError("injected cleanup failure")

    def broken_engine(*args):
        raise ValueError("original engine construction failure")

    monkeypatch.setattr(supervisor, "Store", lambda path: store)
    monkeypatch.setattr(supervisor, "Broker", lambda config: BrokenClient())
    monkeypatch.setattr(supervisor, "Engine", broken_engine)
    with pytest.raises(ValueError, match="original engine construction") as caught:
        supervisor.Supervisor(config)
    assert calls == ["broker_close"] and store.close_calls == 1
    assert any("OSError" in note for note in caught.value.__notes__)


@pytest.mark.parametrize("body_fails,cleanup_fails", [(False, False), (True, False), (False, True)])
def test_runtime_lease_survives_both_unfinished_workers_and_cleanup(config, body_fails, cleanup_fails):
    instance = supervisor.Supervisor.__new__(supervisor.Supervisor)
    instance.config = config
    instance.store = resource_fixtures.MemoryStore()
    instance.pool = ThreadPoolExecutor(max_workers=1)
    instance.publisher_pool = ThreadPoolExecutor(max_workers=1)
    instance._closed = False
    instance.future = None
    started = [threading.Event(), threading.Event()]
    releases = [threading.Event(), threading.Event()]
    finished = [threading.Event(), threading.Event()]
    errors, closed = [], []

    def work(index):
        started[index].set()
        if not releases[index].wait(5):
            raise AssertionError("test did not release fake work")
        finished[index].set()

    def close_client():
        assert all(event.is_set() for event in finished)
        with pytest.raises(RuntimeBusy):
            with runtime_ownership(config.state_dir):
                pass
        closed.append(True)
        if cleanup_fails:
            raise OSError("injected client cleanup failure")

    instance.broker = SimpleNamespace(close=close_client)

    def body():
        instance.pool.submit(work, 0)
        instance.publisher_pool.submit(work, 1)
        if body_fails:
            raise ValueError("injected main-loop failure")

    instance._run_owned = body

    def run():
        try:
            instance.run()
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert all(event.wait(2) for event in started)
        with pytest.raises(RuntimeBusy):
            with runtime_ownership(config.state_dir):
                pass
        assert not closed and instance.store.close_calls == 0
        releases[0].set()
        assert finished[0].wait(2)
        with pytest.raises(RuntimeBusy):
            with runtime_ownership(config.state_dir):
                pass
        assert not closed and instance.store.close_calls == 0
        releases[1].set()
        thread.join(3)
        assert not thread.is_alive()
        assert closed == [True] and instance.store.close_calls == 1
        assert [type(error) for error in errors] == ([OSError] if cleanup_fails else [ValueError] if body_fails else [])
        with runtime_ownership(config.state_dir):
            pass
        instance.close()
        assert closed == [True] and instance.store.close_calls == 1
    finally:
        for event in releases:
            event.set()
        thread.join(3)
        instance.pool.shutdown(wait=True)
        instance.publisher_pool.shutdown(wait=True)
