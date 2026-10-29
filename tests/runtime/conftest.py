import copy
from datetime import datetime, timedelta, timezone

import pytest

from agent_trader.runtime.config import Config
from agent_trader.runtime.store import Store


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "state.sqlite3")
    yield s
    s.close()


@pytest.fixture
def config(tmp_path):
    return Config(
        root=tmp_path,
        start_date="2026-01-01",
        execution=True,
        publish=False,
        api_key="fake-key",
        secret_key="fake-secret",
        ntfy_topic="private-topic",
    )


@pytest.fixture
def now():
    return datetime(2026, 10, 30, 14, 0, tzinfo=timezone.utc)


@pytest.fixture
def plan(now):
    return {
        "id": "test-plan",
        "branch": "intraday",
        "symbol": "AAPL",
        "strategy": "catalyst-confirmation",
        "version": "pilot-v1",
        "thesis": "Verified catalyst with an observable price confirmation.",
        "entry_low": 99.0,
        "entry_high": 101.0,
        "stop": 97.0,
        "target": 107.0,
        "expires_at": (now + timedelta(hours=2)).isoformat(),
        "invalidation": "Break below the recorded support level.",
        "event_check": "Company earnings checked and not due today.",
        "event_risk_known": True,
        "confidence": 0.8,
        "evidence": [
            {
                "title": "Company disclosure",
                "url": "https://example.com/ir",
                "published_at": now.isoformat(),
                "observed_at": now.isoformat(),
                "takeaway": "Verified primary source.",
            }
        ],
    }


@pytest.fixture
def quote(now):
    return {"bp": 99.99, "ap": 100.0, "t": now.isoformat()}


class FakeBroker:
    def __init__(self):
        self.items = {}
        self.cash = 30000.0
        self.pos = []
        self.submissions = 0
        self.fail_after_accept = False

    def account(self):
        return {
            "status": "ACTIVE",
            "cash": str(self.cash),
            "equity": str(self.cash + sum(float(p["market_value"]) for p in self.pos)),
            "buying_power": "120000",
            "trading_blocked": False,
            "account_blocked": False,
        }

    def positions(self):
        return copy.deepcopy(self.pos)

    def orders(self):
        return [
            copy.deepcopy(o)
            for o in self.items.values()
            if o["status"] not in ("filled", "canceled", "rejected", "expired")
        ]

    def order(self, oid):
        return copy.deepcopy(self.items[oid])

    def by_client(self, cid):
        return next(
            (copy.deepcopy(o) for o in self.items.values() if o["client_order_id"] == cid), None
        )

    def quotes(self, symbols):
        return {
            s: {"bp": 100, "ap": 100.01, "t": datetime.now(timezone.utc).isoformat()}
            for s in symbols
        }

    def asset(self, symbol):
        return {"tradable": True, "status": "active"}

    def submit(self, payload):
        self.submissions += 1
        oid = "broker-" + str(self.submissions)
        item = {**payload, "id": oid, "status": "new", "filled_qty": "0", "filled_avg_price": None}
        self.items[oid] = item
        if self.fail_after_accept:
            raise TimeoutError("Response lost after server acceptance")
        return copy.deepcopy(item)

    def cancel(self, oid):
        self.items[oid]["status"] = "canceled"


@pytest.fixture
def broker():
    return FakeBroker()
