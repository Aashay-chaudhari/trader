from contextlib import nullcontext
from dataclasses import replace
from io import BytesIO
from types import SimpleNamespace
import signal
import sqlite3
import subprocess
import threading
import time

import pytest

from agent_trader.runtime import (
    accounting, adaptive_lab, agent, broker as broker_module, cli, exploration,
    options_coverage, probe, quality, supervisor,
)
from agent_trader.runtime.ownership import RuntimeBusy, runtime_ownership
from agent_trader.runtime import store as store_module
from agent_trader.runtime.store import Store


class Client:
    def __init__(self, **kwargs):
        self.close_calls = 0

    def close(self):
        self.close_calls += 1

    def request(self, *args, **kwargs):
        pytest.fail("Lifecycle tests must not issue network requests")


@pytest.fixture
def clients(monkeypatch):
    created = []

    def create(**kwargs):
        client = Client(**kwargs)
        created.append(client)
        return client

    monkeypatch.setattr(broker_module.httpx, "Client", create)
    return created


class MemoryStore:
    def __init__(self, path=None):
        self.values = {}
        self.close_calls = 0

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value

    def event(self, *args, **kwargs):
        pass

    def close(self):
        self.close_calls += 1


def fail(*args, **kwargs):
    raise RuntimeError("Injected operation failure")


@pytest.mark.parametrize("role", ["research", "exploration", "pulse", "accounting_refresh", "options_coverage"])
@pytest.mark.parametrize("failure", [None, "collection", "model"])
def test_worker_closes_http_and_store_on_all_paths(config, monkeypatch, clients, role, failure):
    store = MemoryStore()
    monkeypatch.setattr(supervisor, "Store", lambda _: store)
    collect = fail if failure == "collection" else lambda *a, **k: {}
    monkeypatch.setattr(supervisor, "market_packet", collect)
    monkeypatch.setattr(exploration, "prepare_screen", collect)
    monkeypatch.setattr(accounting, "Accounting", lambda _: SimpleNamespace(refresh=collect))
    monkeypatch.setattr(options_coverage, "run_capture", collect)
    monkeypatch.setattr(supervisor, "research_prompt", lambda *a: "prompt")
    monkeypatch.setattr(exploration, "exploration_prompt", lambda *a: "prompt")
    monkeypatch.setattr(quality, "pulse_prompt", lambda *a: "prompt")

    def model(*args, **kwargs):
        # The data client need not remain open throughout a model turn.
        assert [x.close_calls for x in clients] == [1]
        if failure == "model":
            fail()
        return {}

    monkeypatch.setattr(supervisor, "run_task", model)
    raises = failure == "collection" or (
        failure == "model" and role in ("research", "exploration", "pulse")
    )
    with pytest.raises(RuntimeError) if raises else nullcontext():
        supervisor.worker(config, role, {"slot": 1}, "2026-11-07")
    assert [x.close_calls for x in clients] == [1]
    assert store.close_calls == 1


@pytest.mark.parametrize("failure", [False, True])
def test_publisher_closes_its_store(config, monkeypatch, failure):
    store = MemoryStore()
    monkeypatch.setattr(supervisor, "Store", lambda _: store)
    monkeypatch.setattr(supervisor, "publish", fail if failure else lambda *a: {})
    with pytest.raises(RuntimeError) if failure else nullcontext():
        supervisor.publish_worker(config)
    assert store.close_calls == 1


@pytest.mark.parametrize("stage", ["broker", "engine", "publisher"])
def test_supervisor_partial_initialization_releases_acquired_resources(config, monkeypatch, clients, stage):
    store = MemoryStore()
    pools = []
    monkeypatch.setattr(supervisor, "Store", lambda _: store)
    if stage == "broker":
        monkeypatch.setattr(supervisor, "Broker", fail)
    monkeypatch.setattr(supervisor, "Engine", fail if stage == "engine" else lambda *a: None)
    for module, name in ((supervisor, "Experiments"), (supervisor, "ForwardLab"), (adaptive_lab, "AdaptiveLab")):
        monkeypatch.setattr(module, name, lambda *a: None)

    def pool(**kwargs):
        if kwargs["thread_name_prefix"] == "publisher":
            fail()
        item = SimpleNamespace(closed=False)
        item.shutdown = lambda **kwargs: setattr(item, "closed", True)
        pools.append(item)
        return item

    monkeypatch.setattr(supervisor.concurrent.futures, "ThreadPoolExecutor", pool)
    with pytest.raises(RuntimeError):
        supervisor.Supervisor(config)
    assert store.close_calls == 1
    assert [x.close_calls for x in clients] == ([] if stage == "broker" else [1])
    assert all(pool.closed for pool in pools)


