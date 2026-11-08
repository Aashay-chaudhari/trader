import copy
import json
import subprocess
from dataclasses import replace
from datetime import datetime, timedelta

import httpx
import pytest

from agent_trader.runtime import publish, supervisor
from agent_trader.runtime.broker import Broker
from agent_trader.runtime.config import ET
from agent_trader.runtime.engine import Engine
from tests.runtime.test_scheduler_priorities import prepare, scheduler as scheduler
from tests.runtime.test_operational_session import clock as session_clock
from tests.runtime.session_fixtures import install as install_session


def test_nested_parent_survives_refresh_and_authorizes_real_protective_shrink(
    config, store, now
):
    leg = {
        "symbol": "AAPL", "qty": "10", "filled_qty": "0", "filled_avg_price": None,
        "status": "new", "side": "sell", "legs": None,
    }
    stop = {**leg, "id": "stop", "client_order_id": "stop-client", "type": "stop", "stop_price": "97"}
    take = {**leg, "id": "take", "client_order_id": "take-client", "type": "limit", "limit_price": "110"}
    parent = {
        **leg, "id": "parent", "client_order_id": "parent-client", "side": "buy",
        "status": "filled", "filled_qty": "10", "filled_avg_price": "100",
        "order_class": "bracket", "legs": [stop, take],
    }
    items = {item["id"]: item for item in (parent, stop, take)}
    balance = {"cash": "29000", "qty": "10", "market_value": "1000"}
    parent_queries = []

    def transport(request):
        path = request.url.path
        if path.startswith("/v2/orders/"):
            result = copy.deepcopy(items[path.rsplit("/", 1)[-1]])
            if result["id"] == "parent":
                parent_queries.append(dict(request.url.params))
            # Match Alpaca: flat retrieval has no protective-child ancestry.
            if request.url.params.get("nested") != "true":
                result["legs"] = None
        elif path == "/v2/orders":
            result = [copy.deepcopy(parent)]
        elif path == "/v2/account":
            result = {"status": "ACTIVE", "cash": balance["cash"], "equity": "30000"}
        elif path == "/v2/positions":
            result = [{"symbol": "AAPL", "qty": balance["qty"], "market_value": balance["market_value"]}]
        else:
            pytest.fail("Unexpected broker route")
        return httpx.Response(200, json=result)

    broker = Broker.__new__(Broker)
    broker.client = httpx.Client(transport=httpx.MockTransport(transport))
    try:
        engine = Engine(config, store, broker)
        engine.ingest_order(parent, "intraday", "owned-plan")
        assert engine.reconcile(now)
        stop["qty"] = "6"
        take.update(status="partially_filled", filled_qty="4", filled_avg_price="110")
        balance.update(cash="29440", qty="6", market_value="660")
        assert engine.reconcile(now + timedelta(seconds=30))
        assert engine.reconcile(now + timedelta(seconds=60))
        assert all(query == {"nested": "true"} for query in parent_queries)
        assert store.rows("SELECT qty,cost FROM holdings") == [{"qty": 6.0, "cost": 600.0}]
        assert store.rows("SELECT cash FROM branches WHERE name='intraday'")[0]["cash"] == 9440
        assert len(store.rows("SELECT id FROM events WHERE kind='fill'")) == 2
    finally:
        broker.client.close()


def test_slow_notification_defers_stale_clock_then_fresh_tick_prioritizes_closing(
    scheduler, broker, monkeypatch
):
    now = datetime(2026, 11, 6, 15, 49, tzinfo=ET)
    prepare(scheduler, broker, monkeypatch, now)
    elapsed = [0.0]
    monkeypatch.setattr(supervisor.time, "monotonic", lambda: elapsed[0])

    def delayed_notification(*args, **kwargs):
        # Simulate prior reconciliation plus a notification timeout, without sleeping.
        elapsed[0] += 31
        return False

    def delayed_clock():
        stamp = now + timedelta(seconds=elapsed[0])
        elapsed[0] += 20
        return session_clock(stamp, next_day="2026-11-09")

    monkeypatch.setattr(supervisor, "notify", delayed_notification)
    monkeypatch.setattr(broker, "clock", delayed_clock)
    closed = []
    monkeypatch.setattr(scheduler.engine, "close_intraday", lambda **kwargs: closed.append(True))
    scheduler.tick(now)
    assert closed == []
    assert scheduler.store.get("market_open") is False
    assert scheduler.store.get("operational_session")["assessment"]["reason_codes"] == ["clock_timestamp_stale"]
    later = now + timedelta(seconds=elapsed[0])
    prepare(scheduler, broker, monkeypatch, later)
    monkeypatch.setattr(supervisor, "notify", lambda *args, **kwargs: False)
    monkeypatch.setattr(scheduler.engine, "ensure_protection", lambda **kwargs: pytest.fail("Closing takes priority on recovery"))
    scheduler.tick(later)
    assert closed == [True]
    assert scheduler.store.get("market_open") is True
    codes = [json.loads(row["payload"])["code"] for row in scheduler.store.rows("SELECT payload FROM events WHERE kind='incident'")]
    assert codes == ["broker_clock"]  # The stale episode remains visible after recovery.


