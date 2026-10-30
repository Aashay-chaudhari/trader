from __future__ import annotations

from datetime import datetime, timedelta

from .config import ET

import httpx

PAPER_URL = "https://paper-api.alpaca.markets"
DATA_URL = "https://data.alpaca.markets"


class BrokerError(RuntimeError):
    def __init__(self, status, message="Broker request failed"):
        self.status = status
        super().__init__(f"{message} (HTTP {status})")


class Broker:
    """Deliberately has no configurable live endpoint or paid-feed fallback."""

    def __init__(self, config):
        if not config.api_key or not config.secret_key:
            raise ValueError("Local Alpaca paper credentials missing")
        self.client = httpx.Client(
            headers={
                "APCA-API-KEY-ID": config.api_key,
                "APCA-API-SECRET-KEY": config.secret_key,
            },
            timeout=20,
        )

    def request(self, method, path, *, data=False, params=None, payload=None):
        base = DATA_URL if data else PAPER_URL
        r = self.client.request(method, base + path, params=params, json=payload)
        if r.status_code >= 400:
            raise BrokerError(r.status_code)
        return r.json() if r.content else None

    def account(self):
        return self.request("GET", "/v2/account")

    def clock(self):
        return self.request("GET", "/v2/clock")

    def calendar(self, day: str):
        return self.request("GET", "/v2/calendar", params={"start": day, "end": day})

    def calendar_range(self, start, end):
        return self.request("GET", "/v2/calendar", params={"start": start, "end": end})

    def positions(self):
        return self.request("GET", "/v2/positions")

    def orders(self, status="open"):
        return self.request(
            "GET", "/v2/orders", params={"status": status, "limit": 500, "nested": "true"}
        )

    def order(self, broker_id):
        return self.request("GET", f"/v2/orders/{broker_id}")

    def by_client(self, client_id):
        try:
            return self.request(
                "GET", "/v2/orders:by_client_order_id", params={"client_order_id": client_id}
            )
        except BrokerError as e:
            if e.status == 404:
                return None
            raise

    def submit(self, payload):
        return self.request("POST", "/v2/orders", payload=payload)

    def cancel(self, broker_id):
        try:
            return self.request("DELETE", f"/v2/orders/{broker_id}")
        except BrokerError as e:
            if e.status not in (404, 422):
                raise

    def asset(self, symbol):
        return self.request("GET", f"/v2/assets/{symbol}")

    def quotes(self, symbols):
        if not symbols:
            return {}
        return self.request(
            "GET",
            "/v2/stocks/quotes/latest",
            data=True,
            params={"symbols": ",".join(sorted(set(symbols))), "feed": "iex"},
        ).get("quotes", {})

    def snapshots(self, symbols):
        if not symbols:
            return {}
        return self.request(
            "GET",
            "/v2/stocks/snapshots",
            data=True,
            params={"symbols": ",".join(sorted(set(symbols))), "feed": "iex"},
        )

    def bars(self, symbols, days=80):
        return self.request(
            "GET",
            "/v2/stocks/bars",
            data=True,
            params={
                "symbols": ",".join(symbols),
                "timeframe": "1Day",
                "feed": "iex",
                "start": (datetime.now(ET).date() - timedelta(days=days)).isoformat(),
                "end": (datetime.now(ET) - timedelta(minutes=20)).isoformat(),
                "limit": 10000,
                "adjustment": "all",
            },
        ).get("bars", {})

    def option_chain(self, symbol):
        return self.request(
            "GET",
            f"/v1beta1/options/snapshots/{symbol}",
            data=True,
            params={"feed": "indicative", "limit": 30},
        )
