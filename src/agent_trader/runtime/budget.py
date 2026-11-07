"""Measured account allowance and useful background-work admission.

Quota percentages are account-wide meter readings, never inferred token balances.
Background analysis has its own call allowance so it cannot consume the reserved
decision/review slots. All roles share the fixed account reserve.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from .config import ET

DEEP_ROLES = ("deep_research", "deep_research_review")
WEEKLY_CEILING = 80
WEEKLY_MINIMUM_TARGET = 50
DEEP_CALL_CEILING = 96


def account_limit_reason(quota, now=None):
    now = now or datetime.now(timezone.utc)
    if not isinstance(quota, dict):
        return "Account quota unavailable or access limited"
    windows = quota.get("windows", [])
    if not quota.get("ordinary_usage_allowed", False) or not isinstance(windows, list) or not windows:
        return "Account quota unavailable or access limited"
    if quota.get("at"):
        try:
            age = (now - datetime.fromisoformat(quota["at"].replace("Z", "+00:00"))).total_seconds()
        except (TypeError, ValueError, AttributeError):
            return "Invalid account quota observation time"
        if age < -60 or age > 900:
            return "Account quota observation is stale"
    weekly = []
    for window in windows:
        if not isinstance(window, dict) or any(
            type(window.get(k)) not in (int, float)
            for k in ("usedPercent", "windowDurationMins", "resetsAt")
        ):
            return "Malformed account quota window"
        try:
            used = float(window["usedPercent"])
            minutes = float(window["windowDurationMins"])
            reset = float(window["resetsAt"])
        except (KeyError, TypeError, ValueError):
            return "Malformed account quota window"
        if not all(math.isfinite(x) for x in (used, minutes, reset)):
            return "Malformed account quota window"
        if not 0 <= used <= 100 or minutes <= 0 or reset <= now.timestamp():
            return "Expired or invalid account quota window"
        if minutes >= 10000:
            weekly.append(window)
            if used >= WEEKLY_CEILING:
                return "20% account reserve reached"
        elif used >= 90:
            return "Short-window quota nearly exhausted"
    if not weekly:
        return "Weekly quota window unavailable"
    return None


def budget_check(store, quota, role, now):
    reason = account_limit_reason(quota, now)
    if reason:
        return False, reason
    weekly = [w for w in quota["windows"] if w["windowDurationMins"] >= 10000]
    # Every bucket must allow the call; pace against the most consumed one.
    window = max(weekly, key=lambda w: float(w["usedPercent"]))
    used, reset = float(window["usedPercent"]), int(window["resetsAt"])
    today = now.astimezone(ET).date().isoformat()
    placeholders = ",".join("?" for _ in DEEP_ROLES)
    deep = role in DEEP_ROLES
    count = store.rows(
        f"SELECT count(*) AS n FROM usage WHERE day=? AND role "
        f"{'IN' if deep else 'NOT IN'} ({placeholders})",
        (today, *DEEP_ROLES),
    )[0]["n"]
    if deep:
        if count >= DEEP_CALL_CEILING:
            return False, "Background research daily attempt ceiling reached"
        # The explicit November 7 target authorizes useful catch-up work without
        # the old 45%-of-paced-day throttle. Core work retains its own slots.
        return True, "Useful background work within account reserve and attempt ceiling"

    night_roles = (
        "retrospective", "maintenance", "weekly", "monthly",
        "research_audit", "research_audit_review",
    )
    critical_roles = ("decision", "position_review")
    ceiling = 24 if role in night_roles else (20 if role in critical_roles else 16)
    if count >= ceiling:
        return False, "Daily model-call ceiling reached"
    key = f"quota-baseline:{reset}"
    baseline = store.get(key)
    if baseline is None or used < baseline - 1:
        store.set(key, used)
    reset_day = datetime.fromtimestamp(reset, timezone.utc).astimezone(ET).date()
    import numpy as np

    trading_days = max(1, int(np.busday_count(now.astimezone(ET).date(), reset_day)) + 1)
    day_key = f"quota-day:{today}:{reset}"
    day_start = store.get(day_key)
    if day_start is None or used < day_start:
        day_start = used
        store.set(day_key, day_start)
    daily_allowance = max(1.0, (WEEKLY_CEILING - day_start) / trading_days)
    multiplier = 1.0 if role in night_roles else (0.8 if role in critical_roles else 0.45)
    if max(0, used - day_start) >= daily_allowance * multiplier:
        return False, "Paced daily quota allocation reached"
    return True, "Within account and paced daily limits"


def usage_policy(store, now=None):
    now = now or datetime.now(timezone.utc)
    quota = store.get("quota", {})
    windows = quota.get("windows", [])
    weekly = [w for w in windows if isinstance(w, dict)
              and type(w.get("windowDurationMins")) in (int, float)
              and w["windowDurationMins"] >= 10000] if isinstance(windows, list) else []
    valid_usage = []
    for window in weekly:
        try:
            used = float(window["usedPercent"])
            if math.isfinite(used) and 0 <= used <= 100:
                valid_usage.append(used)
        except (KeyError, TypeError, ValueError):
            continue
    used = max(valid_usage) if valid_usage else None
    return {
        "minimum_weekly_target": WEEKLY_MINIMUM_TARGET,
        "weekly_target": WEEKLY_CEILING,
        "project_weekly_share": WEEKLY_CEILING,
        "reserve": 20,
        "daily_call_ceiling": 24,
        "background_daily_call_ceiling": DEEP_CALL_CEILING,
        "night_review_reserved_calls": 4,
        "account_used_percent": used,
        "quota_observed_at": quota.get("at"),
        "target_gap_percentage_points": None if used is None else max(0, WEEKLY_CEILING - used),
        "account_limit_reason": account_limit_reason(quota, now),
        "attribution": "Task tokens are measured when reported. Quota is account-wide, includes other sessions, and is not an exact project token budget. Targets are objectives, not evidence of consumption. Calls already in flight can cross a reported threshold.",
    }
