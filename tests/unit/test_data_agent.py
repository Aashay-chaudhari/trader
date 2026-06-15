from datetime import datetime, timedelta, timezone

import pandas as pd

from agent_trader.agents.data_agent import DataAgent


class FakeTicker:
    def __init__(self, intraday: pd.DataFrame):
        self.intraday = intraday

    def history(self, **kwargs):
        assert kwargs["interval"] == "1m"
        return self.intraday


def test_latest_quote_prefers_timestamped_one_minute_bar(message_bus):
    timestamp = datetime.now(timezone.utc) - timedelta(seconds=30)
    intraday = pd.DataFrame({"Close": [101.25]}, index=pd.DatetimeIndex([timestamp]))
    daily = pd.DataFrame(
        {"Close": [99.0]}, index=pd.DatetimeIndex([timestamp - timedelta(days=1)])
    )

    quote = DataAgent(message_bus)._fetch_latest_quote(FakeTicker(intraday), daily)

    assert quote["price"] == 101.25
    assert quote["source"] == "yahoo_1m"
    assert quote["is_fresh"] is True
    assert quote["age_seconds"] < 300


def test_latest_quote_marks_daily_fallback_stale(message_bus):
    timestamp = datetime.now(timezone.utc) - timedelta(days=1)
    daily = pd.DataFrame({"Close": [99.0]}, index=pd.DatetimeIndex([timestamp]))

    quote = DataAgent(message_bus)._fetch_latest_quote(FakeTicker(pd.DataFrame()), daily)

    assert quote["price"] == 99.0
    assert quote["source"] == "yahoo_daily_fallback"
    assert quote["is_fresh"] is False
