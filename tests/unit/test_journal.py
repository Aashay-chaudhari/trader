"""Tests for journal/report generation."""

import json
import tempfile
from pathlib import Path

from agent_trader.utils.journal import create_journal_entry


def test_create_journal_entry_uses_timestamped_report_names(monkeypatch):
    original_cwd = Path.cwd()
    with tempfile.TemporaryDirectory(dir=".") as temp_dir:
        monkeypatch.chdir(Path(temp_dir).resolve())

        path = create_journal_entry(
            run_id="20260321_170332",
            phase="monitor",
            research_results={
                "research": {
                    "overall_sentiment": "neutral",
                    "market_summary": "test summary",
                    "stocks": {},
                    "_meta": {
                        "provider_preference": "openai",
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                        "runtime": {"platform": "github_actions"},
                        "attempts": [
                            {
                                "provider": "openai",
                                "model": "gpt-4o-mini",
                                "status": "success",
                            }
                        ],
                    },
                }
            },
        )

        report_path = Path(path)
        assert report_path.name.endswith("_monitor_report.md")

        json_path = report_path.with_suffix(".json")
        assert json_path.name.endswith("_monitor_report.json")

        raw = json.loads(json_path.read_text(encoding="utf-8"))
        assert raw["research"]["research"]["_meta"]["provider"] == "openai"
        monkeypatch.chdir(original_cwd)
