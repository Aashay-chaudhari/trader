"""Free official release calendars. Unknown timing and fetch failures stay explicit."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx

from .config import ET
from .engine import timestamp

FEEDS = {
    "BLS": "https://www.bls.gov/schedule/news_release/bls.ics",
    "BEA": "https://www.bea.gov/news/schedule/ics/online-calendar-subscription.ics",
}


def parse_calendar(text, agency, source, observed_at):
    if "BEGIN:VCALENDAR" not in text or len(text) > 2_000_000:
        raise ValueError("Invalid or oversized official calendar")
    unfolded = re.sub(r"\r?\n[ \t]", "", text)
    rows, current = [], None
    for line in unfolded.splitlines():
        line = line.strip()
        if line == "BEGIN:VEVENT":
            current = {}
        elif line == "END:VEVENT" and current is not None:
            raw = current.get("DTSTART")
            if raw:
                value, parameters = raw
                try:
                    if len(value) == 8:
                        when, timing_known = (
                            datetime.strptime(value, "%Y%m%d").date().isoformat(),
                            False,
                        )
                    else:
                        dt = datetime.strptime(value.rstrip("Z"), "%Y%m%dT%H%M%S")
                        zone = parameters.get("TZID", "").strip('"') or None
                        if value.endswith("Z"):
                            dt = dt.replace(tzinfo=timezone.utc)
                        elif zone in ("US/Eastern", "Eastern Standard Time"):
                            dt = dt.replace(tzinfo=ET)
                        elif zone:
                            dt = dt.replace(tzinfo=ZoneInfo(zone))
                        timing_known = dt.tzinfo is not None
                        when = (
                            dt.astimezone(ET).isoformat() if timing_known else dt.date().isoformat()
                        )
                    title = current.get("SUMMARY", ("Untitled official release", {}))[0]
                    title = title.replace("\\n", " ").replace("\\,", ",").replace("\\;", ";")[:300]
                    candidate = current.get("URL", (source, {}))[0]
                    parsed = urlsplit(candidate)
                    domain = "bls.gov" if agency == "BLS" else "bea.gov"
                    url = (
                        candidate
                        if parsed.scheme == "https"
                        and (
                            parsed.hostname == domain
                            or (parsed.hostname or "").endswith("." + domain)
                        )
                        else source
                    )
                    rows.append(
                        {
                            "title": title,
                            "when": when,
                            "timing_known": timing_known,
                            "symbols": [],
                            "importance": "high"
                            if re.search(
                                r"employment situation|consumer price|employment cost|gross domestic|\bGDP\b|personal income|producer price",
                                title,
                                re.I,
                            )
                            else "medium",
                            "source_url": url,
                            "agency": agency,
                            "observed_at": observed_at,
                            "implication": "Official scheduled release; verify revisions and exposure before entry. No consensus forecast supplied.",
                        }
                    )
                except (ValueError, KeyError):
                    pass
            current = None
        elif current is not None and ":" in line:
            left, value = line.split(":", 1)
            parts = left.split(";")
            if parts[0] == "RRULE":
                raise ValueError("Recurring calendar expansion is not implemented")
            current[parts[0]] = (value, dict(p.split("=", 1) for p in parts[1:] if "=" in p))
    if not rows:
        raise ValueError("No recognizable dated official events")
    return rows


def official_calendar(store, now=None):
    now = now or datetime.now(timezone.utc)
    result = {"observed_at": now.isoformat(), "events": [], "sources": [], "unknowns": []}
    for agency, url in FEEDS.items():
        key = "official-calendar:" + agency
        cached = store.get(key)
        status = "ok"
        due = not cached or (now - timestamp(cached["retrieved_at"])).total_seconds() > 6 * 3600
        failure = store.get("official-calendar-failure:" + agency)
        if due and failure and 0 <= (now - timestamp(failure["at"])).total_seconds() < 1800:
            status = "stale" if cached else "unavailable"
            result["unknowns"].append(
                agency
                + " official calendar "
                + status
                + "; recent fetch failure, source recheck backoff active"
            )
            due = False
        if due:
            try:
                response = httpx.get(
                    url,
                    timeout=15,
                    follow_redirects=True,
                    headers={
                        "User-Agent": "TraderPublicResearch/2.0 (+https://github.com/Aashay-chaudhari/trader)"
                    },
                )
                response.raise_for_status()
                if len(response.content) > 2_000_000:
                    raise ValueError("Calendar size limit")
                events = parse_calendar(response.text, agency, url, now.isoformat())
                cached = {
                    "retrieved_at": now.isoformat(),
                    "events": events,
                    "sha256": hashlib.sha256(response.content).hexdigest(),
                }
                store.set(key, cached)
                store.set("official-calendar-failure:" + agency, None)
            except Exception as exc:
                store.set(
                    "official-calendar-failure:" + agency,
                    {"at": now.isoformat(), "error_type": type(exc).__name__},
                )
                status = "stale" if cached else "unavailable"
                result["unknowns"].append(
                    agency + " official calendar " + status + " (" + type(exc).__name__ + ")"
                )
        result["sources"].append(
            {
                "agency": agency,
                "url": url,
                "status": status,
                "retrieved_at": cached.get("retrieved_at") if cached else None,
            }
        )
        if cached:
            for event in cached["events"]:
                event_day = datetime.fromisoformat(event["when"]).date()
                if (
                    now.astimezone(ET).date() - timedelta(days=1)
                    <= event_day
                    <= now.astimezone(ET).date() + timedelta(days=14)
                ):
                    result["events"].append({**event, "calendar_status": status})
    result["events"] = sorted(result["events"], key=lambda e: e["when"])[:50]
    store.set("official_calendar", result)
    return result