def held_exit(scheduler, broker, now, *, protected=False):
    parent = {
        "id": "buy", "client_order_id": "owned-buy", "symbol": "AAPL", "qty": "1",
        "side": "buy", "type": "limit", "status": "filled", "filled_qty": "1",
        "filled_avg_price": "100", "legs": None,
    }
    broker.items[parent["id"]] = parent
    broker.cash = 29900
    broker.pos = [{"symbol": "AAPL", "qty": "1", "market_value": "100"}]
    scheduler.engine.ingest_order(parent, "swing", "owned-swing")
    if protected:
        stop = {
            **parent, "id": "stop", "client_order_id": "owned-stop", "side": "sell",
            "type": "stop", "status": "new", "filled_qty": "0", "filled_avg_price": None,
            "stop_price": "97",
        }
        broker.items[stop["id"]] = stop
        scheduler.engine.ingest_order(stop, "swing", "owned-swing")
    scheduler.store.set("exit-intent:AAPL", {
        "at": now.isoformat(), "branch": "swing", "plan_id": "owned-swing",
        "reason": "Validated thesis invalidation",
    })
    assert scheduler.engine.reconcile(now)


def quotes_fail(*args):
    raise httpx.ReadTimeout("isolated quote outage")


def test_validated_exit_submits_once_despite_market_data_outage(scheduler, broker, monkeypatch):
    now = datetime(2026, 11, 9, 10, tzinfo=ET)
    held_exit(scheduler, broker, now)
    install_session(scheduler.store, now)
    monkeypatch.setattr(broker, "quotes", quotes_fail)
    monkeypatch.setattr(scheduler.engine, "enter", lambda *a: pytest.fail("No entry without quotes"))
    # This fixture normally stubs market_tick; invoke the implementation explicitly.
    for _ in range(2):
        with pytest.raises(httpx.ReadTimeout):
            supervisor.Supervisor.market_tick(scheduler, now, now + timedelta(hours=1))
    assert broker.submissions == 1
    assert scheduler.store.get("exit-intent:AAPL") is None
    assert scheduler.store.rows("SELECT side,qty,status FROM orders WHERE client_id!='owned-buy'") == [
        {"side": "sell", "qty": 1.0, "status": "new"}
    ]
    assert scheduler.store.rows("SELECT qty FROM holdings") == [{"qty": 1.0}]


def test_quote_outage_keeps_exit_pending_until_protection_cancel_confirmed(
    scheduler, broker, monkeypatch
):
    now = datetime(2026, 11, 9, 10, tzinfo=ET)
    held_exit(scheduler, broker, now, protected=True)
    install_session(scheduler.store, now)
    monkeypatch.setattr(broker, "quotes", quotes_fail)
    monkeypatch.setattr(broker, "cancel", lambda oid: broker.items[oid].update(status="pending_cancel"))
    with pytest.raises(httpx.ReadTimeout):
        supervisor.Supervisor.market_tick(scheduler, now, now + timedelta(hours=1))
    assert broker.submissions == 0
    assert scheduler.store.get("exit-intent:AAPL")
    broker.items["stop"]["status"] = "canceled"
    assert scheduler.engine.reconcile(now)
    install_session(scheduler.store, now + timedelta(seconds=30))
    with pytest.raises(httpx.ReadTimeout):
        supervisor.Supervisor.market_tick(scheduler, now + timedelta(seconds=30), now + timedelta(hours=1))
    assert broker.submissions == 1
    assert scheduler.store.get("exit-intent:AAPL") is None