@pytest.mark.parametrize("failure", [False, True])
def test_supervisor_run_closes_after_both_workers_under_ownership(config, broker, monkeypatch, failure):
    monkeypatch.setattr(supervisor, "Broker", lambda _: broker)
    instance = supervisor.Supervisor(config)
    completed = []
    original_close = broker.close

    def close():
        assert sorted(completed) == ["publisher", "research"]
        with pytest.raises(RuntimeBusy):
            with runtime_ownership(config.state_dir):
                pass
        original_close()

    monkeypatch.setattr(broker, "close", close)

    def run():
        instance.pool.submit(lambda: completed.append("research"))
        instance.publisher_pool.submit(lambda: completed.append("publisher"))
        if failure:
            fail()

    monkeypatch.setattr(instance, "_run_owned", run)
    with pytest.raises(RuntimeError) if failure else nullcontext():
        instance.run()
    instance.close()  # Repeated cleanup is harmless and does not close twice.
    assert broker.closed
    with pytest.raises(sqlite3.ProgrammingError):
        instance.store.get("status")
    with runtime_ownership(config.state_dir):
        pass


@pytest.mark.parametrize("failure", [False, True])
def test_probe_closes_data_client_and_stores(config, monkeypatch, clients, failure):
    stores = []

    def create(path):
        store = Store(path)
        stores.append(store)
        return store

    monkeypatch.setattr(probe, "Store", create)
    monkeypatch.setattr(probe, "notify", lambda *a, **k: True)
    monkeypatch.setattr(probe, "market_packet", fail if failure else lambda *a: {})
    monkeypatch.setattr(probe, "research_prompt", lambda *a: "prompt")
    monkeypatch.setattr(probe, "run_task", lambda *a, **k: {"plans": [], "sources": []})
    with pytest.raises(RuntimeError) if failure else nullcontext():
        probe.run_probe(config, "lifetime-proof", "research")
    assert [x.close_calls for x in clients] == [1]
    assert len(stores) == 2
    for store in stores:
        with pytest.raises(sqlite3.ProgrammingError):
            store.get("anything")


def test_probe_setup_failure_closes_live_store(config, monkeypatch):
    live = Store(config.state_dir / "trader.sqlite3")
    monkeypatch.setattr(probe, "Store", lambda _: live)
    monkeypatch.setattr(probe, "notify", fail)
    with pytest.raises(RuntimeError):
        probe.run_probe(config, "setup-failure", "research")
    with pytest.raises(sqlite3.ProgrammingError):
        live.get("anything")


def test_probe_scratch_constructor_failure_closes_live_store(config, monkeypatch):
    live = Store(config.state_dir / "trader.sqlite3")
    calls = []

    def create(path):
        calls.append(path)
        if len(calls) > 1:
            fail()
        return live

    monkeypatch.setattr(probe, "Store", create)
    monkeypatch.setattr(probe, "notify", lambda *a, **k: True)
    with pytest.raises(RuntimeError):
        probe.run_probe(config, "scratch-failure", "research")
    with pytest.raises(sqlite3.ProgrammingError):
        live.get("anything")


def test_supervisor_client_close_failure_still_closes_store(config, broker, monkeypatch):
    monkeypatch.setattr(supervisor, "Broker", lambda _: broker)
    instance = supervisor.Supervisor(config)
    monkeypatch.setattr(broker, "close", fail)
    with pytest.raises(RuntimeError):
        instance.close()
    with pytest.raises(sqlite3.ProgrammingError):
        instance.store.get("anything")


