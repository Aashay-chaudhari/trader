"""Tests for the static dashboard generator."""

import json
import tempfile

from agent_trader.dashboard.generator import generate_dashboard
from agent_trader.utils.research_context import save_prompt_context_snapshot


def test_generate_dashboard_writes_context_rich_bundle():
    with tempfile.TemporaryDirectory(dir=".", ignore_cleanup_errors=True) as temp_dir:
        from pathlib import Path

        root = Path(temp_dir).resolve()
        data_dir = root / "data"
        docs_dir = root / "docs"

        (data_dir / "snapshots").mkdir(parents=True)
        (data_dir / "research").mkdir(parents=True)
        (data_dir / "analytics").mkdir(parents=True)
        (data_dir / "context").mkdir(parents=True)
        (data_dir / "journal" / "2026-03-21").mkdir(parents=True)

        (data_dir / "snapshots" / "latest.json").write_text(
            json.dumps(
                {
                    "timestamp": "2026-03-21T17:53:18Z",
                    "portfolio_value": 100000.0,
                    "cash": 95000.0,
                    "invested": 5000.0,
                    "total_pnl": 0.0,
                    "total_pnl_pct": 0.0,
                    "positions": [],
                    "position_count": 0,
                }
            ),
            encoding="utf-8",
        )
        (data_dir / "snapshots" / "history.json").write_text(
            json.dumps([{"timestamp": "2026-03-21T17:53:18Z", "portfolio_value": 100000.0}]),
            encoding="utf-8",
        )
        (data_dir / "research" / "2026-03-21_research_1753.json").write_text(
            json.dumps(
                {
                    "overall_sentiment": "neutral",
                    "market_summary": "Risk-off tape with a few oversold setups.",
                    "best_opportunities": ["ABBV"],
                    "stocks": {
                        "ABBV": {
                            "sentiment": "bullish",
                            "confidence": 0.7,
                            "recommendation": "buy",
                            "key_observations": ["Oversold with RSI under 30."],
                            "catalysts": ["Immunology deal sentiment"],
                            "risks": ["Market continues lower"],
                            "trade_plan": {"entry": 205.0, "stop_loss": 195.0, "target": 225.0},
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        (data_dir / "analytics" / "latest_llm.json").write_text(
            json.dumps(
                {
                    "selected_provider": "openai",
                    "selected_model": "gpt-4o-mini",
                    "usage": {"input_tokens": 100, "output_tokens": 40, "total_tokens": 140},
                }
            ),
            encoding="utf-8",
        )
        (data_dir / "context" / "latest_research.json").write_text(
            json.dumps(
                {
                    "phase": "research",
                    "provider": "openai",
                    "model": "gpt-4o-mini",
                    "symbols": ["ABBV"],
                    "prompt_sections": {
                        "artifact_context": "RECENT SAVED RESEARCH ARTIFACTS:\\n- prior run",
                        "market_context": {"market_regime": "risk_off"},
                        "screener_context": {
                            "shortlist": [
                                {
                                    "symbol": "ABBV",
                                    "source": "news+technical",
                                    "score": 0.7,
                                    "discovery_reason": "Strong bullish news sentiment",
                                }
                            ]
                        },
                        "news_inputs": {
                            "per_symbol": {
                                "ABBV": {
                                    "news_headlines": [
                                        {
                                            "title": "AbbVie signs new antibody discovery deal",
                                            "publisher": "Simply Wall St.",
                                            "published": "2026-03-21T16:00:00Z",
                                            "summary": "Deal expands the immunology pipeline.",
                                            "url": "https://example.com/abbv",
                                            "sentiment": 1.0,
                                        }
                                    ]
                                }
                            },
                            "market_headlines": [
                                {
                                    "title": "Markets fade into the close",
                                    "source": "yfinance:SPY",
                                    "summary": "Broad risk-off move.",
                                }
                            ],
                            "news_discoveries": [
                                {
                                    "symbol": "ABBV",
                                    "discovery_reason": "Strong bullish news sentiment",
                                }
                            ],
                            "hot_stocks": [],
                            "finviz": {"analyst_changes": []},
                        },
                    },
                }
            ),
            encoding="utf-8",
        )
        (data_dir / "journal" / "2026-03-21" / "17-53-18Z_research_report.json").write_text(
            json.dumps({"run_id": "20260321_175214", "phase": "research"}),
            encoding="utf-8",
        )
        (data_dir / "journal" / "2026-03-21" / "17-53-18Z_research_report.md").write_text(
            "# Research report",
            encoding="utf-8",
        )
        (data_dir / "journal" / "2026-03-21" / "17-53-18Z_monitor_report.md").write_text(
            "# Monitor report",
            encoding="utf-8",
        )

        generate_dashboard(data_dir=str(data_dir), docs_dir=str(docs_dir))

        html = (docs_dir / "index.html").read_text(encoding="utf-8")
        bundle = json.loads((docs_dir / "data" / "dashboard.json").read_text(encoding="utf-8"))

        assert "Today's Decisions" in html
        assert "Strategist Comparison" in html
        assert "Market Intelligence" in html
        assert "foldout" in html
        assert "Actions" in html
        assert bundle["profiles"]["default"]["profile"]["id"] == "default"
        assert bundle["comparison"]["summary"][0]["profile"] == "default"
        assert bundle["context"]["prompt_sections"]["news_inputs"]["per_symbol"]["ABBV"]["news_headlines"][0]["title"] == (
            "AbbVie signs new antibody discovery deal"
        )
        assert bundle["reports"]["research"]["run_id"] == "20260321_175214"
        assert (docs_dir / "data" / "report_research.md").exists()
        assert (docs_dir / "data" / "report_monitor.md").exists()


def test_generate_dashboard_backfills_legacy_news_context():
    with tempfile.TemporaryDirectory(dir=".", ignore_cleanup_errors=True) as temp_dir:
        from pathlib import Path

        root = Path(temp_dir).resolve()
        data_dir = root / "data"
        docs_dir = root / "docs"

        (data_dir / "snapshots").mkdir(parents=True)
        (data_dir / "research").mkdir(parents=True)
        (data_dir / "analytics").mkdir(parents=True)
        (data_dir / "context").mkdir(parents=True)
        (data_dir / "journal" / "2026-03-21").mkdir(parents=True)

        (data_dir / "snapshots" / "latest.json").write_text(
            json.dumps({"timestamp": "2026-03-21T17:53:18Z", "positions": [], "position_count": 0}),
            encoding="utf-8",
        )
        (data_dir / "snapshots" / "history.json").write_text(json.dumps([]), encoding="utf-8")
        (data_dir / "research" / "2026-03-21_research_1753.json").write_text(
            json.dumps({"stocks": {}, "best_opportunities": []}),
            encoding="utf-8",
        )
        (data_dir / "analytics" / "latest_llm.json").write_text(json.dumps({}), encoding="utf-8")
        (data_dir / "context" / "latest_research.json").write_text(
            json.dumps(
                {
                    "phase": "research",
                    "provider": "openai",
                    "model": "gpt-4o-mini",
                    "symbols": ["ABBV"],
                    "prompt_sections": {
                        "news_context": (
                            "PER-STOCK NEWS:\n\n"
                            "ABBV (sentiment: bullish, score: +0.50):\n"
                            "  - [Simply Wall St.] AbbVie signs antibody discovery deal [+1.0]\n\n"
                            "NEWS-DRIVEN DISCOVERIES (stocks in the news today):\n"
                            "  ABBV: bullish sentiment (+0.60), price -0.6%\n"
                            "    Headline: AbbVie signs antibody discovery deal\n"
                            "    Why: strong bullish news sentiment\n"
                        )
                    },
                }
            ),
            encoding="utf-8",
        )
        (data_dir / "journal" / "2026-03-21" / "17-53-18Z_research_report.json").write_text(
            json.dumps({"run_id": "20260321_175214", "phase": "research"}),
            encoding="utf-8",
        )

        generate_dashboard(data_dir=str(data_dir), docs_dir=str(docs_dir))

        bundle = json.loads((docs_dir / "data" / "dashboard.json").read_text(encoding="utf-8"))
        news_inputs = bundle["context"]["prompt_sections"]["news_inputs"]

        assert news_inputs["per_symbol"]["ABBV"]["news_headlines"][0]["title"] == (
            "AbbVie signs antibody discovery deal"
        )
        assert news_inputs["news_discoveries"][0]["symbol"] == "ABBV"


def test_generate_dashboard_merges_multiple_profiles():
    with tempfile.TemporaryDirectory(dir=".", ignore_cleanup_errors=True) as temp_dir:
        from pathlib import Path

        root = Path(temp_dir).resolve()
        data_dir = root / "data"
        docs_dir = root / "docs"

        for profile_id, label, provider, portfolio_value in (
            ("claude", "Claude Strategist", "anthropic", 101250.0),
            ("codex", "Codex Strategist", "openai", 100400.0),
        ):
            profile_root = data_dir / "profiles" / profile_id
            (profile_root / "snapshots").mkdir(parents=True)
            (profile_root / "research").mkdir(parents=True)
            (profile_root / "analytics").mkdir(parents=True)
            (profile_root / "context").mkdir(parents=True)
            (profile_root / "journal" / "2026-03-21").mkdir(parents=True)

            (profile_root / "profile.json").write_text(
                json.dumps({"id": profile_id, "label": label}),
                encoding="utf-8",
            )
            (profile_root / "snapshots" / "latest.json").write_text(
                json.dumps(
                    {
                        "timestamp": f"2026-03-21T1{8 if profile_id == 'claude' else 7}:00:00Z",
                        "profile": profile_id,
                        "profile_label": label,
                        "portfolio_value": portfolio_value,
                        "cash": 90000.0,
                        "invested": 10000.0,
                        "total_pnl": portfolio_value - 100000.0,
                        "total_pnl_pct": round((portfolio_value - 100000.0) / 1000, 2),
                        "positions": [],
                        "position_count": 0,
                    }
                ),
                encoding="utf-8",
            )
            (profile_root / "snapshots" / "history.json").write_text(
                json.dumps(
                    [
                        {
                            "timestamp": "2026-03-21T16:00:00Z",
                            "portfolio_value": 100000.0,
                        },
                        {
                            "timestamp": f"2026-03-21T1{8 if profile_id == 'claude' else 7}:00:00Z",
                            "portfolio_value": portfolio_value,
                        },
                    ]
                ),
                encoding="utf-8",
            )
            (profile_root / "research" / f"2026-03-21_{profile_id}.json").write_text(
                json.dumps(
                    {
                        "market_summary": f"{label} summary",
                        "best_opportunities": ["ABBV" if profile_id == "claude" else "MSFT"],
                        "stocks": {},
                    }
                ),
                encoding="utf-8",
            )
            (profile_root / "analytics" / "latest_llm.json").write_text(
                json.dumps({"selected_provider": provider, "selected_model": f"{provider}-model"}),
                encoding="utf-8",
            )
            (profile_root / "context" / "latest_research.json").write_text(
                json.dumps({"prompt_sections": {"news_inputs": {"per_symbol": {}}}}),
                encoding="utf-8",
            )
            (profile_root / "journal" / "2026-03-21" / f"{profile_id}_research_report.json").write_text(
                json.dumps({"run_id": f"{profile_id}-run", "phase": "research"}),
                encoding="utf-8",
            )
            (profile_root / "journal" / "2026-03-21" / f"{profile_id}_research_report.md").write_text(
                f"# {label} report",
                encoding="utf-8",
            )

        generate_dashboard(data_dir=str(data_dir), docs_dir=str(docs_dir))

        bundle = json.loads((docs_dir / "data" / "dashboard.json").read_text(encoding="utf-8"))
        claude_bundle = json.loads(
            (docs_dir / "data" / "profiles" / "claude" / "dashboard.json").read_text(encoding="utf-8")
        )
        codex_bundle = json.loads(
            (docs_dir / "data" / "profiles" / "codex" / "dashboard.json").read_text(encoding="utf-8")
        )

        assert set(bundle["profiles"]) == {"claude", "codex"}
        assert bundle["active_profile"] == "claude"
        assert bundle["comparison"]["leaders"]["portfolio_value"] == "claude"
        assert {item["profile"] for item in bundle["comparison"]["summary"]} == {"claude", "codex"}
        assert claude_bundle["profile"]["label"] == "Claude Strategist"
        assert codex_bundle["profile"]["label"] == "Codex Strategist"
        assert (docs_dir / "data" / "profiles" / "claude" / "report_research.md").exists()
        assert (docs_dir / "data" / "profiles" / "codex" / "report_research.md").exists()


def test_generate_dashboard_preserves_linkable_evidence():
    with tempfile.TemporaryDirectory(dir=".", ignore_cleanup_errors=True) as temp_dir:
        from pathlib import Path

        root = Path(temp_dir).resolve()
        data_dir = root / "data"
        docs_dir = root / "docs"

        (data_dir / "snapshots").mkdir(parents=True)
        (data_dir / "research").mkdir(parents=True)
        (data_dir / "analytics").mkdir(parents=True)
        (data_dir / "context").mkdir(parents=True)
        (data_dir / "journal" / "2026-03-21").mkdir(parents=True)

        (data_dir / "snapshots" / "latest.json").write_text(
            json.dumps({"timestamp": "2026-03-21T17:53:18Z", "positions": [], "position_count": 0}),
            encoding="utf-8",
        )
        (data_dir / "snapshots" / "history.json").write_text(json.dumps([]), encoding="utf-8")
        (data_dir / "research" / "2026-03-21_research_1753.json").write_text(
            json.dumps(
                {
                    "best_opportunities": ["ABBV"],
                    "stocks": {
                        "ABBV": {
                            "recommendation": "buy",
                            "catalysts": ["Pipeline deal remains a positive driver"],
                            "risks": ["Broader market weakness could cap upside"],
                            "supporting_articles": [
                                {
                                    "title": "AbbVie signs new antibody discovery deal",
                                    "url": "https://example.com/abbv-deal",
                                    "source": "ExampleWire",
                                    "reason": "Confirms the catalyst behind the setup",
                                }
                            ],
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        (data_dir / "analytics" / "latest_llm.json").write_text(json.dumps({}), encoding="utf-8")
        (data_dir / "context" / "latest_research.json").write_text(
            json.dumps(
                {
                    "prompt_sections": {
                        "news_inputs": {
                            "per_symbol": {
                                "ABBV": {
                                    "news_headlines": [
                                        {
                                            "title": "AbbVie signs new antibody discovery deal",
                                            "publisher": "ExampleWire",
                                            "url": "https://example.com/abbv-deal",
                                        }
                                    ]
                                }
                            },
                            "market_headlines": [],
                            "news_discoveries": [
                                {
                                    "symbol": "ABBV",
                                    "top_headline": "AbbVie signs new antibody discovery deal",
                                    "top_headline_url": "https://example.com/abbv-deal",
                                }
                            ],
                            "hot_stocks": [
                                {
                                    "symbol": "ABBV",
                                    "sentiment": "bullish",
                                    "source_count": 2,
                                    "reasons": ["ExampleWire: AbbVie signs new antibody discovery deal"],
                                    "articles": [
                                        {
                                            "title": "AbbVie signs new antibody discovery deal",
                                            "source": "ExampleWire",
                                            "url": "https://example.com/abbv-deal",
                                        }
                                    ],
                                }
                            ],
                            "finviz": {"analyst_changes": []},
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        (data_dir / "journal" / "2026-03-21" / "17-53-18Z_research_report.json").write_text(
            json.dumps({"run_id": "20260321_175214", "phase": "research"}),
            encoding="utf-8",
        )

        generate_dashboard(data_dir=str(data_dir), docs_dir=str(docs_dir))

        html = (docs_dir / "index.html").read_text(encoding="utf-8")
        bundle = json.loads((docs_dir / "data" / "dashboard.json").read_text(encoding="utf-8"))

        assert "trade-row" in html
        assert "Trade History" in html
        assert bundle["profiles"]["default"]["research"]["stocks"]["ABBV"]["supporting_articles"][0]["url"] == (
            "https://example.com/abbv-deal"
        )
        assert (
            bundle["context"]["prompt_sections"]["news_inputs"]["news_discoveries"][0]["top_headline_url"]
            == "https://example.com/abbv-deal"
        )


def test_generate_dashboard_includes_knowledge_store_bundle():
    with tempfile.TemporaryDirectory(dir=".", ignore_cleanup_errors=True) as temp_dir:
        from pathlib import Path

        root = Path(temp_dir).resolve()
        data_dir = root / "data"
        docs_dir = root / "docs"

        (data_dir / "snapshots").mkdir(parents=True)
        (data_dir / "research").mkdir(parents=True)
        (data_dir / "analytics").mkdir(parents=True)
        (data_dir / "context").mkdir(parents=True)
        (data_dir / "journal" / "2026-03-21").mkdir(parents=True)
        (data_dir / "observations" / "daily").mkdir(parents=True)
        (data_dir / "observations" / "weekly").mkdir(parents=True)
        (data_dir / "observations" / "monthly").mkdir(parents=True)
        (data_dir / "knowledge").mkdir(parents=True)

        (data_dir / "snapshots" / "latest.json").write_text(
            json.dumps({"timestamp": "2026-03-21T23:00:00Z", "positions": [], "position_count": 0}),
            encoding="utf-8",
        )
        (data_dir / "snapshots" / "history.json").write_text(json.dumps([]), encoding="utf-8")
        (data_dir / "research" / "2026-03-21_research_2300.json").write_text(
            json.dumps({"best_opportunities": ["NVDA"], "stocks": {}}),
            encoding="utf-8",
        )
        (data_dir / "analytics" / "latest_llm.json").write_text(json.dumps({}), encoding="utf-8")
        (data_dir / "context" / "latest_research.json").write_text(
            json.dumps({"prompt_sections": {"news_inputs": {"per_symbol": {}}}}),
            encoding="utf-8",
        )
        (data_dir / "journal" / "2026-03-21" / "23-00-00Z_research_report.json").write_text(
            json.dumps({"run_id": "20260321_230000", "phase": "research"}),
            encoding="utf-8",
        )
        (data_dir / "observations" / "daily" / "obs_2026-03-21.json").write_text(
            json.dumps(
                {
                    "date": "2026-03-21",
                    "market_regime": "risk_on",
                    "market_summary": "Tech leadership remained intact.",
                    "lessons": ["Momentum still favored clean breakouts."],
                }
            ),
            encoding="utf-8",
        )
        (data_dir / "observations" / "weekly" / "week_2026-03-17.json").write_text(
            json.dumps(
                {
                    "week_start": "2026-03-17",
                    "summary": {"trades_count": 8, "win_rate": 0.75},
                    "regime_analysis": {"dominant": "risk_on"},
                    "forward_thesis": {
                        "outlook": "Leadership remains concentrated in large-cap tech.",
                        "confidence": 0.7,
                        "key_risks": ["Rate volatility"],
                    },
                }
            ),
            encoding="utf-8",
        )
        (data_dir / "observations" / "monthly" / "month_2026-03.json").write_text(
            json.dumps({"month": "2026-03", "vs_last_month": {"improvement_areas": "Sharpen exits"}}),
            encoding="utf-8",
        )
        (data_dir / "knowledge" / "lessons_learned.json").write_text(
            json.dumps({"lessons": ["Trend strength matters more than valuation on squeeze days."]}),
            encoding="utf-8",
        )
        (data_dir / "knowledge" / "patterns_library.json").write_text(
            json.dumps(
                {
                    "patterns": [
                        {
                            "name": "gap_and_go",
                            "description": "Gap continuation on strong volume.",
                            "win_rate": 0.71,
                            "total_occurrences": 14,
                            "best_regime": "risk_on",
                            "symbols_seen": ["NVDA", "TSLA"],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        (data_dir / "knowledge" / "strategy_effectiveness.json").write_text(
            json.dumps({"momentum": {"win_rate": 0.8, "avg_return": 1.2, "best_regime": "risk_on"}}),
            encoding="utf-8",
        )
        (data_dir / "knowledge" / "regime_library.json").write_text(
            json.dumps(
                {
                    "regimes": {
                        "risk_on": {
                            "preferred_strategies": ["momentum"],
                            "avoid_strategies": ["mean_reversion"],
                            "rules": ["Favor continuation over dip buying."],
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        (data_dir / "improvement_proposals.json").write_text(
            json.dumps(
                [
                    {
                        "date": "2026-03-21",
                        "proposals": [
                            {
                                "priority": "high",
                                "category": "data",
                                "title": "Add earnings surprise context",
                                "description": "Capture post-earnings drift more explicitly.",
                            }
                        ],
                    }
                ]
            ),
            encoding="utf-8",
        )

        generate_dashboard(data_dir=str(data_dir), docs_dir=str(docs_dir))

        html = (docs_dir / "index.html").read_text(encoding="utf-8")
        bundle = json.loads((docs_dir / "data" / "dashboard.json").read_text(encoding="utf-8"))
        knowledge = bundle["profiles"]["default"]["knowledge"]

        assert "System Intelligence" in html
        assert "kbTabs" in html
        assert knowledge["counts"]["daily_observations"] == 1
        assert knowledge["counts"]["patterns"] == 1
        assert knowledge["latest_weekly_review"]["week_start"] == "2026-03-17"
        assert knowledge["patterns"][0]["name"] == "gap_and_go"
        assert knowledge["proposals"][0]["title"] == "Add earnings surprise context"
        assert (docs_dir / "data" / "knowledge.json").exists()


def test_generate_dashboard_exports_interaction_logs():
    with tempfile.TemporaryDirectory(dir=".", ignore_cleanup_errors=True) as temp_dir:
        from pathlib import Path

        root = Path(temp_dir).resolve()
        data_dir = root / "data"
        docs_dir = root / "docs"

        (data_dir / "profiles" / "claude" / "snapshots").mkdir(parents=True)
        (data_dir / "profiles" / "claude" / "research").mkdir(parents=True)
        (data_dir / "profiles" / "claude" / "analytics").mkdir(parents=True)
        (data_dir / "profiles" / "claude" / "context").mkdir(parents=True)
        interaction_dir = data_dir / "profiles" / "claude" / "interactions" / "2026-03-22"
        interaction_dir.mkdir(parents=True)

        profile_root = data_dir / "profiles" / "claude"
        (profile_root / "profile.json").write_text(
            json.dumps({"id": "claude", "label": "Claude Strategist"}),
            encoding="utf-8",
        )
        (profile_root / "snapshots" / "latest.json").write_text(
            json.dumps({"timestamp": "2026-03-22T13:30:00Z", "positions": [], "position_count": 0}),
            encoding="utf-8",
        )
        (profile_root / "snapshots" / "history.json").write_text(json.dumps([]), encoding="utf-8")
        (profile_root / "research" / "2026-03-22_research.json").write_text(
            json.dumps({"best_opportunities": [], "stocks": {}}),
            encoding="utf-8",
        )
        (profile_root / "analytics" / "latest_llm.json").write_text(json.dumps({}), encoding="utf-8")
        (profile_root / "context" / "latest_research.json").write_text(
            json.dumps({"prompt_sections": {"news_inputs": {"per_symbol": {}}}}),
            encoding="utf-8",
        )

        prompt_path = interaction_dir / "083000_morning_prompt.md"
        transcript_path = interaction_dir / "083000_morning_transcript.txt"
        metadata_path = interaction_dir / "083000_morning_interaction.json"

        prompt_path.write_text("# Morning prompt", encoding="utf-8")
        transcript_path.write_text("Research started\nTop thesis line", encoding="utf-8")
        metadata_path.write_text(
            json.dumps(
                {
                    "timestamp": "2026-03-22T08:30:00-04:00",
                    "profile": "claude",
                    "phase": "morning",
                    "tool": "claude",
                    "status": "success",
                    "prompt_source": "scripts/prompts/morning_research.md",
                    "prompt_file": "data/profiles/claude/interactions/2026-03-22/083000_morning_prompt.md",
                    "transcript_file": "data/profiles/claude/interactions/2026-03-22/083000_morning_transcript.txt",
                    "raw_log_file": ".tmp/cli_logs/claude_morning_2026-03-22_083000.ndjson",
                    "summary": "Research started | Top thesis line",
                }
            ),
            encoding="utf-8",
        )
        (profile_root / "interactions" / "latest.json").write_text(metadata_path.read_text(encoding="utf-8"), encoding="utf-8")
        (profile_root / "interactions" / "latest_morning.json").write_text(
            metadata_path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )

        generate_dashboard(data_dir=str(data_dir), docs_dir=str(docs_dir))

        bundle = json.loads((docs_dir / "data" / "dashboard.json").read_text(encoding="utf-8"))
        interactions = bundle["profiles"]["claude"]["interactions"]

        assert interactions["counts"]["total"] == 1
        assert interactions["latest"]["phase"] == "morning"
        assert interactions["recent"][0]["prompt_url"] == (
            "data/profiles/claude/interactions/2026-03-22/083000_morning_prompt.md"
        )
        assert interactions["recent"][0]["transcript_url"] == (
            "data/profiles/claude/interactions/2026-03-22/083000_morning_transcript.txt"
        )
        assert (docs_dir / "data" / "profiles" / "claude" / "interactions.json").exists()
        assert (
            docs_dir
            / "data"
            / "profiles"
            / "claude"
            / "interactions"
            / "2026-03-22"
            / "083000_morning_prompt.md"
        ).exists()
        assert (
            docs_dir
            / "data"
            / "profiles"
            / "claude"
            / "interactions"
            / "2026-03-22"
            / "083000_morning_transcript.txt"
        ).exists()
        assert interactions["counts"]["days"] == 1
        assert interactions["days"][0]["date"] == "2026-03-22"
        assert interactions["days"][0]["phases"][0]["key"] == "morning"


def test_generate_dashboard_groups_automated_monitor_evaluations_by_day():
    with tempfile.TemporaryDirectory(dir=".", ignore_cleanup_errors=True) as temp_dir:
        from pathlib import Path

        root = Path(temp_dir).resolve()
        data_dir = root / "data"
        docs_dir = root / "docs"
        profile_root = data_dir / "profiles" / "claude"

        (profile_root / "snapshots").mkdir(parents=True)
        (profile_root / "research").mkdir(parents=True)
        (profile_root / "analytics").mkdir(parents=True)
        (profile_root / "context").mkdir(parents=True)

        (profile_root / "profile.json").write_text(
            json.dumps({"id": "claude", "label": "Claude Strategist"}),
            encoding="utf-8",
        )
        (profile_root / "snapshots" / "latest.json").write_text(
            json.dumps({"timestamp": "2026-03-22T15:00:00Z", "positions": [], "position_count": 0}),
            encoding="utf-8",
        )
        (profile_root / "snapshots" / "history.json").write_text(json.dumps([]), encoding="utf-8")
        (profile_root / "research" / "2026-03-22_monitor_1500.json").write_text(
            json.dumps(
                {
                    "market_summary": "XOM moved into the planned entry zone.",
                    "stocks": {"XOM": {"ready_to_trade": True, "monitor_reason": "Entry zone matched."}},
                }
            ),
            encoding="utf-8",
        )
        (profile_root / "analytics" / "latest_llm.json").write_text(
            json.dumps({"selected_provider": "openai", "selected_model": "gpt-4o-mini"}),
            encoding="utf-8",
        )
        (profile_root / "context" / "latest_research.json").write_text(
            json.dumps({"prompt_sections": {"news_inputs": {"per_symbol": {}}}}),
            encoding="utf-8",
        )

        save_prompt_context_snapshot(
            phase="monitor",
            provider="openai",
            model="gpt-4o-mini",
            symbols=["XOM"],
            prompt_sections={"candidate_symbols": ["XOM"]},
            llm_meta={
                "status": "success",
                "provider": "openai",
                "model": "gpt-4o-mini",
                "usage": {"total_tokens": 21},
            },
            prompt_text="Return JSON only. Check whether XOM still matches the morning plan.",
            prompt_source="src/agent_trader/agents/research_agent.py",
            tool="python-api",
            response_payload={
                "market_summary": "XOM moved into the planned entry zone.",
                "stocks": {
                    "XOM": {
                        "ready_to_trade": True,
                        "monitor_reason": "Entry zone matched.",
                        "recommendation": "buy",
                    }
                },
            },
            data_dir=str(profile_root),
        )

        generate_dashboard(data_dir=str(data_dir), docs_dir=str(docs_dir))

        bundle = json.loads((docs_dir / "data" / "dashboard.json").read_text(encoding="utf-8"))
        interactions = bundle["profiles"]["claude"]["interactions"]
        day = interactions["days"][0]
        monitor_group = next(section for section in day["phases"] if section["key"] == "monitor")
        item = monitor_group["items"][0]

        assert interactions["counts"]["days"] == 1
        assert day["date"] == item["day"]
        assert item["tool"] == "python-api"
        assert item["phase"] == "monitor"
        assert item["prompt_url"].endswith("_monitor_prompt.md")
        assert item["transcript_url"].endswith("_monitor_transcript.txt")
        assert (
            docs_dir
            / "data"
            / "profiles"
            / "claude"
            / "interactions"
            / day["date"]
            / Path(item["prompt_url"]).name
        ).exists()


def test_generate_dashboard_exports_strategist_voice_bundle():
    with tempfile.TemporaryDirectory(dir=".", ignore_cleanup_errors=True) as temp_dir:
        from pathlib import Path

        root = Path(temp_dir).resolve()
        data_dir = root / "data"
        docs_dir = root / "docs"

        profile_root = data_dir / "profiles" / "claude"
        (profile_root / "snapshots").mkdir(parents=True)
        (profile_root / "research").mkdir(parents=True)
        (profile_root / "analytics").mkdir(parents=True)
        (profile_root / "context").mkdir(parents=True)
        (profile_root / "voice").mkdir(parents=True)

        (profile_root / "profile.json").write_text(
            json.dumps({"id": "claude", "label": "Claude Strategist"}),
            encoding="utf-8",
        )
        (profile_root / "snapshots" / "latest.json").write_text(
            json.dumps({"timestamp": "2026-03-22T21:00:00Z", "positions": [], "position_count": 0}),
            encoding="utf-8",
        )
        (profile_root / "snapshots" / "history.json").write_text(json.dumps([]), encoding="utf-8")
        (profile_root / "research" / "2026-03-22_research.json").write_text(
            json.dumps({"best_opportunities": [], "stocks": {}}),
            encoding="utf-8",
        )
        (profile_root / "analytics" / "latest_llm.json").write_text(json.dumps({}), encoding="utf-8")
        (profile_root / "context" / "latest_research.json").write_text(
            json.dumps({"prompt_sections": {"news_inputs": {"per_symbol": {}}}}),
            encoding="utf-8",
        )

        voice_payload = {
            "date": "2026-03-22",
            "profile": "claude",
            "state": "building",
            "summary": "Process quality is improving, but trade evidence is still thin.",
            "since_last_time": ["First voice entry - no prior baseline yet."],
            "working_well": ["Morning research is producing clear trade plans."],
            "struggles": ["Not enough executed trades yet to trust confidence calibration."],
            "needs_from_operator": ["None"],
            "next_focus": "Watch whether tomorrow's entries respect the planned zones.",
            "confidence_score": 0.52,
        }
        (profile_root / "voice" / "voice_2026-03-22.json").write_text(
            json.dumps(voice_payload),
            encoding="utf-8",
        )
        (profile_root / "voice" / "latest_voice.json").write_text(
            json.dumps(voice_payload),
            encoding="utf-8",
        )

        generate_dashboard(data_dir=str(data_dir), docs_dir=str(docs_dir))

        html = (docs_dir / "index.html").read_text(encoding="utf-8")
        bundle = json.loads((docs_dir / "data" / "dashboard.json").read_text(encoding="utf-8"))
        voice = bundle["profiles"]["claude"]["voice"]

        assert "Strategist Voice" in html
        assert voice["counts"]["total"] == 1
        assert voice["latest"]["state"] == "building"
        assert voice["recent"][0]["json_url"] == "data/profiles/claude/voice/voice_2026-03-22.json"
        assert (docs_dir / "data" / "profiles" / "claude" / "voice.json").exists()
        assert (docs_dir / "data" / "profiles" / "claude" / "voice" / "latest_voice.json").exists()


def test_generate_dashboard_exports_evolution_bundle():
    with tempfile.TemporaryDirectory(dir=".", ignore_cleanup_errors=True) as temp_dir:
        from pathlib import Path

        root = Path(temp_dir).resolve()
        data_dir = root / "data"
        docs_dir = root / "docs"

        profile_root = data_dir / "profiles" / "claude"
        (profile_root / "snapshots").mkdir(parents=True)
        (profile_root / "research").mkdir(parents=True)
        (profile_root / "analytics").mkdir(parents=True)
        (profile_root / "context").mkdir(parents=True)

        (profile_root / "profile.json").write_text(
            json.dumps({"id": "claude", "label": "Claude Strategist"}),
            encoding="utf-8",
        )
        (profile_root / "snapshots" / "latest.json").write_text(
            json.dumps({"timestamp": "2026-03-22T21:00:00Z", "positions": [], "position_count": 0}),
            encoding="utf-8",
        )
        (profile_root / "snapshots" / "history.json").write_text(json.dumps([]), encoding="utf-8")
        (profile_root / "research" / "2026-03-22_research.json").write_text(
            json.dumps({"best_opportunities": [], "stocks": {}}),
            encoding="utf-8",
        )
        (profile_root / "analytics" / "latest_llm.json").write_text(json.dumps({}), encoding="utf-8")
        (profile_root / "context" / "latest_research.json").write_text(
            json.dumps({"prompt_sections": {"news_inputs": {"per_symbol": {}}}}),
            encoding="utf-8",
        )

        evolution_payload = {
            "date": "2026-03-22",
            "profile": "claude",
            "status": "focused_upgrade_window",
            "summary": "Execution conditions are usable, but the improvement queue needs tighter prioritization.",
            "top_priority": {
                "title": "Tighten execution-condition templates",
                "category": "prompt",
                "why_now": "The monitor gate is only as good as the morning plan quality.",
                "expected_impact": "Cleaner approval decisions and fewer ambiguous entries.",
            },
            "priority_queue": [
                {
                    "title": "Standardize execution conditions",
                    "category": "prompt",
                    "priority": "high",
                    "action_type": "implement_now",
                    "reason": "This affects every monitor decision.",
                }
            ],
        }
        (profile_root / "evolution_review.json").write_text(
            json.dumps(evolution_payload),
            encoding="utf-8",
        )
        (profile_root / "EVOLUTION_REPORT.md").write_text(
            "# Evolution Report - Claude Strategist\n\n## Top Priority\n\n- Tighten execution-condition templates\n",
            encoding="utf-8",
        )

        generate_dashboard(data_dir=str(data_dir), docs_dir=str(docs_dir))

        html = (docs_dir / "index.html").read_text(encoding="utf-8")
        bundle = json.loads((docs_dir / "data" / "dashboard.json").read_text(encoding="utf-8"))
        evolution = bundle["profiles"]["claude"]["evolution"]

        assert "Evolution Review" in html
        assert evolution["status"] == "focused_upgrade_window"
        assert evolution["top_priority"]["title"] == "Tighten execution-condition templates"
        assert evolution["report_url"] == "data/profiles/claude/EVOLUTION_REPORT.md"
        assert evolution["review_url"] == "data/profiles/claude/evolution_review.json"
        assert (docs_dir / "data" / "profiles" / "claude" / "evolution.json").exists()
        assert (docs_dir / "data" / "profiles" / "claude" / "EVOLUTION_REPORT.md").exists()


def test_generate_dashboard_ignores_default_profile_when_named_profiles_exist():
    with tempfile.TemporaryDirectory(dir=".", ignore_cleanup_errors=True) as temp_dir:
        from pathlib import Path

        root = Path(temp_dir).resolve()
        data_dir = root / "data"
        docs_dir = root / "docs"
        stale_default = docs_dir / "data" / "profiles" / "default"
        stale_default.mkdir(parents=True)
        (stale_default / "stale.txt").write_text("stale", encoding="utf-8")

        for profile_id in ("claude", "codex", "default"):
            profile_root = data_dir / "profiles" / profile_id
            (profile_root / "snapshots").mkdir(parents=True)
            (profile_root / "research").mkdir(parents=True)
            (profile_root / "analytics").mkdir(parents=True)
            (profile_root / "context").mkdir(parents=True)
            (profile_root / "snapshots" / "latest.json").write_text(
                json.dumps({"timestamp": "2026-03-22T13:30:00Z", "positions": [], "position_count": 0}),
                encoding="utf-8",
            )
            (profile_root / "snapshots" / "history.json").write_text(json.dumps([]), encoding="utf-8")
            (profile_root / "research" / f"{profile_id}_research.json").write_text(
                json.dumps({"best_opportunities": [], "stocks": {}}),
                encoding="utf-8",
            )
            (profile_root / "analytics" / "latest_llm.json").write_text(json.dumps({}), encoding="utf-8")
            (profile_root / "context" / "latest_research.json").write_text(
                json.dumps({"prompt_sections": {"news_inputs": {"per_symbol": {}}}}),
                encoding="utf-8",
            )
            (profile_root / "profile.json").write_text(
                json.dumps({"id": profile_id, "label": f"{profile_id.title()} Strategist"}),
                encoding="utf-8",
            )

        generate_dashboard(data_dir=str(data_dir), docs_dir=str(docs_dir))

        bundle = json.loads((docs_dir / "data" / "dashboard.json").read_text(encoding="utf-8"))

        assert set(bundle["profiles"]) == {"claude", "codex"}
        assert not (docs_dir / "data" / "profiles" / "default").exists()