@pytest.mark.parametrize("case", ["other_owner", "unreconciled", "future", "expired"])
def test_quote_outage_does_not_weaken_exit_authorization(scheduler, broker, monkeypatch, case):
    now = datetime.now(ET)
    held_exit(scheduler, broker, now)
    intent = scheduler.store.get("exit-intent:AAPL")
    if case == "other_owner":
        intent["plan_id"] = "previous-position"
    elif case == "unreconciled":
        scheduler.store.set("reconciled", False)
    else:
        intent["at"] = (now + timedelta(minutes=1) if case == "future" else now - timedelta(minutes=6)).isoformat()
    scheduler.store.set("exit-intent:AAPL", intent)
    monkeypatch.setattr(broker, "quotes", quotes_fail)
    with pytest.raises(httpx.ReadTimeout):
        supervisor.Supervisor.market_tick(scheduler, now, now + timedelta(hours=1))
    assert broker.submissions == 0
    assert bool(scheduler.store.get("exit-intent:AAPL")) is (case != "other_owner")


def test_failed_accounting_refresh_retries_same_key_after_bounded_backoff(
    scheduler, monkeypatch
):
    from agent_trader.runtime import research_work

    now = datetime.now(ET)
    day = now.date().isoformat()
    scheduler.store.set("quota", {"at": now.isoformat()})
    key = "accounting-refresh:" + day
    assert scheduler.store.job_start(key)
    scheduler.store.job_end(key, False, {"error_type": "ReadTimeout"})
    monkeypatch.setattr(research_work, "next_work", lambda *a: None)
    launches = []

    def claim(key, role, context, day):
        if scheduler.store.job_start(key):
            launches.append((key, role))
            return True
        return False

    monkeypatch.setattr(scheduler, "launch", claim)
    assert not scheduler.launch_deep_research(now)
    scheduler.store.db.execute("UPDATE jobs SET at=? WHERE key=?", ((now - timedelta(minutes=31)).isoformat(), key))
    assert scheduler.launch_deep_research(now)
    assert not scheduler.launch_deep_research(now)
    assert launches == [(key, "accounting_refresh")]
    assert scheduler.store.rows("SELECT state,attempts FROM jobs WHERE key=?", (key,)) == [{"state": "running", "attempts": 2}]
    scheduler.store.job_end(key, False, {"error_type": "ReadTimeout"})
    assert not scheduler.launch_deep_research(now)
    assert launches == [(key, "accounting_refresh")]


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


def publication_repo(config, store, monkeypatch):
    git(config.root, "init", "-b", "main")
    git(config.root, "config", "user.name", "Runtime test")
    git(config.root, "config", "user.email", "runtime@example.invalid")
    for name in publish.PUBLIC_PATHS:
        target = config.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("public initial")
    git(config.root, "add", "docs")
    git(config.root, "commit", "-m", "initial")
    store.set("release", {"source_commit": git(config.root, "rev-parse", "HEAD").stdout.strip()})
    monkeypatch.setattr(publish, "export", lambda *args: (config.root / "docs/data/lab.json").write_text("public update"))
    original_git = publish.git_run
    pushes = []

    def offline_git(config, args, timeout=60):
        if args[0] == "push":
            pushes.append(args)
            return subprocess.CompletedProcess(args, 0, "", "")
        return original_git(config, args, timeout)

    monkeypatch.setattr(publish, "git_run", offline_git)
    return replace(config, publish=True), pushes, offline_git


@pytest.mark.parametrize("private_path", ["docs/private-note.txt", "private.env", "docs/data/lab.json\nprivate"])
def test_publication_rejects_unrelated_staged_paths_without_changing_user_index(
    config, store, monkeypatch, private_path
):
    config, pushes, _ = publication_repo(config, store, monkeypatch)
    path = config.root / private_path
    path.write_text("private draft sentinel")
    git(config.root, "add", "--", private_path)
    before_index = (config.root / ".git/index").read_bytes()
    before_head = git(config.root, "rev-parse", "HEAD").stdout
    with pytest.raises(RuntimeError, match="Unrelated staged"):
        publish.publish(config, store)
    assert (config.root / ".git/index").read_bytes() == before_index
    assert git(config.root, "rev-parse", "HEAD").stdout == before_head
    assert (config.root / "docs/data/lab.json").read_text() == "public initial"
    assert pushes == []


