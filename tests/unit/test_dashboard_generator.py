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
        assert "News influence explorer" in html
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
