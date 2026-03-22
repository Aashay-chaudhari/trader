"""Knowledge Base — accumulated learnings that make the agent smarter over time.

Manages three layers of knowledge:
  1. Observations (daily/weekly/monthly) — what the agent noticed and reflected on
  2. Knowledge files (patterns, strategies, regimes, lessons) — distilled insights
  3. Context assembly — token-budgeted summaries for injection into research prompts

The key principle: raw JSON is never dumped into prompts. Everything is pre-summarized
into natural language within a strict token budget.
"""

from __future__ import annotations

import gzip
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class KnowledgeBase:
    """Persistent knowledge store for a single strategist profile."""

    def __init__(self, data_dir: str = "data"):
        self.root = Path(data_dir)
        self.obs_dir = self.root / "observations"
        self.daily_dir = self.obs_dir / "daily"
        self.weekly_dir = self.obs_dir / "weekly"
        self.monthly_dir = self.obs_dir / "monthly"
        self.archive_dir = self.obs_dir / "archive"
        self.knowledge_dir = self.root / "knowledge"

        # Ensure all directories exist
        for d in [self.daily_dir, self.weekly_dir, self.monthly_dir,
                  self.archive_dir, self.knowledge_dir]:
            d.mkdir(parents=True, exist_ok=True)

    # ── Daily Observations ─────────────────────────────────────────────

    def save_daily_observation(self, observation: dict) -> Path:
        """Save a daily observation from the evening reflection phase.

        Args:
            observation: Dict with date, market_regime, trades_review,
                        patterns_detected, confidence_calibration, etc.

        Returns:
            Path to the saved file.
        """
        date = observation.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        path = self.daily_dir / f"obs_{date}.json"
        _atomic_write_json(path, observation)
        logger.info("Saved daily observation: %s", path.name)
        return path

    def get_recent_observations(self, days: int = 7) -> list[dict]:
        """Load the most recent N daily observations, newest first."""
        files = sorted(self.daily_dir.glob("obs_*.json"), reverse=True)
        results = []
        for f in files[:days]:
            try:
                results.append(json.loads(f.read_text()))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Skipping corrupt observation %s: %s", f.name, exc)
        return results

    # ── Weekly Reviews ─────────────────────────────────────────────────

    def save_weekly_review(self, review: dict) -> Path:
        """Save a weekly consolidation review."""
        week_start = review.get("week_start",
                                datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        path = self.weekly_dir / f"week_{week_start}.json"
        _atomic_write_json(path, review)
        logger.info("Saved weekly review: %s", path.name)

        # Apply knowledge updates from the review
        updates = review.get("knowledge_updates", {})
        if updates.get("new_patterns"):
            self.update_patterns_library(updates["new_patterns"])
        if updates.get("new_lessons"):
            self.update_lessons_learned(updates["new_lessons"])
        if updates.get("updated_strategies"):
            strat_data = review.get("strategy_effectiveness", {})
            if strat_data:
                self.update_strategy_effectiveness(strat_data)
        if updates.get("regime_rules_updated"):
            regime_data = review.get("regime_analysis", {})
            if regime_data:
                self.update_regime_library_from_review(regime_data)

        return path

    def get_latest_weekly_review(self) -> dict | None:
        """Load the most recent weekly review."""
        files = sorted(self.weekly_dir.glob("week_*.json"), reverse=True)
        if not files:
            return None
        try:
            return json.loads(files[0].read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def get_recent_weekly_reviews(self, count: int = 4) -> list[dict]:
        """Load the most recent N weekly reviews."""
        files = sorted(self.weekly_dir.glob("week_*.json"), reverse=True)
        results = []
        for f in files[:count]:
            try:
                results.append(json.loads(f.read_text()))
            except (json.JSONDecodeError, OSError):
                pass
        return results

    # ── Monthly Reviews ────────────────────────────────────────────────

    def save_monthly_review(self, review: dict) -> Path:
        """Save a monthly retrospective."""
        month = review.get("month", datetime.now(timezone.utc).strftime("%Y-%m"))
        path = self.monthly_dir / f"month_{month}.json"
        _atomic_write_json(path, review)
        logger.info("Saved monthly review: %s", path.name)

        # Update lessons from monthly review
        top_lessons = review.get("top_lessons", [])
        if top_lessons:
            self.update_lessons_learned(top_lessons)

        return path

    def get_latest_monthly_review(self) -> dict | None:
        """Load the most recent monthly review."""
        files = sorted(self.monthly_dir.glob("month_*.json"), reverse=True)
        if not files:
            return None
        try:
            return json.loads(files[0].read_text())
        except (json.JSONDecodeError, OSError):
            return None

    # ── Knowledge Files ────────────────────────────────────────────────

    def update_patterns_library(self, new_patterns: list[dict]) -> None:
        """Merge new patterns into the patterns library.

        Each pattern has: name, description, occurrences, win_rate, etc.
        Existing patterns with the same name get their stats updated.
        Max 100 entries (oldest/least effective removed).
        """
        lib_path = self.knowledge_dir / "patterns_library.json"
        existing = _load_json(lib_path, {"patterns": [], "last_updated": ""})
        patterns = {p["name"]: p for p in existing.get("patterns", [])}

        for p in new_patterns:
            name = p.get("name", "")
            if not name:
                continue
            if name in patterns:
                # Merge: update stats
                old = patterns[name]
                old_occ = old.get("total_occurrences", old.get("occurrences", 0))
                new_occ = p.get("occurrences", 1)
                total = old_occ + new_occ
                # Weighted average win rate
                old_wr = old.get("win_rate", 0.5)
                new_wr = p.get("win_rate", 0.5)
                if total > 0:
                    merged_wr = (old_wr * old_occ + new_wr * new_occ) / total
                else:
                    merged_wr = new_wr
                old["total_occurrences"] = total
                old["win_rate"] = round(merged_wr, 3)
                old["last_seen"] = p.get("last_seen",
                                         datetime.now(timezone.utc).strftime("%Y-%m-%d"))
                # Update symbols seen
                old_symbols = set(old.get("symbols_seen", []))
                old_symbols.update(p.get("symbols_seen", []))
                old["symbols_seen"] = sorted(old_symbols)[:20]  # cap at 20
                if p.get("notes"):
                    old["notes"] = p["notes"]
                if p.get("best_regime"):
                    old["best_regime"] = p["best_regime"]
            else:
                # New pattern
                p.setdefault("total_occurrences", p.get("occurrences", 1))
                p.setdefault("first_seen",
                             datetime.now(timezone.utc).strftime("%Y-%m-%d"))
                p.setdefault("last_seen",
                             datetime.now(timezone.utc).strftime("%Y-%m-%d"))
                patterns[name] = p

        # Keep top 100 by recency + effectiveness
        all_patterns = list(patterns.values())
        all_patterns.sort(
            key=lambda x: (x.get("last_seen", ""), x.get("win_rate", 0)),
            reverse=True,
        )
        existing["patterns"] = all_patterns[:100]
        existing["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        _atomic_write_json(lib_path, existing)

    def update_strategy_effectiveness(self, data: dict) -> None:
        """Overwrite strategy effectiveness with latest weekly data."""
        path = self.knowledge_dir / "strategy_effectiveness.json"
        data["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        _atomic_write_json(path, data)

    def update_regime_library(self, regimes: dict) -> None:
        """Overwrite the regime library with updated rules."""
        path = self.knowledge_dir / "regime_library.json"
        data = {"regimes": regimes,
                "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%d")}
        _atomic_write_json(path, data)

    def update_regime_library_from_review(self, regime_analysis: dict) -> None:
        """Update regime library based on weekly review regime analysis."""
        path = self.knowledge_dir / "regime_library.json"
        existing = _load_json(path, {"regimes": {}, "last_updated": ""})
        dominant = regime_analysis.get("dominant", "")
        if dominant and dominant in existing.get("regimes", {}):
            # Update the dominant regime's notes
            existing["regimes"][dominant]["last_observed"] = (
                datetime.now(timezone.utc).strftime("%Y-%m-%d")
            )
        existing["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        _atomic_write_json(path, existing)

    def update_lessons_learned(self, new_lessons: list[str]) -> None:
        """Append new lessons, keeping the most recent 50."""
        path = self.knowledge_dir / "lessons_learned.json"
        existing = _load_json(path, {"lessons": [], "last_updated": ""})
        lessons = existing.get("lessons", [])

        # Deduplicate: don't add if very similar lesson exists
        for lesson in new_lessons:
            normalized = lesson.strip().lower()
            if not any(normalized == existing_lesson.strip().lower() for existing_lesson in lessons):
                lessons.append(lesson.strip())

        existing["lessons"] = lessons[-50:]  # keep last 50
        existing["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        _atomic_write_json(path, existing)

    # ── Context Assembly (Token-Budgeted) ──────────────────────────────

    def build_knowledge_context(
        self,
        token_budget: int = 1500,
        watchlist: list[str] | None = None,
        current_regime: str = "",
    ) -> str:
        """Build a pre-summarized knowledge context string for the research prompt.

        Returns natural language, not JSON. Fits within the token budget.
        ~4 chars ≈ 1 token (rough estimate for English text).
        """
        char_budget = token_budget * 4
        sections: list[str] = []
        used = 0

        # Count trading days
        obs_count = len(list(self.daily_dir.glob("obs_*.json")))
        trades_count = self._count_total_trades()
        header = f"ACCUMULATED KNOWLEDGE ({obs_count} trading days, {trades_count} trades):"
        sections.append(header)
        used += len(header)

        # 1. Lessons learned (~200 tokens = 800 chars)
        lessons_budget = min(800, char_budget // 5)
        lessons_text = self._summarize_lessons(lessons_budget)
        if lessons_text:
            sections.append(lessons_text)
            used += len(lessons_text)

        # 2. Current regime rules (~150 tokens = 600 chars)
        if current_regime:
            regime_budget = min(600, char_budget // 6)
            regime_text = self._summarize_regime_rules(current_regime, regime_budget)
            if regime_text:
                sections.append(regime_text)
                used += len(regime_text)

        # 3. Strategy effectiveness (~200 tokens = 800 chars)
        strat_budget = min(800, char_budget // 5)
        strat_text = self._summarize_strategies(strat_budget)
        if strat_text:
            sections.append(strat_text)
            used += len(strat_text)

        # 4. Recent patterns (~400 tokens = 1600 chars)
        remaining = char_budget - used
        patterns_budget = min(1600, remaining // 2)
        patterns_text = self._summarize_patterns(patterns_budget, watchlist)
        if patterns_text:
            sections.append(patterns_text)
            used += len(patterns_text)

        # 5. Forward thesis from latest weekly (~250 tokens = 1000 chars)
        remaining = char_budget - used
        if remaining > 400:
            thesis_text = self._summarize_thesis(min(1000, remaining))
            if thesis_text:
                sections.append(thesis_text)

        return "\n".join(sections) if len(sections) > 1 else ""

    def build_observations_context(self, token_budget: int = 500) -> str:
        """Build a compressed summary of recent daily observations.

        Returns natural language summary of last 3-5 days.
        """
        char_budget = token_budget * 4
        observations = self.get_recent_observations(days=5)
        if not observations:
            return ""

        lines = ["RECENT DAILY OBSERVATIONS:"]
        used = len(lines[0])

        for obs in observations[:5]:
            date = obs.get("date", "?")
            regime = obs.get("market_regime", "?")
            summary = obs.get("market_summary", "")
            # Truncate summary to fit
            max_summary = min(len(summary), (char_budget - used) // 3)
            summary = summary[:max_summary]

            lessons = obs.get("lessons", [])
            lesson_str = "; ".join(lessons[:2]) if lessons else ""

            line = f"  {date} ({regime}): {summary}"
            if lesson_str:
                line += f" | Learned: {lesson_str}"

            if used + len(line) > char_budget:
                break
            lines.append(line)
            used += len(line)

        # Add weekly thesis if room
        weekly = self.get_latest_weekly_review()
        if weekly and used < char_budget - 200:
            thesis = weekly.get("forward_thesis", {})
            outlook = thesis.get("outlook", "")
            if outlook:
                line = f"  WEEKLY THESIS: {outlook[:200]}"
                lines.append(line)

        return "\n".join(lines) if len(lines) > 1 else ""

    # ── Archival ───────────────────────────────────────────────────────

    def archive_old_observations(self, keep_days: int = 90) -> int:
        """Compress daily observations older than keep_days into quarterly archives.

        Returns the number of files archived.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
        cutoff_str = cutoff.strftime("%Y-%m-%d")
        archived = 0

        # Group old files by quarter
        quarters: dict[str, list[Path]] = {}
        for f in sorted(self.daily_dir.glob("obs_*.json")):
            date_str = f.stem.replace("obs_", "")
            if date_str >= cutoff_str:
                continue  # Keep recent files

            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                continue

            quarter = f"{dt.year}-Q{(dt.month - 1) // 3 + 1}"
            quarters.setdefault(quarter, []).append(f)

        for quarter, files in quarters.items():
            archive_path = self.archive_dir / f"{quarter}_daily.json.gz"
            # Load all observations for this quarter
            observations = []
            for f in files:
                try:
                    observations.append(json.loads(f.read_text()))
                except (json.JSONDecodeError, OSError):
                    pass

            # Write compressed archive
            data = json.dumps(observations, indent=1).encode("utf-8")
            with gzip.open(archive_path, "wb") as gz:
                gz.write(data)

            # Remove originals
            for f in files:
                f.unlink()
                archived += 1

            logger.info("Archived %d observations to %s", len(files), archive_path.name)

        return archived

    # ── Private Helpers ────────────────────────────────────────────────

    def _count_total_trades(self) -> int:
        """Count total trades from feedback file."""
        trades_file = self.root / "feedback" / "completed_trades.json"
        if not trades_file.exists():
            return 0
        try:
            return len(json.loads(trades_file.read_text()))
        except (json.JSONDecodeError, OSError):
            return 0

    def _summarize_lessons(self, char_budget: int) -> str:
        """Summarize lessons_learned.json into compact text."""
        path = self.knowledge_dir / "lessons_learned.json"
        data = _load_json(path, {"lessons": []})
        lessons = data.get("lessons", [])
        if not lessons:
            return ""

        lines = ["LESSONS:"]
        used = len(lines[0])
        for i, lesson in enumerate(lessons[-10:], 1):  # Last 10
            entry = f" ({i}) {lesson}"
            if used + len(entry) > char_budget:
                break
            lines.append(entry)
            used += len(entry)

        return "".join(lines) if len(lines) > 1 else ""

    def _summarize_regime_rules(self, regime: str, char_budget: int) -> str:
        """Summarize rules for the current market regime."""
        path = self.knowledge_dir / "regime_library.json"
        data = _load_json(path, {"regimes": {}})
        regimes = data.get("regimes", {})
        info = regimes.get(regime)
        if not info:
            return ""

        preferred = ", ".join(info.get("preferred_strategies", []))
        avoid = ", ".join(info.get("avoid_strategies", []))
        rules = "; ".join(info.get("rules", []))

        text = f"CURRENT REGIME RULES ({regime}): Prefer {preferred}."
        if avoid:
            text += f" Avoid {avoid}."
        if rules:
            remaining = char_budget - len(text)
            text += f" {rules[:remaining]}"

        return text[:char_budget]

    def _summarize_strategies(self, char_budget: int) -> str:
        """Summarize strategy effectiveness into compact text."""
        path = self.knowledge_dir / "strategy_effectiveness.json"
        data = _load_json(path, {})
        if not data or "last_updated" not in data:
            return ""

        # Collect strategy entries (skip metadata keys)
        strategies = []
        for k, v in data.items():
            if k in ("last_updated",) or not isinstance(v, dict):
                continue
            wr = v.get("win_rate", 0)
            best = v.get("best_regime", "")
            strategies.append((k, wr, best))

        if not strategies:
            return ""

        strategies.sort(key=lambda x: x[1], reverse=True)
        parts = [f"{name} {wr:.0%} win (best: {best})"
                 for name, wr, best in strategies[:5]]

        text = "TOP STRATEGIES: " + ", ".join(parts)
        return text[:char_budget]

    def _summarize_patterns(self, char_budget: int,
                            watchlist: list[str] | None = None) -> str:
        """Summarize patterns library, prioritizing today's watchlist."""
        path = self.knowledge_dir / "patterns_library.json"
        data = _load_json(path, {"patterns": []})
        patterns = data.get("patterns", [])
        if not patterns:
            return ""

        # Prioritize patterns involving watchlist stocks
        watchlist_set = set(watchlist or [])

        def relevance(p: dict) -> tuple:
            symbols = set(p.get("symbols_seen", []))
            has_watchlist = bool(symbols & watchlist_set)
            return (has_watchlist, p.get("last_seen", ""), p.get("win_rate", 0))

        patterns.sort(key=relevance, reverse=True)

        lines = ["RECENT PATTERNS:"]
        used = len(lines[0])
        for p in patterns[:10]:
            name = p.get("name", "?")
            wr = p.get("win_rate", 0)
            occ = p.get("total_occurrences", p.get("occurrences", 0))
            entry = f" {name} {wr:.0%} win ({occ} occ)"
            if used + len(entry) > char_budget:
                break
            lines.append(entry)
            used += len(entry)

        return "".join(lines) if len(lines) > 1 else ""

    def _summarize_thesis(self, char_budget: int) -> str:
        """Extract forward thesis from latest weekly review."""
        weekly = self.get_latest_weekly_review()
        if not weekly:
            return ""

        thesis = weekly.get("forward_thesis", {})
        outlook = thesis.get("outlook", "")
        confidence = thesis.get("confidence", 0)
        risks = ", ".join(thesis.get("key_risks", [])[:3])

        if not outlook:
            return ""

        text = f"FORWARD THESIS (conf {confidence:.0%}): {outlook}"
        if risks:
            text += f" Risks: {risks}"

        return text[:char_budget]


# ── Module-level Helpers ───────────────────────────────────────────────

def _atomic_write_json(path: Path, data: Any) -> None:
    """Write JSON atomically: write to .tmp, then rename."""
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2, default=str))
        tmp.replace(path)
    except OSError:
        # Fallback: direct write
        path.write_text(json.dumps(data, indent=2, default=str))


def _load_json(path: Path, default: Any = None) -> Any:
    """Load JSON from path, returning default on failure."""
    if not path.exists():
        return default if default is not None else {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return default if default is not None else {}