def test_concurrent_staging_cannot_add_private_file_to_publication_commit(config, store, monkeypatch):
    config, pushes, offline_git = publication_repo(config, store, monkeypatch)

    def racing_git(config, args, timeout=60):
        if args[0] == "commit":
            (config.root / "docs/private-note.txt").write_text("private draft sentinel")
            git(config.root, "add", "docs/private-note.txt")
        return offline_git(config, args, timeout)

    monkeypatch.setattr(publish, "git_run", racing_git)
    with pytest.raises(RuntimeError, match="Unreviewed tracked source"):
        publish.publish(config, store)
    assert pushes == []
    assert git(config.root, "diff", "HEAD^", "HEAD", "--name-only").stdout.splitlines() == ["docs/data/lab.json"]
    assert git(config.root, "diff", "--cached", "--name-only").stdout.splitlines() == ["docs/private-note.txt"]
    assert "docs/private-note.txt" not in git(config.root, "ls-tree", "-r", "--name-only", "HEAD").stdout.splitlines()


def test_fresh_target_from_delayed_quote_exits_in_same_tick(scheduler, broker, monkeypatch):
    from agent_trader.runtime import engine

    now = datetime(2026, 11, 9, 10, tzinfo=ET)
    held_exit(scheduler, broker, now)
    scheduler.store.set("exit-intent:AAPL", None)
    scheduler.store.db.execute(
        "INSERT INTO plans VALUES('owned-swing',?,'swing','executed',?)",
        (now.date().isoformat(), json.dumps({"target": 105})),
    )
    elapsed = [0.0]
    monkeypatch.setattr(supervisor.time, "monotonic", lambda: elapsed[0])
    closed = now.replace(hour=16)
    install_session(scheduler.store, now, closed=closed)
    scheduler.store.set("calendar:" + now.date().isoformat(), scheduler.store.get("operational_session")["calendar_raw"])

    class ExecutionClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return (now + timedelta(seconds=elapsed[0])).astimezone(tz or ET)

    monkeypatch.setattr(engine, "datetime", ExecutionClock)

    def delayed_quotes(symbols):
        elapsed[0] += 20
        return {"AAPL": {"bp": 110, "ap": 110.01, "t": (now + timedelta(seconds=20)).isoformat()}}

    monkeypatch.setattr(broker, "quotes", delayed_quotes)
    monkeypatch.setattr(scheduler, "benchmarks", lambda *a: None)
    supervisor.Supervisor.market_tick(scheduler, now, closed)
    assert broker.submissions == 1
    assert scheduler.store.get("exit-intent:AAPL") is None
    sells = scheduler.store.rows("SELECT qty,status FROM orders WHERE side='sell'")
    assert sells == [{"qty": 1.0, "status": "new"}]


def test_slow_execution_check_crossing_close_cutoff_runs_closing(scheduler, broker, monkeypatch):
    now = datetime(2026, 11, 6, 15, 47, 50, tzinfo=ET)
    prepare(scheduler, broker, monkeypatch, now)
    scheduler.store.set("readiness", {"execution_verified": False})
    elapsed = [0.0]
    monkeypatch.setattr(supervisor.time, "monotonic", lambda: elapsed[0])
    monkeypatch.setattr(scheduler, "smoke", lambda *a: elapsed.__setitem__(0, 30))
    monkeypatch.setattr(scheduler.engine, "ensure_protection", lambda **kwargs: pytest.fail("Closing now takes priority"))
    closed = []
    monkeypatch.setattr(scheduler.engine, "close_intraday", lambda **kwargs: closed.append(True))
    scheduler.tick(now)
    assert closed == [True]


@pytest.mark.parametrize("case", ["different_branch", "detached", "missing_receipt", "unknown_ancestor"])
def test_publisher_requires_reviewed_configured_branch_before_mutating_files(
    config, store, monkeypatch, case
):
    config, pushes, _ = publication_repo(config, store, monkeypatch)
    if case == "different_branch":
        git(config.root, "checkout", "-b", "feature")
    elif case == "detached":
        git(config.root, "checkout", "--detach")
    elif case == "missing_receipt":
        store.set("release", {})
    else:
        store.set("release", {"source_commit": "a" * 40})
    before_head = git(config.root, "rev-parse", "HEAD").stdout
    before_index = (config.root / ".git/index").read_bytes()
    with pytest.raises(RuntimeError):
        publish.publish(config, store)
    assert git(config.root, "rev-parse", "HEAD").stdout == before_head
    assert (config.root / ".git/index").read_bytes() == before_index
    assert (config.root / "docs/data/lab.json").read_text() == "public initial"
    assert pushes == []


