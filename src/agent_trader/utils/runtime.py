"""Runtime helpers for environment-specific setup."""

from functools import lru_cache
from pathlib import Path

import yfinance as yf


@lru_cache(maxsize=1)
def configure_yfinance_cache(cache_root: str = "data/cache/yfinance_tz") -> str:
    """Point yfinance's timezone cache at a writable repo-local directory."""
    cache_dir = Path(cache_root)
    cache_dir.mkdir(parents=True, exist_ok=True)

    try:
        yf.set_tz_cache_location(str(cache_dir.resolve()))
    except Exception:
        # If yfinance changes internals, we still want the app to run.
        pass

    return str(cache_dir)
