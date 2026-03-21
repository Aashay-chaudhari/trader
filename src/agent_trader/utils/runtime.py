"""Runtime helpers for environment-specific setup."""

from functools import lru_cache
from pathlib import Path

import yfinance as yf

from agent_trader.config.settings import get_settings


@lru_cache(maxsize=1)
def configure_yfinance_cache(cache_root: str | None = None) -> str:
    """Point yfinance's timezone cache at a writable repo-local directory."""
    if cache_root is None:
        cache_root = str(Path(get_settings().data_dir) / "cache" / "yfinance_tz")
    cache_dir = Path(cache_root)
    cache_dir.mkdir(parents=True, exist_ok=True)

    try:
        yf.set_tz_cache_location(str(cache_dir.resolve()))
    except Exception:
        # If yfinance changes internals, we still want the app to run.
        pass

    return str(cache_dir)
