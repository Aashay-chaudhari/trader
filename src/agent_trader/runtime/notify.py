from __future__ import annotations

import httpx

from .store import utc_now


def notify(config, store, key, title, body, urgent=False):
    if store.get("notification:" + key):
        return True
    if not config.ntfy_topic:
        store.event("notification_failed", {"key": key, "reason": "Not configured"})
        return False
    # Topic is deliberately never included in published logs or exception strings.
    try:
        response = httpx.post(
            "https://ntfy.sh/" + config.ntfy_topic,
            content=(body + "\n" + config.dashboard_url).encode(),
            headers={
                "Title": title,
                "Priority": "high" if urgent else "default",
                "Tags": "warning" if urgent else "chart_with_upwards_trend",
            },
            timeout=15,
        )
        response.raise_for_status()
    except Exception as exc:
        store.event("notification_failed", {"key": key, "error_type": type(exc).__name__})
        return False
    store.set("notification:" + key, utc_now())
    store.event("notification_sent", {"key": key, "title": title})
    return True