def test_configured_existing_branch_can_publish_only_frozen_reviewed_revision(config, store, monkeypatch):
    config, pushes, offline_git = publication_repo(config, store, monkeypatch)
    git(config.root, "checkout", "-b", "existing-runtime")
    config = replace(config, publish_branch="existing-runtime")
    validated = []

    def race_before_push(config, args, timeout=60):
        if args[0] == "push":
            validated.append(args[2].split(":")[0])
            # A local commit after validation must not be included in this push.
            (config.root / "unreviewed.py").write_text("unreviewed = True")
            git(config.root, "add", "unreviewed.py")
            git(config.root, "commit", "-m", "later unrelated source")
        return offline_git(config, args, timeout)

    monkeypatch.setattr(publish, "git_run", race_before_push)
    result = publish.publish(config, store)
    assert result["status"] == "pushed"
    assert result["commit"] == validated[0]
    assert pushes == [["push", "origin", validated[0] + ":main"]]
    assert result["commit"] != git(config.root, "rev-parse", "HEAD").stdout.strip()
    assert "unreviewed.py" not in git(config.root, "ls-tree", "-r", "--name-only", result["commit"]).stdout.splitlines()


@pytest.mark.parametrize("history", ["source", "source_reverted", "merged_source"])
def test_publisher_checks_every_commit_after_review_not_only_final_tree(
    config, store, monkeypatch, history
):
    config, pushes, _ = publication_repo(config, store, monkeypatch)
    if history == "merged_source":
        git(config.root, "checkout", "-b", "unreviewed-feature")
    (config.root / "source.py").write_text("unreviewed = True")
    git(config.root, "add", "source.py")
    git(config.root, "commit", "-m", "unreviewed source")
    if history == "source_reverted":
        git(config.root, "revert", "--no-edit", "HEAD")
        assert git(config.root, "diff", store.get("release")["source_commit"], "HEAD", "--name-only").stdout == ""
    elif history == "merged_source":
        git(config.root, "checkout", "main")
        git(config.root, "merge", "--no-ff", "unreviewed-feature", "-m", "merge unreviewed")
    with pytest.raises(RuntimeError, match="Unreviewed source"):
        publish.publish(config, store)
    assert pushes == []


def test_publisher_rejects_branch_change_after_staging(config, store, monkeypatch):
    config, pushes, offline_git = publication_repo(config, store, monkeypatch)

    def switch_after_add(config, args, timeout=60):
        result = offline_git(config, args, timeout)
        if args[0] == "add":
            git(config.root, "checkout", "-b", "other-work")
        return result

    monkeypatch.setattr(publish, "git_run", switch_after_add)
    with pytest.raises(RuntimeError, match="configured local branch"):
        publish.publish(config, store)
    assert pushes == []
    assert git(config.root, "rev-parse", "HEAD").stdout.strip() == store.get("release")["source_commit"]


def test_tick_applies_pending_exit_before_quote_dependent_protection_repair(
    scheduler, broker, monkeypatch
):
    now = datetime(2026, 11, 6, 11, 0, tzinfo=ET)
    held_exit(scheduler, broker, now)
    prepare(scheduler, broker, monkeypatch, now)
    monkeypatch.setattr(
        scheduler, "market_tick", supervisor.Supervisor.market_tick.__get__(scheduler),
    )
    monkeypatch.setattr(broker, "quotes", quotes_fail)
    with pytest.raises(httpx.ReadTimeout):
        scheduler.tick(now)
    assert broker.submissions == 1
    assert scheduler.store.get("exit-intent:AAPL") is None
    assert scheduler.store.rows("SELECT side,qty,status FROM orders WHERE side='sell'") == [
        {"side": "sell", "qty": 1.0, "status": "new"}
    ]


@pytest.mark.parametrize("staged", [False, True])
def test_dirty_tracked_source_cannot_leak_through_generated_dashboard(
    config, store, monkeypatch, staged
):
    config, pushes, _ = publication_repo(config, store, monkeypatch)
    source = config.root / "src/runtime/web/app.js"
    source.parent.mkdir(parents=True)
    source.write_text("reviewed frontend")
    git(config.root, "add", "src/runtime/web/app.js")
    git(config.root, "commit", "-m", "reviewed frontend source")
    store.set("release", {"source_commit": git(config.root, "rev-parse", "HEAD").stdout.strip()})
    source.write_text("unreviewed frontend edit")
    if staged:
        git(config.root, "add", "src/runtime/web/app.js")
    before_index = (config.root / ".git/index").read_bytes()
    with pytest.raises(RuntimeError, match="Unrelated staged" if staged else "Unreviewed tracked source"):
        publish.publish(config, store)
    assert source.read_text() == "unreviewed frontend edit"
    assert (config.root / ".git/index").read_bytes() == before_index
    assert (config.root / "docs/data/lab.json").read_text() == "public initial"
    assert pushes == []