def test_supervisor_denied_ownership_closes_only_its_unstarted_resources(config, broker, monkeypatch):
    monkeypatch.setattr(supervisor, "Broker", lambda _: broker)
    instance = supervisor.Supervisor(config)
    monkeypatch.setattr(instance, "_run_owned", lambda: pytest.fail("Ownership required"))
    with runtime_ownership(config.state_dir):
        with pytest.raises(RuntimeBusy):
            instance.run()
        assert broker.closed
        with pytest.raises(sqlite3.ProgrammingError):
            instance.store.get("anything")
        with pytest.raises(RuntimeBusy):
            with runtime_ownership(config.state_dir):
                pass


@pytest.mark.parametrize("operation", ["reset", "smoke"])
def test_cli_early_guard_closes_client(config, monkeypatch, clients, operation):
    monkeypatch.setattr(broker_module.Broker, "positions", lambda _: [{}])
    with pytest.raises(ValueError):
        if operation == "reset":
            cli._reset_application(config, "RESET")
        else:
            cli._smoke_submission(config, MemoryStore())
    assert [x.close_calls for x in clients] == [1]


def test_smoke_cancellation_error_still_closes_client(config, broker, monkeypatch):
    monkeypatch.setattr(cli, "Broker", lambda _: broker)
    monkeypatch.setattr(cli, "Engine", lambda *a: SimpleNamespace(ingest_order=lambda *a, **k: None))
    monkeypatch.setattr(broker, "by_client", lambda _: {"id": "fake", "status": "new"})
    monkeypatch.setattr(broker, "cancel", fail)
    with pytest.raises(RuntimeError):
        cli._smoke_submission(config, MemoryStore())
    assert broker.closed


@pytest.mark.parametrize("stage", ["wal", "schema", "migration", "seed"])
@pytest.mark.parametrize("close_error", [False, True])
def test_store_initialization_failure_closes_connection_and_preserves_error(
    tmp_path, monkeypatch, stage, close_error
):
    original = sqlite3.OperationalError("Injected initialization failure")

    class Connection:
        in_transaction = False
        close_calls = 0

        def execute(self, sql, *args):
            if sql == "PRAGMA journal_mode=WAL":
                if stage == "wal":
                    raise original
                return SimpleNamespace(fetchone=lambda: ("wal",))
            if sql == "BEGIN IMMEDIATE":
                self.in_transaction = True
            elif sql in ("COMMIT", "ROLLBACK"):
                self.in_transaction = False
            elif sql == "PRAGMA table_info(jobs)":
                if stage == "migration":
                    raise original
                return [{"name": "owner"}]
            elif "INSERT OR IGNORE INTO branches" in sql and stage == "seed":
                raise original
            return []

        def executescript(self, sql):
            if stage == "schema":
                raise original

        def close(self):
            self.close_calls += 1
            if close_error:
                raise OSError("Injected cleanup failure")

    connection = Connection()
    monkeypatch.setattr(store_module.sqlite3, "connect", lambda *a, **k: connection)
    with pytest.raises(sqlite3.OperationalError) as caught:
        Store(tmp_path / "partial.sqlite3")
    assert caught.value is original
    assert connection.close_calls == 1
    if close_error:
        assert caught.value.__notes__ == ["Store initialization cleanup failed: OSError"]


class Pipe(BytesIO):
    def __init__(self):
        super().__init__()
        self.close_calls = 0

    def close(self):
        self.close_calls += 1
        super().close()


class Process:
    pid = 1234567  # Fake only: every killpg call is intercepted.

    def __init__(self):
        self.stdin, self.stdout = Pipe(), Pipe()
        self.wait_calls = []
        self.timeouts = 0
        self.returncode = None

    def wait(self, timeout):
        self.wait_calls.append(timeout)
        if self.timeouts:
            self.timeouts -= 1
            raise subprocess.TimeoutExpired("fake", timeout)
        self.returncode = 0
        return 0

    def poll(self):
        return self.returncode


