"""Tests for the static dashboard generator."""

import json
import tempfile

from agent_trader.dashboard.generator import generate_dashboard


def test_generate_dashboard_writes_context_rich_bundle():
    with tempfile.TemporaryDirectory(dir=".") as temp_dir:
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

        assert "Decision board" in html
        assert "Strategist Arena" in html
        assert "News influence explorer" in html
        assert bundle["profiles"]["default"]["profile"]["id"] == "default"
        assert bundle["comparison"]["summary"][0]["profile"] == "default"
        assert bundle["context"]["prompt_sections"]["news_inputs"]["per_symbol"]["ABBV"]["news_headlines"][0]["title"] == (
            "AbbVie signs new antibody discovery deal"
        )
        assert bundle["reports"]["research"]["run_id"] == "20260321_175214"
        assert (docs_dir / "data" / "report_research.md").exists()
        assert (docs_dir / "data" / "report_monitor.md").exists()


def test_generate_dashboard_backfills_legacy_news_context():
    with tempfile.TemporaryDirectory(dir=".") as temp_dir:
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
    with tempfile.TemporaryDirectory(dir=".") as temp_dir:
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
