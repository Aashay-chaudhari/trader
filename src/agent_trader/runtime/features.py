"""Feed-specific research features. No signals, strategy changes or order authority."""

from __future__ import annotations

import math
from datetime import timedelta

from .engine import quote_values, timestamp


def minute_features(bars, now, opened, closed):
    result = {}
    cutoff = min(now, closed)
    for symbol, raw in bars.items():
        valid = {}
        for r in raw:
            try:
                at = timestamp(r["t"])
                o, h, low, c, v = (float(r[k]) for k in ("o", "h", "l", "c", "v"))
                if (
                    not all(math.isfinite(x) for x in (o, h, low, c, v))
                    or not 0 < low <= min(o, c) <= max(o, c) <= h
                    or v < 0
                    or at < opened
                    or at + timedelta(minutes=1) > cutoff
                ):
                    continue
                valid[at] = {**r, "v": v, "h": h, "l": low, "o": o, "c": c}
            except (ValueError, KeyError, TypeError):
                continue
        if not valid:
            continue
        times = sorted(valid)
        rows = [valid[t] for t in times]
        volume = sum(r["v"] for r in rows)
        weighted, covered = 0.0, 0.0
        for r in rows:
            try:
                vw = float(r["vw"])
                if math.isfinite(vw) and vw > 0:
                    weighted += vw * r["v"]
                    covered += r["v"]
            except (KeyError, TypeError, ValueError):
                pass
        opening = [valid.get(opened + timedelta(minutes=i)) for i in range(5)]
        complete = all(r is not None for r in opening)
        result[symbol] = {
            "feed": "iex",
            "asof": (times[-1] + timedelta(minutes=1)).isoformat(),
            "observed_minute_bars": len(rows),
            "missing_minute_intervals": max(
                0, int((cutoff - opened).total_seconds() // 60) - len(rows)
            ),
            "last_completed_close": rows[-1]["c"],
            "high_so_far": max(r["h"] for r in rows),
            "low_so_far": min(r["l"] for r in rows),
            "session_volume_iex": volume,
            "bar_vwap_iex": weighted / volume if volume > 0 and covered == volume else None,
            "vwap_volume_coverage": covered / volume if volume > 0 else 0,
            "opening_5m_high": max(r["h"] for r in opening) if complete else None,
            "opening_5m_low": min(r["l"] for r in opening) if complete else None,
            "opening_5m_complete": complete,
            "age_seconds": max(0, (now - (times[-1] + timedelta(minutes=1))).total_seconds()),
        }
    return result


def research_focus(packet, now, limit=3):
    """Prioritize verifiable data for bounded discovery, never approve a trade."""
    ranked = []
    for symbol in packet.get("universe", []):
        snapshot = packet.get("market", {}).get(symbol, {})
        daily = packet.get("daily_indicators", {}).get(symbol, {})
        minute = packet.get("intraday_indicators", {}).get(symbol, {})
        try:
            bid, ask = quote_values(snapshot.get("latestQuote") or {}, now)
            fresh = True
        except (ValueError, TypeError, KeyError):
            fresh = False
        ready = (
            fresh
            and minute.get("opening_5m_complete", False)
            and minute.get("age_seconds", 9999) <= 120
        )
        ranked.append((not ready, not fresh, -abs(daily.get("return_5d") or 0), symbol))
    return [x[-1] for x in sorted(ranked)[:limit]]