def test_dirty_generated_dashboard_is_allowed_with_reviewed_clean_source(config, store, monkeypatch):
    config, pushes, _ = publication_repo(config, store, monkeypatch)
    (config.root / "docs/app.js").write_text("generated frontend")
    assert publish.publish(config, store)["status"] == "pushed"
    assert len(pushes) == 1
    assert git(config.root, "diff", "HEAD^", "HEAD", "--name-only").stdout.splitlines() == [
        "docs/app.js", "docs/data/lab.json",
    ]


@pytest.mark.parametrize("elapsed_seconds,can_recover", [(61, True), (781, False)])
def test_protection_latency_rechecks_closing_and_actual_session_end(
    scheduler, broker, monkeypatch, elapsed_seconds, can_recover
):
    now = datetime(2026, 11, 6, 15, 47, 59, tzinfo=ET)
    prepare(scheduler, broker, monkeypatch, now)
    elapsed = [0.0]
    monkeypatch.setattr(supervisor.time, "monotonic", lambda: elapsed[0])
    monkeypatch.setattr(scheduler.engine, "ensure_protection", lambda **kwargs: elapsed.__setitem__(0, elapsed_seconds))
    monkeypatch.setattr(scheduler, "market_tick", lambda *a: pytest.fail("Session deadline takes priority"))
    closes = []
    monkeypatch.setattr(scheduler.engine, "close_intraday", lambda **kwargs: closes.append(True))
    scheduler.tick(now)
    assert closes == []
    assert scheduler.store.get("market_open") is False
    assert "Existing protection retained" in scheduler.store.get("status")
    later = now + timedelta(seconds=elapsed_seconds)
    prepare(scheduler, broker, monkeypatch, later)
    monkeypatch.setattr(scheduler.engine, "ensure_protection", lambda **kwargs: pytest.fail("Fresh closing tick bypasses protection lookup"))
    monkeypatch.setattr(scheduler, "launch", lambda *args: False)
    scheduler.tick(later)
    assert bool(closes) is can_recover


def test_late_open_clock_response_cannot_authorize_market_exits_after_actual_close(
    scheduler, broker, monkeypatch
):
    now = datetime(2026, 11, 6, 15, 59, 50, tzinfo=ET)
    prepare(scheduler, broker, monkeypatch, now)
    elapsed = [0.0]
    monkeypatch.setattr(supervisor.time, "monotonic", lambda: elapsed[0])

    def delayed_clock():
        elapsed[0] = 20
        return session_clock(now, next_day="2026-11-09")

    monkeypatch.setattr(broker, "clock", delayed_clock)
    monkeypatch.setattr(scheduler.engine, "close_intraday", lambda **kwargs: pytest.fail("No market exit after close"))
    monkeypatch.setattr(scheduler, "apply_pending_exits", lambda *a: pytest.fail("No approved exit after close"))
    scheduler.tick(now)
    assert scheduler.store.get("market_open") is False


def test_pending_exit_latency_rechecks_cutoff_before_restoring_protection(scheduler, broker, monkeypatch):
    now = datetime(2026, 11, 6, 15, 47, 59, tzinfo=ET)
    prepare(scheduler, broker, monkeypatch, now)
    elapsed = [0.0]
    monkeypatch.setattr(supervisor.time, "monotonic", lambda: elapsed[0])

    def delayed_pending(*args):
        elapsed[0] = 61
        return set()

    monkeypatch.setattr(scheduler, "apply_pending_exits", delayed_pending)
    monkeypatch.setattr(scheduler.engine, "ensure_protection", lambda **kwargs: pytest.fail("Closing already due"))
    closes = []
    monkeypatch.setattr(scheduler.engine, "close_intraday", lambda **kwargs: closes.append(True))
    scheduler.tick(now)
    assert closes == []
    assert scheduler.store.get("market_open") is False
    later = now + timedelta(seconds=61)
    prepare(scheduler, broker, monkeypatch, later)
    monkeypatch.setattr(scheduler, "apply_pending_exits", lambda *args: pytest.fail("Fresh closing tick bypasses pending-exit lookup"))
    scheduler.tick(later)
    assert closes == [True]
