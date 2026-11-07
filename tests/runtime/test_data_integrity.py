import json
from datetime import date, datetime, timedelta

from agent_trader.runtime.config import ET
from agent_trader.runtime.features import minute_features
from agent_trader.runtime.research import parse_macro_download
from tests.runtime.test_quality import minute


def test_off_grid_bars_cannot_hide_a_missing_regular_session_interval():
    opened = datetime(2026, 11, 6, 9, 30, tzinfo=ET)
    rows = [minute(opened + timedelta(minutes=i)) for i in [0, 1, 2, 3, 4, 6]]
    # Without grid validation these two records make the row count look complete
    # even though the 09:35 and 09:37 minute observations are absent.
    rows += [minute(opened + timedelta(minutes=5, seconds=15), 900),
             minute(opened + timedelta(minutes=6, microseconds=1), 800)]
    result = minute_features(
        {"SPY": rows}, opened + timedelta(minutes=8), opened, opened.replace(hour=16)
    )["SPY"]
    assert result["missing_minute_intervals"] == 2
    assert result["observed_minute_bars"] == 6
    assert result["opening_5m_complete"]
    assert result["high_so_far"] == 102
    assert result["session_volume_iex"] == 60


def test_macro_invalid_latest_values_preserve_prior_date_and_serialize():
    content = b"DATE,DGS2,DGS10,VIXCLS\n2026-11-04,3.7,4.1,19\n2026-11-05,NaN,Infinity,-inf\n"
    result = parse_macro_download(content, ["DGS2", "DGS10", "VIXCLS"], date(2026, 11, 7))
    assert set(result) == {"DGS2", "DGS10", "VIXCLS"}
    assert all(row["observation_date"] == "2026-11-04" for row in result.values())
    json.dumps(result, allow_nan=False)


def test_macro_selects_latest_dated_valid_observation_in_unsorted_download():
    content = (
        b"DATE,DGS2\n2026-11-05,3.8\n2026-11-04,3.7\n"
        b"2026-11-08,999\nnot-a-date,123\n2026-11-06,.\n"
    )
    result = parse_macro_download(content, ["DGS2"], date(2026, 11, 7))
    assert result == {"DGS2": {"value": 3.8, "observation_date": "2026-11-05"}}