class Selector:
    def __init__(self):
        self.close_calls = 0
        self.entered = threading.Event()
        self.release = threading.Event()

    def register(self, *args):
        pass

    def select(self, timeout):
        self.entered.set()
        self.release.wait(timeout)
        return []

    def close(self):
        self.close_calls += 1


@pytest.fixture
def rpc_parts(config, monkeypatch, tmp_path):
    binary = tmp_path / "fake-codex"
    binary.write_bytes(b"\x7fELF")
    process, selector, signals = Process(), Selector(), []
    monkeypatch.setattr(agent.subprocess, "Popen", lambda *a, **k: process)
    monkeypatch.setattr(agent.selectors, "DefaultSelector", lambda: selector)
    monkeypatch.setattr(agent.os, "killpg", lambda pid, value: signals.append(value))
    monkeypatch.setattr(agent.CodexRPC, "rpc", lambda *a, **k: {})
    return replace(config, codex_bin=str(binary)), process, selector, signals


@pytest.mark.parametrize("stage", ["popen", "selector", "register", "initialize", "initialized"])
def test_rpc_partial_initialization_cleans_resources(rpc_parts, monkeypatch, stage):
    config, process, selector, signals = rpc_parts
    if stage == "popen":
        monkeypatch.setattr(agent.subprocess, "Popen", fail)
    elif stage == "selector":
        monkeypatch.setattr(agent.selectors, "DefaultSelector", fail)
    elif stage == "register":
        monkeypatch.setattr(selector, "register", fail)
    elif stage == "initialize":
        monkeypatch.setattr(agent.CodexRPC, "rpc", fail)
    else:
        monkeypatch.setattr(agent.CodexRPC, "send", fail)
    with pytest.raises(RuntimeError):
        agent.CodexRPC(config)
    acquired = stage != "popen"
    assert signals == ([signal.SIGTERM] if acquired else [])
    assert process.wait_calls == ([5] if acquired else [])
    assert process.stdin.close_calls == process.stdout.close_calls == int(acquired)
    assert selector.close_calls == int(stage not in ("popen", "selector"))


@pytest.mark.parametrize("timeouts", [0, 1, 2])
def test_rpc_close_reaps_and_closes_pipes_once_with_bounded_waits(rpc_parts, timeouts):
    config, process, selector, signals = rpc_parts
    rpc = agent.CodexRPC(config)
    process.timeouts = timeouts
    with pytest.raises(subprocess.TimeoutExpired) if timeouts == 2 else nullcontext():
        rpc.close()
    rpc.close()
    rpc.close()
    assert signals == ([signal.SIGTERM, signal.SIGKILL] if timeouts else [signal.SIGTERM])
    assert process.wait_calls == [5] * (timeouts + 1)
    assert process.stdin.close_calls == process.stdout.close_calls == selector.close_calls == 1


def test_rpc_process_already_gone_still_gets_reaped(rpc_parts, monkeypatch):
    config, process, selector, _ = rpc_parts
    rpc = agent.CodexRPC(config)
    monkeypatch.setattr(agent.os, "killpg", lambda *a: (_ for _ in ()).throw(ProcessLookupError()))
    rpc.close()
    assert process.wait_calls == [5]
    assert process.stdin.closed and process.stdout.closed and selector.close_calls == 1


def test_rpc_close_interrupts_pending_reader_without_descriptor_race(rpc_parts):
    config, process, selector, _ = rpc_parts
    rpc = agent.CodexRPC(config)
    errors = []

    def read():
        try:
            rpc.receive(time.monotonic() + 30)
        except agent.AgentUnavailable as exc:
            errors.append(str(exc))

    thread = threading.Thread(target=read)
    thread.start()
    try:
        assert selector.entered.wait(2)
        started = time.monotonic()
        rpc.close()
        thread.join(2)
        assert not thread.is_alive()
        assert time.monotonic() - started < 3
        assert errors == ["Codex client closed"]
        assert process.stdin.closed and process.stdout.closed
    finally:
        selector.release.set()
        thread.join(2)
        rpc.close()
