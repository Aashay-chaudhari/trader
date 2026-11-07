from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

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
        # Route templates identify failures without persisting symbols, broker
        # identifiers, payloads, credentials or provider error response bodies.
        route = path
        for prefix in ("/v2/orders/", "/v2/assets/", "/v1beta1/options/snapshots/"):
            if path.startswith(prefix):
                route = prefix + ":item"
        details = {"service": "market_data" if data else "paper_broker",
                   "method": method, "route": route, "attempt_id": str(uuid4())}
        try:
            r = self.client.request(method, base + path, params=params, json=payload)
            if r.status_code >= 400:
                details["http_status"] = r.status_code
                raise BrokerError(r.status_code)
            return r.json() if r.content else None
        except (httpx.HTTPError, BrokerError, ValueError) as exc:
            exc.operation_details = details
            raise

    def account(self):
        return self.request("GET", "/v2/account")

    def account_activities(self, *, page_size=100, max_pages=100):
        """Read complete paper-account activity history or reject a partial batch.

        The trading API uses the last activity ID as its next-page token. No
        date filter is used: fees can be created after their associated trade.
        """
        if not 1 <= page_size <= 100 or max_pages < 1:
            raise ValueError("Invalid account activity pagination limits")
        params = {"direction": "asc", "page_size": page_size}
        result, seen = [], set()
        for _ in range(max_pages):
            page = self.request("GET", "/v2/account/activities", params=params)
            if not isinstance(page, list) or len(page) > page_size:
                raise ValueError("Invalid account activity response")
            for activity in page:
                identity = activity.get("id") if isinstance(activity, dict) else None
                if not isinstance(identity, str) or not identity or identity in seen:
                    raise ValueError("Missing or repeated account activity identity")
                seen.add(identity)
                result.append(activity)
            if len(page) < page_size:
                return result
            params = {**params, "page_token": page[-1]["id"]}
        raise ValueError("Account activity pagination exhausted; partial batch rejected")

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
        return self.bar_pages(
            {
                "symbols": ",".join(symbols),
                "timeframe": "1Day",
                "feed": "iex",
                "start": (datetime.now(ET).date() - timedelta(days=days)).isoformat(),
                "end": (datetime.now(ET) - timedelta(minutes=20)).isoformat(),
                "limit": 10000,
                "adjustment": "all",
            }
        )

    def bar_pages(self, params, max_pages=4):
        """Never silently truncate a symbol-sorted multi-symbol response."""
        result, seen = {}, set()
        for _ in range(max_pages):
            page = self.request("GET", "/v2/stocks/bars", data=True, params=params)
            for symbol, values in page.get("bars", {}).items():
                result.setdefault(symbol, []).extend(values)
            token = page.get("next_page_token")
            if not token:
                return result
            if token in seen:
                raise ValueError("Repeated market-data pagination token")
            seen.add(token)
            params = {**params, "page_token": token}
        raise ValueError("Market-data pagination budget exhausted; partial batch rejected")

    def intraday_bars(self, symbols, start, end):
        return self.bar_pages(
            {
                "symbols": ",".join(symbols),
                "timeframe": "1Min",
                "feed": "iex",
                "start": start.isoformat(),
                "end": end.isoformat(),
                "limit": 10000,
                "adjustment": "raw",
            }
        )

    def option_chain(self, symbol):
        return self.request(
            "GET",
            f"/v1beta1/options/snapshots/{symbol}",
            data=True,
            params={"feed": "indicative", "limit": 30},
        )
