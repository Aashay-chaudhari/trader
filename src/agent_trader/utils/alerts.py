"""Push Notifications — sends alerts via ntfy.sh (free, no signup).

ntfy.sh is a free, open-source push notification service.
No account, no API key, no credit card. Just:
  1. Install the ntfy app on your phone (iOS/Android)
  2. Subscribe to your topic (e.g., "agent-trader-yourname")
  3. Set NTFY_TOPIC in your .env

That's it. You'll get push notifications on your phone.

Also supports optional Twilio SMS as a secondary channel.

Use cases:
  - Remind you to run morning research / evening reflection
  - Notify when trades execute
  - Daily P&L summary
  - Pipeline errors
"""

import logging
from datetime import datetime, timezone

import httpx

from agent_trader.config.settings import get_settings

logger = logging.getLogger(__name__)

# ── ntfy.sh (primary, free) ──────────────────────────────────


def send_notification(body: str, title: str = "Agent Trader", priority: str = "default",
                      tags: str = "") -> dict:
    """Send a push notification via ntfy.sh.

    Falls back to Twilio SMS if ntfy is not configured but Twilio is.
    """
    settings = get_settings()

    # Try ntfy.sh first (free, preferred)
    if settings.ntfy_topic:
        return _send_ntfy(body, title, priority, tags)

    # Fall back to Twilio SMS if configured
    if settings.twilio_account_sid and settings.alert_phone_number:
        return _send_twilio_sms(f"{title}\n{body}")

    logger.warning("No notification channel configured (set NTFY_TOPIC or Twilio keys)")
    return {"status": "skipped", "reason": "no notification channel configured"}


def _send_ntfy(body: str, title: str, priority: str, tags: str) -> dict:
    """Send via ntfy.sh — free push notifications, no account needed."""
    settings = get_settings()
    url = f"{settings.ntfy_server}/{settings.ntfy_topic}"
    headers = {
        "Title": title,
        "Priority": priority,
    }
    if tags:
        headers["Tags"] = tags

    try:
        resp = httpx.post(url, content=body[:4096], headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        logger.info("ntfy sent: id=%s", data.get("id", "?"))
        return {"status": "ok", "provider": "ntfy", "id": data.get("id")}
    except Exception as e:
        logger.error("ntfy failed: %s", e)
        return {"status": "error", "provider": "ntfy", "error": str(e)}


def _send_twilio_sms(body: str) -> dict:
    """Send via Twilio SMS (optional paid fallback)."""
    try:
        from twilio.rest import Client
    except ImportError:
        return {"status": "error", "provider": "twilio",
                "error": "twilio not installed — run: pip install twilio"}

    settings = get_settings()
    try:
        client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        message = client.messages.create(
            body=body[:1600],
            from_=settings.twilio_from_number,
            to=settings.alert_phone_number,
        )
        return {"status": message.status, "provider": "twilio", "sid": message.sid}
    except Exception as e:
        return {"status": "error", "provider": "twilio", "error": str(e)}


# ── Alert helpers ─────────────────────────────────────────────


def alert_reminder(phase: str) -> dict:
    """Send a reminder to run a specific phase."""
    now = datetime.now(timezone.utc).strftime("%H:%M UTC")
    configs = {
        "morning": {
            "body": "Time for morning research!\ncd agent-trader && ./scripts/run_both.sh morning",
            "title": f"Agent Trader — Morning [{now}]",
            "tags": "sunrise,chart_with_upwards_trend",
            "priority": "high",
        },
        "evening": {
            "body": "Market closed — time for evening reflection.\n"
                    "cd agent-trader && ./scripts/run_both.sh evening",
            "title": f"Agent Trader — Evening [{now}]",
            "tags": "sunset,brain",
            "priority": "default",
        },
        "weekly": {
            "body": "Weekly review time!\ncd agent-trader && ./scripts/run_both.sh weekly",
            "title": f"Agent Trader — Weekly [{now}]",
            "tags": "calendar,mag",
            "priority": "default",
        },
        "monthly": {
            "body": "Monthly retrospective due.\ncd agent-trader && ./scripts/run_both.sh monthly",
            "title": f"Agent Trader — Monthly [{now}]",
            "tags": "trophy,books",
            "priority": "high",
        },
    }
    cfg = configs.get(phase, {"body": f"Time to run '{phase}' phase",
                              "title": "Agent Trader", "tags": "", "priority": "default"})
    return send_notification(**cfg)


def alert_trade_executed(trades: list[dict]) -> dict:
    """Notify when trades execute."""
    if not trades:
        return {"status": "skipped", "reason": "no trades"}
    lines = []
    for t in trades[:5]:
        symbol = t.get("symbol", "?")
        action = t.get("action", "?").upper()
        qty = t.get("quantity", 0)
        price = t.get("price", 0)
        lines.append(f"{action} {qty} {symbol} @ ${price:.2f}")
    if len(trades) > 5:
        lines.append(f"... and {len(trades) - 5} more")
    return send_notification(
        body="\n".join(lines),
        title=f"Agent Trader — {len(trades)} Trade(s)",
        tags="money_with_wings",
        priority="high",
    )


def alert_daily_summary(portfolio: dict) -> dict:
    """Send end-of-day P&L summary."""
    value = portfolio.get("portfolio_value", 0)
    pnl = portfolio.get("total_pnl", 0)
    pnl_pct = portfolio.get("total_pnl_pct", 0)
    positions = portfolio.get("position_count", 0)
    sign = "+" if pnl >= 0 else ""
    tag = "chart_with_upwards_trend" if pnl >= 0 else "chart_with_downwards_trend"
    return send_notification(
        body=(f"Portfolio: ${value:,.0f}\n"
              f"P&L: {sign}${pnl:,.2f} ({sign}{pnl_pct:.2f}%)\n"
              f"Positions: {positions}"),
        title="Agent Trader — Daily Summary",
        tags=tag,
    )


def alert_error(phase: str, error: str) -> dict:
    """Notify on pipeline error."""
    return send_notification(
        body=error[:1000],
        title=f"Agent Trader ERROR — {phase}",
        tags="warning,rotating_light",
        priority="urgent",
    )
