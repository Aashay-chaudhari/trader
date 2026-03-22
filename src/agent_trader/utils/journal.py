"""Trade Journal — creates readable markdown logs of every trading decision.

Every pipeline run produces a journal entry under the active profile root,
for example `data/profiles/claude/journal/`.
These are committed to git by GitHub Actions, so you can browse them
on GitHub like a trading diary.

Each entry includes:
  - Date and time
  - Screener results (what stocks were picked and why)
  - Research insights (Claude's analysis)
  - Signals generated (which strategies fired)
  - Risk decisions (what was approved/rejected and why)
  - Trades executed (or dry-run simulated)
  - Portfolio snapshot

This gives you a complete audit trail of every decision the system made.
"""

import json
from pathlib import Path
from datetime import datetime, timezone

from agent_trader.config.settings import get_settings
from agent_trader.utils.profiles import build_profile_metadata


def create_journal_entry(
    run_id: str,
    phase: str,
    screener_results: dict | None = None,
    research_results: dict | None = None,
    signals: list | None = None,
    risk_results: dict | None = None,
    executed: list | None = None,
    portfolio_snapshot: dict | None = None,
    market_data: dict | None = None,
    data_dir: str | None = None,
    profile: dict | None = None,
) -> str:
    """Generate a markdown journal entry and save it to disk.

    Returns the file path of the saved entry.
    """
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M UTC")
    time_slug = now.strftime("%H-%M-%SZ")
    settings = get_settings()
    resolved_data_dir = data_dir or settings.data_dir
    profile_meta = profile or build_profile_metadata(settings)

    lines = [
        f"# Trading Journal — {date_str}",
        "",
        f"**Run ID:** `{run_id}`  ",
        f"**Phase:** {phase}  ",
        f"**Strategist:** {profile_meta.get('label', profile_meta.get('id', 'Unknown'))}  ",
        f"**Time:** {time_str}  ",
        "",
    ]

    # ── Screener Section ─────────────────────────────────────────
    if screener_results:
        shortlist = screener_results.get("shortlist", [])
        lines.append("## Screener Results")
        lines.append("")
        lines.append(f"Scanned {screener_results.get('total_scanned', 0)} stocks, "
                     f"found {screener_results.get('candidates_found', 0)} candidates, "
                     f"selected top {len(shortlist)}.")
        lines.append("")

        if shortlist:
            lines.append("| Symbol | Price | Change | Volume | Vol Ratio | Score |")
            lines.append("|--------|------:|-------:|-------:|----------:|------:|")
            for s in shortlist:
                lines.append(
                    f"| **{s['symbol']}** "
                    f"| ${s['price']:.2f} "
                    f"| {s['change_pct']:+.2f}% "
                    f"| {s['volume']:,} "
                    f"| {s['volume_ratio']:.1f}x "
                    f"| {s['score']:.3f} |"
                )
            lines.append("")

    # ── Research Section ─────────────────────────────────────────
    if research_results:
        lines.append("## Research Analysis")
        lines.append("")
        research = research_results.get("research", {})
        lines.append(f"**Overall Sentiment:** {research.get('overall_sentiment', 'N/A')}")
        lines.append("")

        summary = research.get("market_summary", "")
        if summary:
            lines.append(f"> {summary}")
            lines.append("")

        stocks = research.get("stocks", {})
        for symbol, analysis in stocks.items():
            sentiment = analysis.get("sentiment", "N/A")
            confidence = analysis.get("confidence", 0)
            rec = analysis.get("recommendation", "N/A")
            emoji = {"bullish": "+", "bearish": "-", "neutral": "~"}.get(sentiment, "?")

            lines.append(f"### {symbol} [{emoji}]")
            lines.append(f"- **Sentiment:** {sentiment} | **Confidence:** {confidence:.0%} | **Recommendation:** {rec}")

            observations = analysis.get("key_observations", [])
            if observations:
                lines.append("- **Observations:**")
                for obs in observations:
                    lines.append(f"  - {obs}")

            catalysts = analysis.get("catalysts", [])
            if catalysts:
                lines.append(f"- **Catalysts:** {', '.join(catalysts)}")

            risks = analysis.get("risks", [])
            if risks:
                lines.append(f"- **Risks:** {', '.join(risks)}")

            lines.append("")

        llm_meta = research.get("_meta", {})
        if llm_meta:
            lines.append("## LLM Telemetry")
            lines.append("")
            lines.append(
                f"- **Platform:** {llm_meta.get('runtime', {}).get('platform', 'unknown')}"
            )
            lines.append(
                f"- **Provider Preference:** {llm_meta.get('provider_preference', 'auto')}"
            )
            lines.append(f"- **Selected Provider:** {llm_meta.get('provider', 'unknown')}")
            lines.append(f"- **Selected Model:** {llm_meta.get('model', 'unknown')}")

            usage = llm_meta.get("usage", {})
            if usage:
                lines.append(
                    "- **Token Usage:** "
                    f"input={usage.get('input_tokens', 0)}, "
                    f"output={usage.get('output_tokens', 0)}, "
                    f"total={usage.get('total_tokens', 0)}"
                )

            estimates = llm_meta.get("rate_limits", {}).get("estimates", {})
            before_tokens = (
                estimates.get("tokens_remaining_before_request_estimate")
                or estimates.get("input_tokens_remaining_before_request_estimate")
            )
            if before_tokens is not None:
                lines.append(
                    "- **Capacity Before First Request (estimate):** "
                    f"{before_tokens:,} tokens remaining"
                )

            if llm_meta.get("request_id"):
                lines.append(f"- **Request ID:** `{llm_meta['request_id']}`")
            if llm_meta.get("duration_ms") is not None:
                lines.append(f"- **LLM Latency:** {llm_meta['duration_ms']} ms")
            if llm_meta.get("quota_note"):
                lines.append(f"- **Quota Note:** {llm_meta['quota_note']}")

            attempts = llm_meta.get("attempts", [])
            if attempts:
                lines.append("")
                lines.append("### Provider Attempts")
                lines.append("")
                for attempt in attempts:
                    pieces = [
                        attempt.get("provider", "?"),
                        attempt.get("model", "?"),
                        attempt.get("status", "?"),
                    ]
                    if attempt.get("duration_ms") is not None:
                        pieces.append(f"{attempt['duration_ms']} ms")
                    if attempt.get("error"):
                        pieces.append(str(attempt["error"])[:180])
                    lines.append(f"- {' | '.join(pieces)}")
                lines.append("")

        news_by_symbol = research_results.get("news", {})
        market_headlines = research_results.get("market_headlines", [])
        if news_by_symbol or market_headlines:
            lines.append("## News Inputs Seen By The LLM")
            lines.append("")

            if market_headlines:
                lines.append("### Market Headlines")
                lines.append("")
                for headline in market_headlines[:5]:
                    title = headline.get("title", "Untitled")
                    source = headline.get("publisher") or headline.get("source") or "unknown"
                    lines.append(f"- **{title}** [{source}]")
                lines.append("")

            for symbol, summary in news_by_symbol.items():
                headlines = summary.get("news_headlines", [])
                if not headlines:
                    continue
                lines.append(f"### {symbol} Headlines")
                lines.append("")
                for headline in headlines[:4]:
                    title = headline.get("title", "Untitled")
                    source = headline.get("publisher") or headline.get("source") or "unknown"
                    lines.append(f"- **{title}** [{source}]")
                lines.append("")

    # ── Signals Section ──────────────────────────────────────────
    if signals:
        lines.append("## Trade Signals")
        lines.append("")
        lines.append("| Symbol | Action | Strength | Strategy | Reasoning |")
        lines.append("|--------|--------|----------|----------|-----------|")
        for sig in signals:
            lines.append(
                f"| **{sig['symbol']}** "
                f"| {sig['action'].upper()} "
                f"| {sig['strength']:.2f} "
                f"| {sig['strategy']} "
                f"| {sig['reasoning'][:80]} |"
            )
        lines.append("")
    else:
        lines.append("## Trade Signals")
        lines.append("")
        lines.append("*No signals generated this run.*")
        lines.append("")

    # ── Risk Decisions ───────────────────────────────────────────
    if risk_results:
        approved = risk_results.get("approved_trades", [])
        rejected = risk_results.get("rejected_trades", [])

        lines.append("## Risk Assessment")
        lines.append("")
        lines.append(f"- **Approved:** {len(approved)} trades")
        lines.append(f"- **Rejected:** {len(rejected)} trades")
        lines.append("")

        if rejected:
            lines.append("### Rejected Trades")
            lines.append("")
            for r in rejected:
                reasons = ", ".join(r.get("rejection_reasons", ["unknown"]))
                lines.append(f"- **{r['symbol']}** ({r['action']}): {reasons}")
            lines.append("")

    # ── Execution Section ────────────────────────────────────────
    if executed:
        lines.append("## Execution")
        lines.append("")
        for trade in executed:
            status = trade.get("status", "unknown")
            status_label = {
                "dry_run": "DRY RUN",
                "submitted": "SUBMITTED",
                "failed": "FAILED",
            }.get(status, status.upper())

            lines.append(
                f"- **{trade.get('symbol')}** {trade.get('action', '').upper()} "
                f"{trade.get('quantity', 0)} shares @ ~${trade.get('estimated_price', 0):.2f} "
                f"= ${trade.get('estimated_value', 0):,.2f} "
                f"[{status_label}]"
            )
            if trade.get("reason"):
                lines.append(f"  - _{trade['reason']}_")
        lines.append("")
    else:
        lines.append("## Execution")
        lines.append("")
        lines.append("*No trades executed.*")
        lines.append("")

    # ── Portfolio Snapshot ────────────────────────────────────────
    if portfolio_snapshot:
        lines.append("## Portfolio Snapshot")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|------:|")
        lines.append(f"| **Total Value** | ${portfolio_snapshot.get('portfolio_value', 0):,.2f} |")
        lines.append(f"| **Cash** | ${portfolio_snapshot.get('cash', 0):,.2f} |")
        lines.append(f"| **Invested** | ${portfolio_snapshot.get('invested', 0):,.2f} |")
        lines.append(f"| **Total P&L** | ${portfolio_snapshot.get('total_pnl', 0):+,.2f} ({portfolio_snapshot.get('total_pnl_pct', 0):+.2f}%) |")
        lines.append(f"| **Positions** | {portfolio_snapshot.get('position_count', 0)} |")
        lines.append("")

        positions = portfolio_snapshot.get("positions", [])
        if positions:
            lines.append("### Open Positions")
            lines.append("")
            lines.append("| Symbol | Shares | Avg Cost | Current | Value | P&L |")
            lines.append("|--------|-------:|---------:|--------:|------:|----:|")
            for p in positions:
                pnl_sign = "+" if p["unrealized_pnl"] >= 0 else ""
                lines.append(
                    f"| {p['symbol']} "
                    f"| {p['shares']} "
                    f"| ${p['avg_cost']:.2f} "
                    f"| ${p['current_price']:.2f} "
                    f"| ${p['current_value']:,.2f} "
                    f"| {pnl_sign}${p['unrealized_pnl']:,.2f} ({pnl_sign}{p['unrealized_pnl_pct']:.2f}%) |"
                )
            lines.append("")

    lines.append("---")
    lines.append("*Generated by Agent Trader v0.1.0*")

    content = "\n".join(lines)

    # Save to journal directory
    journal_dir = Path(resolved_data_dir) / "journal" / date_str
    journal_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{time_slug}_{phase}_report.md"
    filepath = journal_dir / filename
    filepath.write_text(content, encoding="utf-8")

    # Also save raw data as JSON for programmatic access
    raw_data = {
        "run_id": run_id,
        "phase": phase,
        "profile": profile_meta,
        "timestamp": now.isoformat(),
        "screener": screener_results,
        "research": research_results,
        "market_data": market_data,
        "signals": signals,
        "risk": risk_results,
        "executed": executed,
        "portfolio": portfolio_snapshot,
    }
    json_path = journal_dir / f"{time_slug}_{phase}_report.json"
    json_path.write_text(json.dumps(raw_data, indent=2, default=str), encoding="utf-8")

    return str(filepath)
