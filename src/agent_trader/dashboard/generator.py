"""Generate the static GitHub Pages dashboard and JSON bundles."""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from textwrap import dedent
from typing import Any

from agent_trader.utils.profiles import DEFAULT_PROFILE_LABELS

_TEMPLATE_PATH = Path(__file__).parent / "template.html"


def _load_dashboard_html() -> str:
    """Load the dashboard HTML template from file."""
    if _TEMPLATE_PATH.exists():
        return _TEMPLATE_PATH.read_text(encoding="utf-8")
    # Fallback: bare-bones page pointing to the data file
    return "<!doctype html><html><body><p>Dashboard template not found. Run the pipeline first.</p></body></html>\n"


# Keep DASHBOARD_HTML as a property-like callable for backward compat —
# generator.py writes it via _load_dashboard_html() in generate_dashboard().
DASHBOARD_HTML = dedent(
    """
    <!doctype html>
    <html lang="en">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width,initial-scale=1">
      <title>Agent Trader Control Center</title>
      <link rel="preconnect" href="https://fonts.googleapis.com">
      <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
      <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=Manrope:wght@400;500;600;700;800&display=swap" rel="stylesheet">
      <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
      <style>
        :root{--bg:#07111f;--panel:#0f1d35;--panel2:#132746;--line:rgba(126,166,235,.16);--text:#eef5ff;--muted:#95a7ca;--accent:#7dd3fc;--good:#86efac;--bad:#fda4af;--warn:#fcd34d}
        *{box-sizing:border-box}body{margin:0;color:var(--text);font-family:"Segoe UI",system-ui,sans-serif;background:radial-gradient(circle at top left,rgba(125,211,252,.14),transparent 30%),linear-gradient(180deg,#07111f,#091629 48%,#09111f)}a{color:inherit}
        .page{max-width:1460px;margin:0 auto;padding:24px 18px 40px}.hero,.panel,.card,.stage,.decision,.tile{border:1px solid var(--line);background:rgba(15,29,53,.92);box-shadow:0 16px 46px rgba(0,0,0,.25)}.hero{padding:26px;border-radius:28px;margin-bottom:18px;background:linear-gradient(135deg,rgba(20,40,69,.96),rgba(9,18,34,.96))}.panel{padding:20px;border-radius:22px;margin-bottom:18px}.card,.stage,.decision,.tile{padding:16px;border-radius:18px}
        h1{margin:10px 0;font-size:clamp(2rem,4vw,3.1rem);line-height:1.02}h2{margin:0;font-size:1.16rem}h3{margin:0 0 10px;font-size:1rem}p{margin:0;color:var(--muted);line-height:1.55}
        .pill{display:inline-flex;align-items:center;padding:6px 10px;border-radius:999px;border:1px solid rgba(125,211,252,.22);background:#0b1830;font-size:.75rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}.accent{color:var(--accent)}.good{color:var(--good)}.bad{color:var(--bad)}.warn{color:var(--warn)}
        .hero-grid,.metrics,.split,.workflow,.decisions,.newscols,.context,.meta,.buttons,.mini,.articles{display:grid;gap:14px}.hero-grid{grid-template-columns:1.45fr 1fr;align-items:end}.meta{grid-template-columns:repeat(auto-fit,minmax(140px,1fr));margin-top:16px}.buttons{grid-template-columns:repeat(auto-fit,minmax(170px,1fr))}
        .btn{display:flex;align-items:center;justify-content:center;padding:12px 14px;border-radius:999px;border:1px solid rgba(125,211,252,.28);background:#0b1830;text-decoration:none;font-weight:700;cursor:pointer;font:inherit;color:var(--text);appearance:none}.btn:hover{border-color:rgba(125,211,252,.48);transform:translateY(-1px)}.btn.active{border-color:rgba(134,239,172,.55);background:#123053;color:var(--text)}
        .metrics{grid-template-columns:repeat(auto-fit,minmax(170px,1fr));margin-bottom:18px}.label{font-size:.76rem;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin-bottom:8px}.value{font-size:1.7rem;font-weight:800}.sub{margin-top:6px;font-size:.85rem;color:var(--muted)}
        .section{display:flex;justify-content:space-between;gap:14px;align-items:flex-start;margin-bottom:16px}.split{grid-template-columns:1.1fr .9fr}.workflow{grid-template-columns:repeat(auto-fit,minmax(220px,1fr))}.decisions{grid-template-columns:repeat(auto-fit,minmax(460px,1fr))}.newscols,.context{grid-template-columns:1fr 1fr}.mini{grid-template-columns:repeat(auto-fit,minmax(120px,1fr))}
        .chart{height:300px}.stage,.decision{position:relative;background:linear-gradient(180deg,#12233f,#0b1730)}.top{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;margin-bottom:12px}.metric{font-size:1.15rem;font-weight:800;text-align:right;min-width:64px}
        .mini .tile{padding:12px;border-radius:14px;background:#0b1730;border:1px solid rgba(126,166,235,.14)}.tile strong{display:block;font-size:.74rem;letter-spacing:.07em;text-transform:uppercase;color:var(--muted);margin-bottom:6px}.tile span{font-weight:700;line-height:1.45}
        .list strong{display:block;margin:14px 0 8px;font-size:.77rem;letter-spacing:.07em;text-transform:uppercase;color:var(--muted)}.list ul{margin:0;padding-left:18px}.list li{margin-bottom:7px;line-height:1.45}
        .articles{grid-template-columns:repeat(auto-fit,minmax(210px,1fr));margin-top:10px}.article{position:relative}.article a,.article div.body{display:block;padding:12px;border-radius:16px;border:1px solid rgba(126,166,235,.14);background:#0b1730;text-decoration:none;min-height:122px}.article-title{font-weight:700;line-height:1.45;margin-bottom:10px}.article-meta{display:flex;flex-wrap:wrap;gap:8px;font-size:.8rem;color:var(--muted)}.article-copy{margin-top:10px;font-size:.9rem;color:var(--muted);line-height:1.5}
        .hover{display:none;position:absolute;left:0;right:0;top:calc(100% + 8px);z-index:20;padding:14px;border-radius:16px;border:1px solid rgba(125,211,252,.26);background:rgba(8,19,35,.98);box-shadow:0 18px 40px rgba(0,0,0,.36)}.hover strong{display:block;margin-bottom:8px;font-size:.78rem;letter-spacing:.08em;text-transform:uppercase;color:var(--accent)}.hover ul{margin:0;padding-left:18px}.hover li{margin-bottom:6px;line-height:1.45;color:var(--muted)}.stage:hover .hover,.stage:focus-within .hover,.article:hover .hover,.article:focus-within .hover{display:block}
        .stack{display:grid;gap:14px}.mono{margin:0;padding:14px;border-radius:16px;border:1px solid rgba(126,166,235,.12);background:#0b1730;white-space:pre-wrap;font-family:Consolas,monospace;color:var(--muted)}
        .table{overflow:auto}table{width:100%;border-collapse:collapse;font-size:.92rem}th{padding:10px 8px;text-align:left;font-size:.76rem;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);border-bottom:1px solid rgba(126,166,235,.16)}td{padding:12px 8px;border-bottom:1px solid rgba(126,166,235,.08);vertical-align:top}.empty{padding:22px 16px;border:1px dashed rgba(126,166,235,.16);border-radius:16px;color:var(--muted);text-align:center}
        .headline-list{max-height:340px;overflow-y:auto;margin-top:8px;padding-right:4px}.headline-row{display:flex;align-items:flex-start;gap:8px;padding:8px 10px;border-radius:10px;border:1px solid rgba(126,166,235,.08);background:#0a1628;margin-bottom:6px}.headline-row:hover{border-color:rgba(125,211,252,.28);background:#0d1c36}.hl-sent{flex-shrink:0;width:42px;height:24px;display:flex;align-items:center;justify-content:center;border-radius:6px;font-size:.72rem;font-weight:800}.hl-sent.pos{background:rgba(134,239,172,.14);color:var(--good)}.hl-sent.neg{background:rgba(253,164,175,.14);color:var(--bad)}.hl-sent.neu{background:rgba(252,211,77,.1);color:var(--warn)}.hl-body{flex:1;min-width:0}.hl-title{font-size:.85rem;font-weight:600;line-height:1.4;margin-bottom:2px}.hl-meta{font-size:.72rem;color:var(--muted)}.source-tag{display:inline-block;padding:2px 6px;border-radius:4px;font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.04em;background:rgba(125,211,252,.1);color:var(--accent);margin-right:4px}.source-breakdown{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}.src-chip{padding:4px 8px;border-radius:8px;font-size:.72rem;font-weight:600;border:1px solid rgba(126,166,235,.14);background:#0a1628}
        .foldout{padding:0;overflow:hidden}.foldout summary{list-style:none;display:flex;justify-content:space-between;align-items:center;gap:12px;padding:18px 20px;cursor:pointer;font-weight:700}.foldout summary::-webkit-details-marker{display:none}.foldout summary span{color:var(--muted);font-size:.84rem;font-weight:600}.foldout .foldout-body{padding:0 20px 20px}.link-row{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}.link-chip{display:inline-flex;align-items:center;gap:6px;padding:6px 10px;border-radius:999px;border:1px solid rgba(125,211,252,.22);background:#0b1830;font-size:.76rem;text-decoration:none;color:var(--accent)}.link-chip:hover{border-color:rgba(125,211,252,.45)}.reason-list{display:grid;gap:10px}.reason-item{padding:10px 12px;border-radius:14px;border:1px solid rgba(126,166,235,.12);background:#0b1730}.compact-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.compact-grid .card{height:100%}
        @media (max-width:1080px){.hero-grid,.split,.newscols,.context{grid-template-columns:1fr}}@media (max-width:760px){.page{padding:16px 12px 28px}.hero{padding:20px}}
        :root{--bg:#f4efe6;--panel:#fffdf8;--panel2:#f7f1e7;--line:rgba(44,70,67,.12);--text:#132321;--muted:#5e706b;--accent:#0f766e;--good:#1d7a47;--bad:#b14d4c;--warn:#9a6a00}
        body{font-family:"Manrope",system-ui,sans-serif;background:radial-gradient(circle at top left,rgba(15,118,110,.11),transparent 28%),linear-gradient(180deg,#f8f5ee,#f2ede3 52%,#ece6db);color:var(--text)}
        a{text-decoration:none}
        .topbar{position:sticky;top:0;z-index:40;padding:14px 18px 0}
        .topbar-inner{max-width:1460px;margin:0 auto;padding:12px 18px;border-radius:22px;border:1px solid var(--line);background:rgba(255,251,244,.9);backdrop-filter:blur(18px);box-shadow:0 12px 30px rgba(63,48,24,.07);display:flex;justify-content:space-between;align-items:center;gap:16px}
        .brand{display:flex;align-items:center;gap:12px;font-weight:800;color:var(--text)}
        .brand-mark{width:38px;height:38px;border-radius:14px;display:grid;place-items:center;background:linear-gradient(135deg,#0f766e,#2563eb);color:#fff;font-size:.78rem;letter-spacing:.1em;text-transform:uppercase}
        .brand-copy{display:grid;gap:2px}.brand-copy strong{font-size:.96rem}.brand-copy span{font-size:.8rem;color:var(--muted)}
        .nav-links{display:flex;flex-wrap:wrap;gap:8px}
        .tab-link{padding:10px 12px;border-radius:999px;color:var(--muted);font-weight:700;border:1px solid transparent;background:transparent;cursor:pointer;font:inherit}
        .tab-link:hover{background:rgba(15,118,110,.08);color:var(--text)}
        .tab-link.active{background:var(--accent);color:#fff;border-color:var(--accent)}
        .status-chip{display:inline-flex;align-items:center;justify-content:center;padding:10px 14px;border-radius:999px;border:1px solid rgba(15,118,110,.16);background:rgba(15,118,110,.08);color:var(--accent);font-weight:800;min-height:42px}
        .page{padding-top:18px}
        .content-pane{display:none}
        .content-pane.active{display:block}
        .hero,.panel,.card,.stage,.decision,.tile{background:rgba(255,252,247,.94);border:1px solid var(--line);box-shadow:0 16px 34px rgba(72,55,25,.06)}
        .hero{background:linear-gradient(135deg,rgba(255,252,247,.98),rgba(246,241,231,.98))}
        .card,.stage,.decision,.tile,.article a,.article div.body,.headline-row,.reason-item,.mono,.src-chip{background:#fbf7f0}
        .pill{background:#ecf8f6;border-color:rgba(15,118,110,.24);color:var(--accent)}
        .mini .tile{background:#fff;border-color:var(--line)}
        .btn{background:#fff;color:var(--text);border-color:rgba(44,70,67,.14);box-shadow:0 8px 20px rgba(72,55,25,.05)}
        .btn:hover{border-color:rgba(15,118,110,.28)}
        .btn.active{background:var(--accent);border-color:var(--accent);color:#fff}
        .hero-grid{align-items:start}.hero-actions{display:flex;flex-wrap:wrap;gap:10px;margin-top:18px}.hero-side{display:grid;gap:14px}.compact-meta{grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}
        .headline-value{font-size:1.6rem;font-weight:800;line-height:1.1}
        .mini .tile,.stage,.decision{box-shadow:none}
        .foldout{background:rgba(255,252,247,.95)}.foldout summary{padding:18px 22px}
        .mono{font-family:"IBM Plex Mono",monospace;color:var(--muted)}
        .link-chip{background:#fff;color:var(--accent);border-color:rgba(15,118,110,.16)}
        .link-chip:hover{border-color:rgba(15,118,110,.34)}
        .hover{background:#fffaf2;border:1px solid var(--line);box-shadow:0 14px 28px rgba(72,55,25,.12)}
        .decision summary{list-style:none;cursor:pointer}
        .decision summary::-webkit-details-marker{display:none}
        .decision summary .top{margin-bottom:0}
        .decision details{border:1px solid var(--line);border-radius:16px;background:#fbf7f0;padding:12px}
        .decision-body{margin-top:12px;display:grid;gap:12px}
        .knowledge-list,.proposal-list,.observation-list,.pattern-list,.regime-list{display:grid;gap:10px}
        .knowledge-item,.proposal-item,.observation-item,.pattern-item,.regime-item{padding:12px 14px;border-radius:16px;border:1px solid var(--line);background:#fbf7f0}
        .knowledge-item strong,.proposal-item strong,.observation-item strong,.pattern-item strong,.regime-item strong{display:block;margin-bottom:6px}
        .small-copy{font-size:.9rem;line-height:1.55;color:var(--muted)}
        .tag-row{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}.tag{display:inline-flex;align-items:center;padding:6px 10px;border-radius:999px;border:1px solid rgba(44,70,67,.12);background:#fff;font-size:.76rem;font-weight:700;color:var(--muted)}
        .subtle-table td,.subtle-table th{font-size:.86rem}
        @media (max-width:1080px){.topbar-inner{flex-direction:column;align-items:stretch}.status-chip{width:100%}}
        @media (max-width:760px){.topbar{padding:10px 12px 0}.nav-links{overflow:auto;flex-wrap:nowrap}.hero-actions .btn,.buttons .btn{min-height:46px}}
      </style>
    </head>
    <body>
      <nav class="topbar">
        <div class="topbar-inner">
          <a class="brand" href="#overview">
            <span class="brand-mark">AT</span>
            <span class="brand-copy">
              <strong>Agent Trader</strong>
              <span>Two strategist books, one calmer control surface</span>
            </span>
          </a>
          <div class="nav-links" id="sectionTabs">
            <button type="button" class="tab-link active" data-section="overview">Overview</button>
            <button type="button" class="tab-link" data-section="decisions">Decisions</button>
            <button type="button" class="tab-link" data-section="knowledge">Knowledge</button>
            <button type="button" class="tab-link" data-section="news">News</button>
            <button type="button" class="tab-link" data-section="activity">Activity</button>
          </div>
          <div class="status-chip" id="navStatus">Loading latest strategist...</div>
        </div>
      </nav>

      <div class="page">
        <div class="content-pane active" data-pane="overview">
        <header class="hero" id="overview">
          <div class="hero-grid">
            <div>
              <div class="pill accent">Agent Trader Control Center</div>
              <h1>See the story first, then dive as deep as you need.</h1>
              <p id="heroSummary">Latest research, workflow context, and article-level catalysts from the trading pipeline.</p>
              <div class="hero-actions">
              <a class="btn" id="runLink" href="data/report_research.md" target="_blank" rel="noreferrer">Open latest report</a>
              <a class="btn" id="resetLink" href="https://github.com/Aashay-chaudhari/trader/actions/workflows/trading.yml" target="_blank" rel="noreferrer">Reset project state</a>
              <a class="btn" id="researchLink" href="data/report_research.md" target="_blank" rel="noreferrer">Research markdown</a>
              <a class="btn" id="monitorLink" href="data/report_monitor.md" target="_blank" rel="noreferrer">Monitor markdown</a>
              <a class="btn" id="weeklyLink" href="data/report_weekly.json" target="_blank" rel="noreferrer">Weekly review</a>
              <a class="btn" id="monthlyLink" href="data/report_monthly.json" target="_blank" rel="noreferrer">Monthly review</a>
              </div>
            </div>
            <div class="hero-side">
              <div class="card">
                <div class="label">Active strategist</div>
                <div class="headline-value" id="heroProfile">-</div>
                <p id="heroSubline">Strategy context, source-linked evidence, and portfolio state.</p>
              </div>
              <div class="meta compact-meta" id="heroMeta"></div>
            </div>
          </div>
        </header>

        <details class="panel foldout">
          <summary><div><h2>Quick Access</h2><p>Raw files, architecture docs, and exported artifacts.</p></div><span>Expand</span></summary>
          <div class="foldout-body">
            <div class="buttons">
              <a class="btn" id="contextLink" href="data/context.json" target="_blank" rel="noreferrer">Prompt context JSON</a>
              <a class="btn" id="llmLink" href="data/llm.json" target="_blank" rel="noreferrer">LLM analytics JSON</a>
              <a class="btn" id="knowledgeLink" href="data/knowledge.json" target="_blank" rel="noreferrer">Knowledge bundle</a>
              <a class="btn" id="improvementLink" href="data/improvement_proposals.json" target="_blank" rel="noreferrer">Improvement backlog</a>
              <a class="btn" id="dashboardLink" href="data/dashboard.json" target="_blank" rel="noreferrer">Dashboard bundle</a>
              <a class="btn" href="ARCHITECTURE.md" target="_blank" rel="noreferrer">System architecture</a>
              <a class="btn" href="KNOWLEDGE_ARCHITECTURE.md" target="_blank" rel="noreferrer">Knowledge architecture</a>
            </div>
          </div>
        </details>

        <section class="panel" id="arena">
          <div class="section"><div><h2>Strategist Arena</h2><p>Toggle between the independent Claude and Codex books, then use the comparison board to see which one is compounding more effectively.</p></div></div>
          <div class="buttons" id="profileTabs"></div>
          <div class="mini" id="comparisonCards" style="margin-top:14px"></div>
          <div class="table" style="margin-top:14px"><table><thead><tr><th>Strategist</th><th>Portfolio</th><th>Total PnL</th><th>Trades</th><th>Win Rate</th><th>Provider</th><th>Model</th><th>Updated</th></tr></thead><tbody id="comparisonTable"></tbody></table></div>
        </section>

        <section class="metrics">
          <div class="card"><div class="label">Portfolio Value</div><div class="value" id="portfolioValue">-</div></div>
          <div class="card"><div class="label">Total PnL</div><div class="value" id="totalPnl">-</div><div class="sub" id="totalPnlPct">-</div></div>
          <div class="card"><div class="label">Cash Available</div><div class="value" id="cashValue">-</div></div>
          <div class="card"><div class="label">Open Positions</div><div class="value" id="positionCount">-</div></div>
          <div class="card"><div class="label">Trades Logged</div><div class="value" id="tradeCount">-</div></div>
          <div class="card"><div class="label">Prompt Articles</div><div class="value" id="articleCount">-</div><div class="sub" id="modeNote">Mode unknown</div></div>
        </section>

        <details class="panel foldout">
          <summary><div><h2>Workflow Snapshot</h2><p>Quick path from news intake to execution.</p></div><span>Expand</span></summary>
          <div class="foldout-body">
            <div class="workflow" id="workflow"></div>
            <div class="split" style="margin-top:14px">
              <div class="card">
                <div class="section"><div><h3>Portfolio Curve</h3><p>Snapshots across workflow runs.</p></div></div>
                <div class="chart"><canvas id="valueChart"></canvas></div>
              </div>
              <div class="card">
                <div class="section"><div><h3>Run Snapshot</h3><p>Provider, phases, and execution summary.</p></div></div>
                <div class="mini" id="runSummary"></div>
              </div>
            </div>
          </div>
        </details>
        </div>

        <div class="content-pane" data-pane="decisions">
        <section class="panel" id="decisions">
          <div class="section"><div><h2>Decision board</h2><p>Top setups first, with the rationale and linked evidence sitting right beside each trade idea.</p></div></div>
          <div class="decisions" id="decisionBoard"></div>
        </section>
        </div>

        <div class="content-pane" data-pane="knowledge">
        <section class="panel" id="knowledge">
          <div class="section"><div><h2>Knowledge Store</h2><p>The accumulated lessons, pattern edges, review summaries, and improvement ideas that feed back into future prompts.</p></div></div>
          <div class="compact-grid" style="margin-bottom:14px">
            <div class="card">
              <h3>Knowledge snapshot</h3>
              <div class="mini" id="knowledgeSummary"></div>
            </div>
            <div class="card">
              <h3>Prompt-ready memory</h3>
              <p id="knowledgeBlurb">No accumulated knowledge has been summarized yet.</p>
              <div class="link-row" id="knowledgeDocs"></div>
            </div>
          </div>
          <div class="split">
            <div class="stack">
              <div class="card"><h3>Recent observations</h3><div id="knowledgeObservations"></div></div>
              <div class="card"><h3>Latest weekly thesis</h3><div id="weeklyThesis"></div></div>
              <div class="card"><h3>Lessons learned</h3><div id="knowledgeLessons"></div></div>
            </div>
            <div class="stack">
              <div class="card"><h3>Patterns and strategy edges</h3><div id="knowledgePatterns"></div><div id="strategyEdges" style="margin-top:14px"></div></div>
              <div class="card"><h3>Regime playbook</h3><div id="regimePlaybook"></div></div>
              <div class="card"><h3>Improvement backlog</h3><div id="improvementBacklog"></div></div>
            </div>
          </div>
        </section>
        </div>

        <div class="content-pane" data-pane="news">
        <details class="panel foldout" id="news">
          <summary><div><h2>News Influence</h2><p>Linked evidence behind discoveries, headlines, and cross-source movers.</p></div><span>Expand</span></summary>
          <div class="foldout-body">
            <div class="compact-grid" style="margin-bottom:14px">
              <div class="card"><h3>Market regime</h3><p id="marketSummary">No market summary yet.</p><div class="mini" id="marketCards" style="margin-top:14px"></div></div>
              <div class="card"><h3>Analyst tape</h3><div id="analystTape"></div></div>
            </div>
            <div class="newscols">
              <div class="stack">
                <div class="card"><h3>Market headlines</h3><div id="marketHeadlines"></div></div>
                <div class="card"><h3>News discoveries</h3><div id="discoveries"></div></div>
              </div>
              <div class="stack">
                <div class="card"><h3>Cross-source hot stocks</h3><div id="hotStocks"></div></div>
                <div class="card"><h3>Screener rationale</h3><div class="table"><table><thead><tr><th>Symbol</th><th>Source</th><th>Score</th><th>Why</th></tr></thead><tbody id="shortlistTable"></tbody></table></div></div>
              </div>
            </div>
          </div>
        </details>
        </div>

        <div class="content-pane" data-pane="activity">
        <details class="panel foldout" id="activity">
          <summary><div><h2>Context & Telemetry</h2><p>Saved memory, provider attempts, and open positions.</p></div><span>Expand</span></summary>
          <div class="foldout-body">
            <div class="context">
              <div class="stack">
                <div class="card"><h3>Artifact memory</h3><pre class="mono" id="artifactMemory">No saved artifacts yet.</pre></div>
                <div class="card"><h3>LLM telemetry</h3><div class="mini" id="llmSummary"></div><div class="stack" id="providerAttempts" style="margin-top:14px"></div></div>
              </div>
              <div class="stack">
                <div class="card"><h3>Open positions</h3><div class="table"><table><thead><tr><th>Symbol</th><th>Shares</th><th>Avg Cost</th><th>Current</th><th>PnL</th></tr></thead><tbody id="positionsTable"></tbody></table></div></div>
                <div class="card"><h3>Trade history</h3><div class="table"><table><thead><tr><th>Date</th><th>Symbol</th><th>Action</th><th>Qty</th><th>Price</th><th>Value</th><th>Status</th><th>Reasoning</th></tr></thead><tbody id="tradesTable"></tbody></table></div></div>
              </div>
            </div>
          </div>
        </details>
        </div>
      </div>

      <script>
        const arr=v=>Array.isArray(v)?v:[], obj=v=>v&&typeof v==="object"&&!Array.isArray(v)?v:{};
        const num=v=>{const n=Number(v);return Number.isFinite(n)?n:null};
        const esc=v=>String(v??"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;");
        const safeUrl=v=>/^https?:\\/\\//i.test(String(v||""))?String(v):"";
        const truncate=(v,n=140)=>{const t=String(v||"");return t.length>n?t.slice(0,n-1)+"...":t};
        const dateText=v=>{if(!v)return"-";const d=new Date(v);return Number.isNaN(d.getTime())?String(v):d.toLocaleString()};
        const fmtMoney=v=>{const n=num(v);return n===null?"-":"$"+n.toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:2})};
        const signMoney=v=>{const n=num(v);return n===null?"-":(n>=0?"+$":"-$")+Math.abs(n).toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:2})};
        const fmtPct=v=>{const n=num(v);return n===null?"-":(n>=0?"+":"")+n.toFixed(2)+"%"};
        const cls=v=>{const n=num(v);return n===null?"":(n>=0?"good":"bad")};
        const inferExecutionMode=(executionMode,provider)=>{
          const mode=String(executionMode||"").trim().toLowerCase();
          if(["cli","api","none","template"].includes(mode))return mode;
          const prov=String(provider||"").trim().toLowerCase();
          if(prov.startsWith("cli:"))return "cli";
          if(prov.startsWith("template:"))return "template";
          return prov?"api":"unknown";
        };
        const empty=msg=>`<div class="empty">${esc(msg)}</div>`;
        const hover=(title,lines)=>{const items=arr(lines).filter(Boolean);return items.length?`<div class="hover"><strong>${esc(title)}</strong><ul>${items.map(x=>`<li>${esc(x)}</li>`).join("")}</ul></div>`:""};
        const listBlock=(items,fallback)=>{const vals=arr(items).filter(Boolean);return `<ul>${(vals.length?vals:[fallback]).map(x=>`<li>${esc(x)}</li>`).join("")}</ul>`};
        const miniCard=(label,value)=>`<div class="tile"><strong>${esc(label)}</strong><span>${esc(value)}</span></div>`;
        const articleCard=a=>{const url=safeUrl(a.url),pub=a.publisher||a.source||"Unknown source",sent=num(a.sentiment),copy=a.summary||a.reason||"No article summary captured.";const body=`<div class="article-title">${esc(truncate(a.title||"Untitled",110))}</div><div class="article-meta"><span>${esc(pub)}</span><span>${esc(dateText(a.published))}</span><span>${esc(sent===null?(a.kind||"Context item"):"Sentiment "+sent.toFixed(1))}</span></div><div class="article-copy">${esc(truncate(copy,180))}</div>`;return `<div class="article">${url?`<a href="${esc(url)}" target="_blank" rel="noreferrer">${body}</a>`:`<div class="body">${body}</div>`}${hover(a.title||"Article context",[pub,dateText(a.published),a.category?`Category: ${a.category}`:a.kind?`Type: ${a.kind}`:"",sent===null?"":`Sentiment: ${sent.toFixed(2)}`,copy])}</div>`};
        const articleGrid=(items,msg)=>{const list=arr(items).slice(0,6);return list.length?`<div class="articles">${list.map(articleCard).join("")}</div>`:empty(msg)};
        const stackCards=(items,msg)=>{const list=arr(items);return list.length?`<div class="stack">${list.join("")}</div>`:empty(msg)};
        const sentCls=v=>{const n=num(v);return n===null?"neu":n>0.1?"pos":n<-0.1?"neg":"neu"};
        const sentLabel=v=>{const n=num(v);return n===null?"?":n>0?"+"+ n.toFixed(2):n.toFixed(2)};
        const headlineRow=a=>{const sent=num(a.sentiment),src=a.source||"",pub=a.publisher||src||"?",cat=a.category||"headline",url=safeUrl(a.url),title=a.title||"Untitled";return `<div class="headline-row">`+`<div class="hl-sent ${sentCls(sent)}">${sentLabel(sent)}</div>`+`<div class="hl-body">`+`<div class="hl-title">${url?`<a href="${esc(url)}" target="_blank" rel="noreferrer" style="color:inherit;text-decoration:none">${esc(truncate(title,120))}</a>`:esc(truncate(title,120))}</div>`+`<div class="hl-meta"><span class="source-tag">${esc(src)}</span>${esc(pub)} &middot; ${esc(cat)} &middot; ${esc(dateText(a.published))}</div>`+`</div></div>`};
        const headlineList=(items,msg)=>{const list=arr(items);return list.length?`<div class="headline-list">${list.map(headlineRow).join("")}</div>`:empty(msg)};
        const sourceBreakdown=items=>{const counts={};arr(items).forEach(a=>{const s=a.source||"unknown";counts[s]=(counts[s]||0)+1});return Object.keys(counts).length?`<div class="source-breakdown">${Object.entries(counts).sort((a,b)=>b[1]-a[1]).map(([s,c])=>`<span class="src-chip"><span class="source-tag">${esc(s)}</span>${c} article${c>1?"s":""}</span>`).join("")}</div>`:""};
        const linkChip=a=>{const url=safeUrl(a.url);if(!url)return"";const label=a.source||a.publisher||a.title||"Source";return `<a class="link-chip" href="${esc(url)}" target="_blank" rel="noreferrer">${esc(truncate(label,42))}</a>`};
        const dedupeArticles=items=>{const seen=new Set();return arr(items).filter(a=>{const key=(safeUrl(a.url)||String(a.title||"")).toLowerCase();if(!key||seen.has(key))return false;seen.add(key);return true;});};
        const supportingArticlesForSymbol=(analysis,headlines,webArticles)=>dedupeArticles([...arr(analysis.supporting_articles),...arr(headlines),...arr(webArticles)]);
        const matchedArticles=(text,articles)=>{const pool=dedupeArticles(articles);if(!pool.length)return[];const tokens=String(text||"").toLowerCase().match(/[a-z]{4,}/g)||[];const ranked=pool.map(a=>{const haystack=`${String(a.title||"")} ${String(a.summary||"")} ${String(a.reason||"")}`.toLowerCase();const score=tokens.reduce((sum,token)=>sum+(haystack.includes(token)?1:0),0)+(a.reason&&String(text||"").toLowerCase().includes(String(a.reason).toLowerCase())?2:0);return {article:a,score};}).sort((a,b)=>b.score-a.score);const strong=ranked.filter(x=>x.score>0).map(x=>x.article).slice(0,2);return strong.length?strong:pool.slice(0,Math.min(2,pool.length));};
        const linkedReasonList=(items,articles,fallback)=>{const vals=arr(items).filter(Boolean);const rows=(vals.length?vals:[fallback]).map(item=>`<div class="reason-item"><div>${esc(item)}</div><div class="link-row">${matchedArticles(item,articles).map(linkChip).join("")}</div></div>`);return `<div class="reason-list">${rows.join("")}</div>`};
        const discoveryCard=d=>{const url=safeUrl(d.top_headline_url||d.url);const title=d.top_headline||d.discovery_reason||"No discovery reason captured.";const heading=url?`<a href="${esc(url)}" target="_blank" rel="noreferrer" style="color:inherit;text-decoration:none">${esc(title)}</a>`:esc(title);return `<div class="tile"><strong>${esc(d.symbol||"?")}</strong><span>${heading}</span><div class="sub">${esc((d.sentiment_label||"mixed")+" | "+(d.news_sentiment!==undefined?Number(d.news_sentiment).toFixed(2):"n/a"))}</div></div>`};
        const hotStockCard=h=>{const articles=dedupeArticles(arr(h.articles));return `<div class="tile"><strong>${esc(h.symbol||"?")}</strong><span>${esc((h.sentiment||"mixed")+" across "+String(h.source_count||0)+" sources")}</span><div class="sub">${esc(truncate(arr(h.reasons).join(" | "),160)||"No reasons captured.")}</div><div class="link-row">${articles.slice(0,3).map(linkChip).join("")}</div></div>`};
        const labelFromId=id=>String(id||"default").replace(/[-_]+/g," ").replace(/\\b\\w/g,m=>m.toUpperCase());
        const tagRow=items=>arr(items).filter(Boolean).map(item=>`<span class="tag">${esc(item)}</span>`).join("");
        const cssVar=name=>getComputedStyle(document.documentElement).getPropertyValue(name).trim();
        const observationCard=item=>`<div class="observation-item"><strong>${esc(item.date||"Observation")}</strong><div class="small-copy">${esc(item.market_summary||"No observation summary saved.")}</div><div class="tag-row">${tagRow([item.market_regime||"",arr(item.lessons).length?`${arr(item.lessons).length} lesson${arr(item.lessons).length===1?"":"s"}`:""])}</div></div>`;
        const proposalCard=item=>`<div class="proposal-item"><strong>${esc(item.title||"Untitled proposal")}</strong><div class="small-copy">${esc(item.description||"No proposal description saved.")}</div><div class="tag-row">${tagRow([item.priority||"medium",item.category||"other",item.date||"",item.expected_impact?`Impact: ${item.expected_impact}`:""])}</div></div>`;
        const strategyCard=item=>`<div class="pattern-item"><strong>${esc(item.name||"Strategy")}</strong><div class="small-copy">${esc(item.best_regime?`Best in ${item.best_regime}.`:"No best regime captured.")}</div><div class="tag-row">${tagRow([item.win_rate===null||item.win_rate===undefined?"":`Win ${Number(item.win_rate*100).toFixed(0)}%`,item.avg_return===null||item.avg_return===undefined?"":`Avg ${Number(item.avg_return).toFixed(2)}%`])}</div></div>`;
        const regimeCard=item=>`<div class="regime-item"><strong>${esc(item.name||"Regime")}</strong><div class="small-copy">${esc(arr(item.rules).slice(0,2).join(" ")||"No regime rules captured.")}</div><div class="tag-row">${tagRow([arr(item.preferred_strategies).length?`Prefer: ${arr(item.preferred_strategies).join(", ")}`:"",arr(item.avoid_strategies).length?`Avoid: ${arr(item.avoid_strategies).join(", ")}`:"",item.position_size_modifier!==undefined?`Size x${item.position_size_modifier}`:"",item.stop_loss_modifier!==undefined?`Stop x${item.stop_loss_modifier}`:""])}</div></div>`;

        let dashboardBundle=null;
        let selectedProfile=null;
        let selectedSection="overview";
        let valueChartInstance=null;

        function bundleProfiles(bundle){
          const profiles=obj(bundle.profiles);
          if(Object.keys(profiles).length)return profiles;
          const fallbackProfile=obj(bundle.profile);
          const profileId=fallbackProfile.id||bundle.active_profile||"default";
          return {[profileId]:{profile:{id:profileId,label:fallbackProfile.label||labelFromId(profileId)},latest:obj(bundle.latest),history:arr(bundle.history),trades:arr(bundle.trades),research:obj(bundle.research),llm:obj(bundle.llm),context:obj(bundle.context),knowledge:obj(bundle.knowledge),reports:obj(bundle.reports),artifacts:obj(bundle.artifacts)}};
        }

        function comparisonSummary(bundle,profiles){
          const summary=arr(obj(bundle.comparison).summary);
          if(summary.length)return summary;
          return Object.entries(profiles).map(([profileId,profileBundle])=>{const latest=obj(profileBundle.latest),llm=obj(profileBundle.llm),trades=arr(profileBundle.trades),closed=trades.filter(t=>typeof t==="object"&&typeof t.pnl==="number"),wins=closed.filter(t=>(t.pnl||0)>0);return {profile:profileId,label:obj(profileBundle.profile).label||labelFromId(profileId),last_updated:latest.timestamp,portfolio_value:latest.portfolio_value,total_pnl:latest.total_pnl,total_pnl_pct:latest.total_pnl_pct,trade_count:trades.length,closed_trade_count:closed.length,win_rate:closed.length?Math.round(wins.length/closed.length*1000)/10:null,provider:llm.selected_provider||llm.provider,model:llm.selected_model||llm.model};});
        }

        function workflowUrlFromContext(runtime,runUrl){
          const repo=obj(obj(runtime).github).repository;
          if(repo)return `https://github.com/${repo}/actions/workflows/trading.yml`;
          const match=String(runUrl||"").match(/https:\\/\\/github\\.com\\/([^\\/]+\\/[^\\/]+)\\/actions\\/runs\\//i);
          if(match)return `https://github.com/${match[1]}/actions/workflows/trading.yml`;
          if(location.hostname.endsWith(".github.io")){
            const owner=location.hostname.replace(/\\.github\\.io$/i,"");
            const repoName=location.pathname.split("/").filter(Boolean)[0];
            if(owner&&repoName)return `https://github.com/${owner}/${repoName}/actions/workflows/trading.yml`;
          }
          return "https://github.com";
        }

        function initialProfile(bundle,profiles){
          if(bundle.active_profile&&profiles[bundle.active_profile])return bundle.active_profile;
          return Object.keys(profiles)[0]||"default";
        }

        function renderSectionTabs(){
          const sectionTabs=document.querySelectorAll("#sectionTabs [data-section]");
          sectionTabs.forEach(node=>{
            const section=node.getAttribute("data-section")||"overview";
            node.classList.toggle("active",section===selectedSection);
          });
          document.querySelectorAll(".content-pane[data-pane]").forEach(node=>{
            const pane=node.getAttribute("data-pane")||"overview";
            node.classList.toggle("active",pane===selectedSection);
          });
        }

        function renderKnowledge(profileBundle){
          const knowledge=obj(profileBundle.knowledge);
          const counts=obj(knowledge.counts);
          const observations=arr(knowledge.recent_observations);
          const weekly=obj(knowledge.latest_weekly_review);
          const monthly=obj(knowledge.latest_monthly_review);
          const lessons=arr(knowledge.lessons);
          const patterns=arr(knowledge.patterns);
          const strategies=arr(knowledge.strategies);
          const regimes=arr(knowledge.regimes);
          const proposals=arr(knowledge.proposals);
          const promptPreview=obj(knowledge.prompt_preview);

          document.getElementById("knowledgeSummary").innerHTML=[
            ["Daily Notes",String(counts.daily_observations??0)],
            ["Weekly Reviews",String(counts.weekly_reviews??0)],
            ["Lessons",String(counts.lessons??0)],
            ["Patterns",String(counts.patterns??0)],
            ["Regimes",String(counts.regimes??0)],
            ["Open Proposals",String(counts.pending_proposals??0)]
          ].map(([label,value])=>miniCard(label,value)).join("");

          const previewText=promptPreview.knowledge_context||promptPreview.observations_context||"The knowledge store exists, but no prompt-ready summary has been written yet.";
          document.getElementById("knowledgeBlurb").textContent=truncate(previewText,320);
          document.getElementById("knowledgeDocs").innerHTML=[
            `<a class="link-chip" href="ARCHITECTURE.md" target="_blank" rel="noreferrer">System architecture</a>`,
            `<a class="link-chip" href="KNOWLEDGE_ARCHITECTURE.md" target="_blank" rel="noreferrer">Knowledge architecture</a>`,
            document.getElementById("knowledgeLink").href?`<a class="link-chip" href="${esc(document.getElementById("knowledgeLink").href)}" target="_blank" rel="noreferrer">Knowledge JSON</a>`:"",
            document.getElementById("improvementLink").href?`<a class="link-chip" href="${esc(document.getElementById("improvementLink").href)}" target="_blank" rel="noreferrer">Improvement backlog</a>`:""
          ].filter(Boolean).join("");

          document.getElementById("knowledgeObservations").innerHTML=observations.length
            ? `<div class="observation-list">${observations.map(observationCard).join("")}</div>`
            : empty("No daily observations have been saved yet.");

          const weeklyTags=[
            obj(weekly.summary).trades_count!==undefined?`${weekly.summary.trades_count} trades`:"",
            obj(weekly.summary).win_rate!==undefined?`Win ${Number(obj(weekly.summary).win_rate*100).toFixed(0)}%`:"",
            obj(weekly.forward_thesis).confidence!==undefined?`Confidence ${Number(obj(weekly.forward_thesis).confidence*100).toFixed(0)}%`:"",
            obj(weekly.regime_analysis).dominant?`Regime: ${weekly.regime_analysis.dominant}`:""
          ];
          document.getElementById("weeklyThesis").innerHTML=Object.keys(weekly).length
            ? `<div class="knowledge-item"><strong>${esc(weekly.week_start||"Latest weekly review")}</strong><div class="small-copy">${esc(obj(weekly.forward_thesis).outlook||obj(weekly.summary).summary||weekly.summary?.headline||"No weekly thesis saved.")}</div><div class="tag-row">${tagRow(weeklyTags)}</div>${arr(obj(weekly.forward_thesis).key_risks).length?`<div class="small-copy" style="margin-top:10px">Key risks: ${esc(arr(obj(weekly.forward_thesis).key_risks).slice(0,3).join(", "))}</div>`:""}</div>`
            : empty("No weekly review has been written yet.");

          document.getElementById("knowledgeLessons").innerHTML=lessons.length
            ? `<div class="knowledge-list">${lessons.map(item=>`<div class="knowledge-item"><strong>Lesson</strong><div class="small-copy">${esc(item)}</div></div>`).join("")}</div>`
            : empty("No lessons have been distilled yet.");

          document.getElementById("knowledgePatterns").innerHTML=patterns.length
            ? `<div class="pattern-list">${patterns.map(item=>`<div class="pattern-item"><strong>${esc(item.name||"Pattern")}</strong><div class="small-copy">${esc(item.description||item.notes||"No pattern notes stored.")}</div><div class="tag-row">${tagRow([item.win_rate!==undefined?`Win ${Number(item.win_rate*100).toFixed(0)}%`:"",item.total_occurrences!==undefined?`${item.total_occurrences} observations`:"",item.best_regime?`Best: ${item.best_regime}`:"",arr(item.symbols_seen).length?arr(item.symbols_seen).slice(0,4).join(", "):""])}</div></div>`).join("")}</div>`
            : empty("No pattern library entries have been saved yet.");

          document.getElementById("strategyEdges").innerHTML=strategies.length
            ? `<div class="pattern-list">${strategies.map(strategyCard).join("")}</div>`
            : empty("No strategy effectiveness summary has been saved yet.");

          document.getElementById("regimePlaybook").innerHTML=regimes.length
            ? `<div class="regime-list">${regimes.map(regimeCard).join("")}</div>`
            : Object.keys(monthly).length
              ? `<div class="knowledge-item"><strong>${esc(monthly.month||"Latest monthly review")}</strong><div class="small-copy">${esc(obj(monthly.vs_last_month).improvement_areas||"Monthly review available, but no explicit regime playbook was stored.")}</div></div>`
              : empty("No regime playbook has been written yet.");

          document.getElementById("improvementBacklog").innerHTML=proposals.length
            ? `<div class="proposal-list">${proposals.map(proposalCard).join("")}</div>`
            : empty("No improvement proposals have been captured yet.");
        }

        function renderComparison(bundle,profiles){
          const summary=comparisonSummary(bundle,profiles).sort((a,b)=>(num(b.portfolio_value)||0)-(num(a.portfolio_value)||0));
          const byId=Object.fromEntries(summary.map(item=>[item.profile,item]));
          const leaders=obj(obj(bundle.comparison).leaders);
          const leaderText=(key,formatter)=>{const entry=byId[leaders[key]];return entry?`${entry.label||entry.profile} (${formatter(entry[key])})`:"No leader yet";};
          const tabs=document.getElementById("profileTabs");
          tabs.innerHTML=summary.map(item=>`<button type="button" class="btn ${item.profile===selectedProfile?"active":""}" data-profile="${esc(item.profile)}">${esc(item.label||labelFromId(item.profile))}</button>`).join("");
          tabs.querySelectorAll("[data-profile]").forEach(node=>node.addEventListener("click",()=>window.selectProfile(node.getAttribute("data-profile")||"default")));
          document.getElementById("comparisonCards").innerHTML=[["Top Equity Curve",leaderText("portfolio_value",fmtMoney)],["Best Total PnL",leaderText("total_pnl",signMoney)],["Best Win Rate",leaderText("win_rate",v=>v===null?"-":`${Number(v).toFixed(1)}%`)],["Most Trades",leaderText("trade_count",v=>String(v??0))]].map(([label,value])=>miniCard(label,value)).join("");
          document.getElementById("comparisonTable").innerHTML=summary.length?summary.map(item=>`<tr${item.profile===selectedProfile?' style="background:rgba(125,211,252,.08)"':""}><td><strong>${esc(item.label||labelFromId(item.profile))}</strong><div class="sub">${esc(item.profile)}</div></td><td>${fmtMoney(item.portfolio_value)}</td><td class="${cls(item.total_pnl)}">${signMoney(item.total_pnl)}<div class="sub ${cls(item.total_pnl_pct)}">${fmtPct(item.total_pnl_pct)}</div></td><td>${esc(String(item.trade_count??0))}<div class="sub">${esc(String(item.closed_trade_count??0))} closed</div></td><td>${esc(item.win_rate===null?"-":`${Number(item.win_rate).toFixed(1)}%`)}</td><td>${esc(item.provider||"-")}</td><td>${esc(item.model||"-")}</td><td>${esc(dateText(item.last_updated))}</td></tr>`).join(""):`<tr><td colspan="8">${empty("No strategist summaries available yet.")}</td></tr>`;
        }

        function updateLinks(profileBundle,runUrl,runtime){
          const artifacts=obj(profileBundle.artifacts);
          const researchPath=artifacts.research_report_md||"data/report_research.md";
          const monitorPath=artifacts.monitor_report_md||"data/report_monitor.md";
          const weeklyPath=artifacts.weekly_report_json||"data/report_weekly.json";
          const monthlyPath=artifacts.monthly_report_json||"data/report_monthly.json";
          document.getElementById("researchLink").href=researchPath;
          document.getElementById("monitorLink").href=monitorPath;
          document.getElementById("weeklyLink").href=weeklyPath;
          document.getElementById("monthlyLink").href=monthlyPath;
          document.getElementById("contextLink").href=artifacts.context_json||"data/context.json";
          document.getElementById("llmLink").href=artifacts.llm_json||"data/llm.json";
          document.getElementById("knowledgeLink").href=artifacts.knowledge_json||"data/knowledge.json";
          document.getElementById("improvementLink").href=artifacts.improvement_json||"data/improvement_proposals.json";
          document.getElementById("dashboardLink").href=artifacts.dashboard_json||"data/dashboard.json";
          const runLink=document.getElementById("runLink");
          if(runUrl){runLink.href=runUrl;runLink.textContent="Open GitHub Actions run";}else{runLink.href=researchPath;runLink.textContent="Open latest report";}
          const resetLink=document.getElementById("resetLink");
          const workflowUrl=workflowUrlFromContext(runtime,runUrl);
          resetLink.href=workflowUrl;
          resetLink.title="Open the GitHub Actions workflow page, then dispatch a run with reset_state enabled.";
        }

        function renderProfile(profileBundle,bundle){
          const profile=obj(profileBundle.profile), latest=obj(profileBundle.latest), trades=arr(profileBundle.trades), reports=obj(profileBundle.reports), reportResearch=obj(reports.research), reportMonitor=obj(reports.monitor), reportPayload=obj(reportResearch.research);
          const research=Object.keys(obj(profileBundle.research)).length?obj(profileBundle.research):obj(reportPayload.research), context=obj(profileBundle.context), prompt=obj(context.prompt_sections), newsInputs=obj(prompt.news_inputs), perSymbol=obj(newsInputs.per_symbol), webInfluence=obj(newsInputs.web_influence), webArticlesBySymbol=obj(webInfluence.articles_by_symbol), screener=obj(prompt.screener_context), market=obj(prompt.market_context);
          const llm=Object.keys(obj(profileBundle.llm)).length?obj(profileBundle.llm):(obj(research._meta)||obj(context.llm_meta));
          const shortlist=arr(screener.shortlist), marketHeadlines=arr(newsInputs.market_headlines), discoveries=arr(newsInputs.news_discoveries), hotStocks=arr(newsInputs.hot_stocks), analystChanges=arr(obj(newsInputs.finviz).analyst_changes), positions=arr(latest.positions);
          const totalArticles=Object.values(perSymbol).reduce((s,v)=>s+arr(obj(v).news_headlines).length,0)+marketHeadlines.length+Object.values(webArticlesBySymbol).reduce((s,v)=>s+arr(v).length,0);
          const best=arr(research.best_opportunities), signals=arr(reportMonitor.signals), approved=arr(obj(reportMonitor.risk).approved_trades), rejected=arr(obj(reportMonitor.risk).rejected_trades), executed=arr(reportMonitor.executed), webChecks=arr(research.web_checks).length+arr(reportMonitor.web_checks).length;

          const runtime=obj(llm.runtime)||obj(obj(context.llm_meta).runtime);
          const runUrl=runtime.github?.run_url||context.llm_meta?.runtime?.github?.run_url||"";
          updateLinks(profileBundle,runUrl,runtime);
          document.getElementById("navStatus").textContent=`Viewing ${profile.label||labelFromId(profile.id)}`;
          document.getElementById("heroProfile").textContent=profile.label||labelFromId(profile.id);
          document.getElementById("heroSummary").textContent=[`${profile.label||labelFromId(profile.id)} is active.`,research.market_summary,research.market_regime?`Regime: ${research.market_regime}`:"",best.length?`Top ideas: ${best.join(", ")}`:""].filter(Boolean).join(" | ")||"Latest research and workflow context loaded.";
          document.getElementById("heroSubline").textContent=[`Provider: ${llm.selected_provider||llm.provider||context.provider||"-"}`,`Model: ${llm.selected_model||llm.model||context.model||"-"}`,best.length?`Watching ${best.join(", ")}`:"No standout opportunity saved yet"].join(" | ");
          document.getElementById("heroMeta").innerHTML=[["Last Updated",dateText(latest.timestamp||bundle.generated_at)],["Provider",llm.selected_provider||llm.provider||context.provider||"-"],["Model",llm.selected_model||llm.model||context.model||"-"],["Symbols",String(arr(context.symbols).length||Object.keys(perSymbol).length||Object.keys(obj(research.stocks)).length)],["Prompt Articles",String(totalArticles)],["Best Opportunities",best.join(", ")||"None"]].map(([l,v])=>`<div class="card" style="padding:14px"><div class="label">${esc(l)}</div><div>${esc(v)}</div></div>`).join("");
          document.getElementById("portfolioValue").textContent=fmtMoney(latest.portfolio_value); document.getElementById("cashValue").textContent=fmtMoney(latest.cash); document.getElementById("positionCount").textContent=String(latest.position_count||positions.length); document.getElementById("tradeCount").textContent=String(trades.length); document.getElementById("articleCount").textContent=String(totalArticles); document.getElementById("modeNote").textContent=trades.some(t=>(t.status||"").toLowerCase()!=="dry_run")?"Live execution detected":"Dry-run history";
          const pnl=document.getElementById("totalPnl"); pnl.textContent=signMoney(latest.total_pnl); pnl.className="value "+cls(latest.total_pnl); const pnlPct=document.getElementById("totalPnlPct"); pnlPct.textContent=fmtPct(latest.total_pnl_pct); pnlPct.className="sub "+cls(latest.total_pnl_pct);
          renderKnowledge(profileBundle);

          document.getElementById("workflow").innerHTML=[
            {title:"News",summary:"Headlines, filings, and analyst changes were gathered before research.",metric:String(totalArticles),lines:[`${marketHeadlines.length} market headlines`,`${discoveries.length} discoveries`,`${hotStocks.length} hot stocks`,...marketHeadlines.slice(0,3).map(x=>x.title||"")]},
            {title:"Screener",summary:"News and technical context narrowed the universe into a shortlist.",metric:String(shortlist.length),lines:[`Total scanned: ${screener.total_scanned||0}`,`Candidates found: ${screener.candidates_found||0}`,`News boosts: ${screener.news_discovered||0}`,...shortlist.slice(0,3).map(x=>`${x.symbol||"?"} - ${x.discovery_reason||x.top_headline||x.source||"technical setup"}`)]},
            {title:"Research",summary:"The LLM returned the structured thesis and trade plan.",metric:String(best.length),lines:[`Overall sentiment: ${research.overall_sentiment||"unknown"}`,`Market regime: ${research.market_regime||market.market_regime||"unknown"}`,`Provider: ${llm.selected_provider||llm.provider||context.provider||"-"}`,`Model: ${llm.selected_model||llm.model||context.model||"-"}`,`Total tokens: ${llm.usage?.total_tokens??"n/a"}`]},
            {title:"Monitor / Execution",summary:"Signals, approvals, and trades were archived for follow-up.",metric:String(executed.length),lines:[`${signals.length} signals`,`${approved.length} approved trades`,`${rejected.length} rejected trades`,...executed.slice(0,3).map(x=>`${x.symbol||"?"} ${String((x.action||"").toUpperCase())} ${x.quantity||0}`)]}
          ].map(x=>`<article class="stage"><div class="top"><div><div class="label">${esc(x.title)}</div><p>${esc(x.summary)}</p></div><div class="metric">${esc(x.metric)}</div></div>${hover(x.title+" details",x.lines)}</article>`).join("");

          document.getElementById("runSummary").innerHTML=[["Research Run",reportResearch.run_id||"-"],["Research Time",dateText(reportResearch.timestamp||context.timestamp)],["Monitor Time",dateText(reportMonitor.timestamp)],["Execution Mode",inferExecutionMode(llm.execution_mode,llm.selected_provider||llm.provider)||"-"],["Signals",String(signals.length)],["Approved",String(approved.length)],["Executed",String(executed.length)],["Web Checks",String(webChecks)],["Quota Note",llm.quota_note||"No quota note recorded"],["Platform",llm.runtime?.platform||"-"]].map(([l,v])=>miniCard(l,String(v))).join("");

          const researchStocks=obj(research.stocks), shortlistMap=Object.fromEntries(shortlist.map(x=>[x.symbol,x])), symbols=[]; [...best,...Object.keys(researchStocks),...Object.keys(perSymbol),...shortlist.map(x=>x.symbol)].forEach(s=>{if(s&&!symbols.includes(s))symbols.push(s)});
          document.getElementById("decisionBoard").innerHTML=symbols.length
            ? symbols.map((symbol,index)=>{
                const analysis=obj(researchStocks[symbol]), news=obj(perSymbol[symbol]), pick=obj(shortlistMap[symbol]), plan=obj(analysis.trade_plan), rec=analysis.recommendation||"watch", headlines=arr(news.news_headlines), webArticles=arr(webArticlesBySymbol[symbol]), supporting=supportingArticlesForSymbol(analysis,headlines,webArticles), uniqueSources=new Set(supporting.map(a=>a.source||a.publisher).filter(Boolean));
                const srcCount=Math.max(news.source_count||0,uniqueSources.size);
                const confidence=analysis.confidence!==undefined?Math.round(Number(analysis.confidence)*100)+"%":"-";
                return `<article class="decision"><details ${index===0?"open":""}><summary><div class="top"><div><h3>${esc(symbol)}</h3><p>${esc(analysis.technical_setup||analysis.news_summary||pick.discovery_reason||"No narrative stored for this symbol.")}</p><div class="sub">${esc(`${confidence} confidence | ${srcCount} source${srcCount===1?"":"s"} | ${headlines.length} headline${headlines.length===1?"":"s"}`)}</div></div><span class="pill ${rec==="buy"?"good":rec==="sell"?"bad":"warn"}">${esc(rec)}</span></div></summary><div class="decision-body"><div class="mini">${miniCard("Sentiment",analysis.sentiment||news.sentiment||"neutral")}${miniCard("Confidence",confidence)}${miniCard("News Impact",analysis.news_impact||"none")}${miniCard("Sources",String(srcCount)+" provider"+(srcCount!==1?"s":""))}${miniCard("Headlines",String(headlines.length))}${miniCard("Web Evidence",String(webArticles.length))}${miniCard("Entry",fmtMoney(plan.entry))}${miniCard("Stop",fmtMoney(plan.stop_loss))}${miniCard("Target",fmtMoney(plan.target))}${miniCard("R / R",plan.risk_reward_ratio!==undefined?Number(plan.risk_reward_ratio).toFixed(2):"-")}${miniCard("Shortlist",pick.source||"research")}</div>${sourceBreakdown(supporting.length?supporting:headlines)}<div class="list"><strong>Why it was interesting</strong>${linkedReasonList([pick.discovery_reason||pick.top_headline||analysis.news_summary||"No shortlist rationale captured.",`Score: ${pick.score!==undefined?Number(pick.score).toFixed(3):"n/a"} | Source: ${pick.source||"n/a"}`],supporting,"No shortlist rationale captured.")}</div><div class="list"><strong>Key observations</strong>${listBlock(analysis.key_observations,"No observations were returned.")}</div><div class="list"><strong>Catalysts</strong>${linkedReasonList(analysis.catalysts,supporting,"No catalysts were listed.")}</div><div class="list"><strong>Risks</strong>${linkedReasonList(analysis.risks,supporting,"No explicit risks were listed.")}</div><div class="list"><strong>Linked evidence</strong>${articleGrid(supporting.slice(0,4),"No linked evidence was stored for this decision.")}</div><div class="list"><strong>All headlines that influenced this decision (${headlines.length})</strong>${headlineList(headlines,"No symbol-specific articles were captured for this decision.")}</div></div></details></article>`;
              }).join("")
            : empty("No research decisions available yet.");

          document.getElementById("marketHeadlines").innerHTML=articleGrid(marketHeadlines,"No market headlines were captured in the latest run.");
          document.getElementById("discoveries").innerHTML=stackCards(discoveries.map(discoveryCard),"No news-driven discoveries were stored for the latest run.");
          document.getElementById("hotStocks").innerHTML=stackCards(hotStocks.map(hotStockCard),"No cross-source hot stocks were persisted.");
          document.getElementById("analystTape").innerHTML=stackCards(analystChanges.map(x=>`<div class="tile"><strong>${esc(x.symbol||"?")}</strong><span>${esc((x.firm||"?")+": "+(x.action||"?"))}</span><div class="sub">${esc((x.from_grade||"?")+" -> "+(x.to_grade||"?"))}</div></div>`),"No analyst changes were captured.");

          document.getElementById("marketSummary").textContent=research.market_summary||"No market summary available.";
          const marketCards=[]; if(market.market_regime)marketCards.push(["Regime",market.market_regime]); if(market.sp500?.change_pct!==undefined)marketCards.push(["SPY",fmtPct(market.sp500.change_pct)]); if(market.nasdaq?.change_pct!==undefined)marketCards.push(["QQQ",fmtPct(market.nasdaq.change_pct)]); if(market.vix?.value!==undefined)marketCards.push(["VIX",String(market.vix.value)]); if(market.treasury_10y?.yield_pct!==undefined)marketCards.push(["10Y Yield",market.treasury_10y.yield_pct+"%"]); if(arr(market.sector_leaders).length)marketCards.push(["Leaders",arr(market.sector_leaders).map(x=>`${x.sector} ${fmtPct(x.daily_pct)}`).join(", ")]); if(arr(market.sector_laggards).length)marketCards.push(["Laggards",arr(market.sector_laggards).map(x=>`${x.sector} ${fmtPct(x.daily_pct)}`).join(", ")]);
          document.getElementById("marketCards").innerHTML=marketCards.length?marketCards.map(([l,v])=>miniCard(l,v)).join(""):empty("No market regime cards were captured.");
          document.getElementById("artifactMemory").textContent=prompt.artifact_context||"No saved artifacts yet.";
          const selectedMode=inferExecutionMode(llm.execution_mode,llm.selected_provider||llm.provider||"");
          document.getElementById("llmSummary").innerHTML=[["Execution Mode",selectedMode||"-"],["Provider",llm.selected_provider||llm.provider||context.provider||"-"],["Model",llm.selected_model||llm.model||context.model||"-"],["Input Tokens",llm.usage?.input_tokens??"-"],["Output Tokens",llm.usage?.output_tokens??"-"],["Total Tokens",llm.usage?.total_tokens??"-"],["Capacity Before Request",String(llm.rate_limits?.estimates?.tokens_remaining_before_request_estimate??llm.rate_limits?.estimates?.input_tokens_remaining_before_request_estimate??"n/a")],["Latency",llm.duration_ms?`${Math.round(Number(llm.duration_ms))} ms`:"-"],["Run ID",llm.runtime?.github?.run_id||"-"],["Request ID",llm.request_id||"-"],["Quota Note",llm.quota_note||"No quota note recorded"]].map(([l,v])=>miniCard(l,String(v))).join("");
          document.getElementById("providerAttempts").innerHTML=arr(llm.attempts).length?arr(llm.attempts).map(x=>{const mode=inferExecutionMode(x.execution_mode,x.provider||"");return `<div class="tile"><strong>${esc((x.provider||"?")+" / "+(x.model||"?"))}</strong><span>${esc(`Mode: ${mode} | Status: ${x.status||"unknown"}`)}</span><div class="sub">${esc(x.duration_ms!==undefined?`${x.duration_ms} ms`:"duration n/a")}${x.error?` | ${esc(truncate(String(x.error),90))}`:""}</div></div>`;}).join(""):empty("No provider attempts were recorded.");

          document.getElementById("shortlistTable").innerHTML=shortlist.length?shortlist.map(x=>`<tr><td><strong>${esc(x.symbol||"")}</strong></td><td>${esc(x.source||"")}</td><td>${x.score!==undefined?Number(x.score).toFixed(3):"-"}</td><td>${safeUrl(x.top_headline_url||x.url)?`<a href="${esc(safeUrl(x.top_headline_url||x.url))}" target="_blank" rel="noreferrer">${esc(x.discovery_reason||x.top_headline||"Technical move only")}</a>`:esc(x.discovery_reason||x.top_headline||"Technical move only")}</td></tr>`).join(""):`<tr><td colspan="4">${empty("No shortlist stored in latest context.")}</td></tr>`;
          document.getElementById("positionsTable").innerHTML=positions.length?positions.map(x=>`<tr><td><strong>${esc(x.symbol)}</strong></td><td>${esc(x.shares)}</td><td>${fmtMoney(x.avg_cost)}</td><td>${fmtMoney(x.current_price)}</td><td class="${cls(x.unrealized_pnl)}">${signMoney(x.unrealized_pnl)}</td></tr>`).join(""):`<tr><td colspan="5">${empty("No positions yet.")}</td></tr>`;
          document.getElementById("tradesTable").innerHTML=trades.length?trades.slice(-60).reverse().map(x=>`<tr><td>${esc(dateText(x.timestamp))}</td><td><strong>${esc(x.symbol||"")}</strong></td><td>${esc(String((x.action||"").toUpperCase()))}</td><td>${esc(x.quantity??"-")}</td><td>${fmtMoney(x.price)}</td><td>${fmtMoney(x.value)}</td><td>${esc(x.status||"-")}</td><td>${esc(x.reasoning||x.reason||"-")}</td></tr>`).join(""):`<tr><td colspan="8">${empty("No trades yet.")}</td></tr>`;

          if(valueChartInstance){valueChartInstance.destroy();valueChartInstance=null;}
          const history=arr(profileBundle.history); if(history.length&&window.Chart){const muted=cssVar("--muted")||"#5e706b";const accent=cssVar("--accent")||"#0f766e";valueChartInstance=new Chart(document.getElementById("valueChart").getContext("2d"),{type:"line",data:{labels:history.map(x=>dateText(x.timestamp)),datasets:[{label:"Portfolio Value",data:history.map(x=>x.portfolio_value),borderColor:accent,backgroundColor:"rgba(15,118,110,.10)",fill:true,tension:.25,borderWidth:2,pointRadius:2}]},options:{maintainAspectRatio:false,plugins:{legend:{labels:{color:muted}}},scales:{x:{ticks:{color:muted,maxTicksLimit:8},grid:{color:"rgba(44,70,67,.08)"}},y:{ticks:{color:muted,callback:v=>"$"+Number(v).toLocaleString()},grid:{color:"rgba(44,70,67,.08)"}}}}});}
        }

        function renderDashboard(){
          const profiles=bundleProfiles(dashboardBundle||{});
          if(!selectedProfile||!profiles[selectedProfile])selectedProfile=initialProfile(dashboardBundle||{},profiles);
          renderSectionTabs();
          renderComparison(dashboardBundle||{},profiles);
          renderProfile(profiles[selectedProfile]||Object.values(profiles)[0]||{},dashboardBundle||{});
        }

        window.selectSection=section=>{
          selectedSection=section||"overview";
          renderSectionTabs();
        };
        window.selectProfile=profileId=>{selectedProfile=profileId;renderDashboard();};

        document.querySelectorAll("#sectionTabs [data-section]").forEach(node=>{
          node.addEventListener("click",()=>window.selectSection(node.getAttribute("data-section")||"overview"));
        });
        const brandLink=document.querySelector(".brand");
        if(brandLink){
          brandLink.addEventListener("click",event=>{
            event.preventDefault();
            window.selectSection("overview");
          });
        }
        renderSectionTabs();
        fetch("data/dashboard.json").then(r=>r.json()).then(bundle=>{dashboardBundle=bundle;renderDashboard();}).catch(err=>console.error("Dashboard load error",err));
      </script>
    </body>
    </html>
    """
).strip() + "\n"


def generate_dashboard(data_dir: str = "data", docs_dir: str = "docs") -> None:
    """Generate the dashboard HTML and JSON bundles."""
    data_root = Path(data_dir)
    docs_root = Path(docs_dir)
    data_out = docs_root / "data"
    docs_root.mkdir(parents=True, exist_ok=True)
    data_out.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(data_out / "profiles", ignore_errors=True)
    shutil.rmtree(data_out / "interactions", ignore_errors=True)
    shutil.rmtree(data_out / "voice", ignore_errors=True)

    profile_roots = _discover_profile_roots(data_root)
    bundle = _build_dashboard_bundle(data_root, profile_roots=profile_roots)
    (docs_root / "index.html").write_text(_load_dashboard_html(), encoding="utf-8")
    _write_json(data_out / "dashboard.json", bundle)
    _write_json(data_out / "latest.json", bundle["latest"])
    _write_json(data_out / "history.json", bundle["history"])
    _write_json(data_out / "trades.json", bundle["trades"])
    _write_json(data_out / "research.json", bundle["research"])
    _write_json(data_out / "llm.json", bundle["llm"])
    _write_json(data_out / "context.json", bundle["context"])
    _write_json(data_out / "knowledge.json", bundle["knowledge"])
    _write_json(data_out / "interactions.json", bundle["interactions"])
    _write_json(data_out / "voice.json", bundle["voice"])
    _write_json(data_out / "report_research.json", bundle["reports"]["research"])
    _write_json(data_out / "report_monitor.json", bundle["reports"]["monitor"])
    _write_json(
        data_out / "report_weekly.json",
        bundle["knowledge"].get("latest_weekly_review", {}),
    )
    _write_json(
        data_out / "report_monthly.json",
        bundle["knowledge"].get("latest_monthly_review", {}),
    )
    active_root = profile_roots.get(bundle["active_profile"], data_root)
    _copy_latest_report_artifact(active_root, data_out / "report_research.md", phase="research", suffix=".md")
    _copy_latest_report_artifact(active_root, data_out / "report_monitor.md", phase="monitor", suffix=".md")
    _copy_if_exists(active_root / "improvement_proposals.json", data_out / "improvement_proposals.json")
    _copy_if_exists(active_root / "IMPROVEMENT_PROPOSALS.md", data_out / "IMPROVEMENT_PROPOSALS.md")
    _copy_interaction_files(active_root, data_out / "interactions", bundle["interactions"])
    _copy_voice_files(active_root, data_out / "voice")

    for profile_id, profile_root in profile_roots.items():
        profile_bundle = bundle["profiles"][profile_id]
        profile_out = data_out / "profiles" / profile_id
        profile_out.mkdir(parents=True, exist_ok=True)
        _write_json(profile_out / "dashboard.json", profile_bundle)
        _write_json(profile_out / "latest.json", profile_bundle["latest"])
        _write_json(profile_out / "history.json", profile_bundle["history"])
        _write_json(profile_out / "trades.json", profile_bundle["trades"])
        _write_json(profile_out / "research.json", profile_bundle["research"])
        _write_json(profile_out / "llm.json", profile_bundle["llm"])
        _write_json(profile_out / "context.json", profile_bundle["context"])
        _write_json(profile_out / "knowledge.json", profile_bundle["knowledge"])
        _write_json(profile_out / "interactions.json", profile_bundle["interactions"])
        _write_json(profile_out / "voice.json", profile_bundle["voice"])
        _write_json(profile_out / "report_research.json", profile_bundle["reports"]["research"])
        _write_json(profile_out / "report_monitor.json", profile_bundle["reports"]["monitor"])
        _write_json(
            profile_out / "report_weekly.json",
            profile_bundle["knowledge"].get("latest_weekly_review", {}),
        )
        _write_json(
            profile_out / "report_monthly.json",
            profile_bundle["knowledge"].get("latest_monthly_review", {}),
        )
        _copy_latest_report_artifact(profile_root, profile_out / "report_research.md", phase="research", suffix=".md")
        _copy_latest_report_artifact(profile_root, profile_out / "report_monitor.md", phase="monitor", suffix=".md")
        _copy_if_exists(
            profile_root / "improvement_proposals.json",
            profile_out / "improvement_proposals.json",
        )
        _copy_if_exists(
            profile_root / "IMPROVEMENT_PROPOSALS.md",
            profile_out / "IMPROVEMENT_PROPOSALS.md",
        )
        _copy_interaction_files(profile_root, profile_out / "interactions", profile_bundle["interactions"])
        _copy_voice_files(profile_root, profile_out / "voice")

    rules_path = active_root / "feedback" / "learned_rules.json"
    if rules_path.exists():
        (data_out / "rules.json").write_text(
            rules_path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )


def _build_dashboard_bundle(
    data_root: Path,
    *,
    profile_roots: dict[str, Path] | None = None,
) -> dict[str, Any]:
    profile_roots = profile_roots or _discover_profile_roots(data_root)
    multi_profile = len(profile_roots) > 1 or any(profile_id != "default" for profile_id in profile_roots)
    profiles = {
        profile_id: _build_profile_bundle(profile_root, profile_id=profile_id, multi_profile=multi_profile)
        for profile_id, profile_root in profile_roots.items()
    }
    active_profile = _select_active_profile(profiles)
    active_bundle = profiles.get(active_profile) or next(iter(profiles.values()), _empty_profile_bundle("default"))
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "active_profile": active_profile,
        "profiles": profiles,
        "comparison": _build_comparison_bundle(profiles),
        "profile": active_bundle["profile"],
        "latest": active_bundle["latest"],
        "history": active_bundle["history"],
        "trades": active_bundle["trades"],
        "research": active_bundle["research"],
        "llm": active_bundle["llm"],
        "context": active_bundle["context"],
        "knowledge": active_bundle["knowledge"],
        "interactions": active_bundle["interactions"],
        "voice": active_bundle["voice"],
        "reports": active_bundle["reports"],
    }


def _discover_profile_roots(data_root: Path) -> dict[str, Path]:
    profiles_root = data_root / "profiles"
    if profiles_root.exists():
        discovered = {
            path.name: path
            for path in sorted(profiles_root.iterdir())
            if path.is_dir()
        }
        if len(discovered) > 1 and "default" in discovered:
            discovered = {name: path for name, path in discovered.items() if name != "default"}
        if discovered:
            return discovered
    return {"default": data_root}


def _build_profile_bundle(data_root: Path, *, profile_id: str, multi_profile: bool) -> dict[str, Any]:
    profile = _load_profile_metadata(data_root, profile_id=profile_id)
    research_report = _get_latest_report(data_root, "research")
    monitor_report = _get_latest_report(data_root, "monitor")
    report_payload = _extract_report_payload(research_report)
    research = _get_latest_json(data_root / "research") or _extract_research_analysis(report_payload)
    context = _normalize_context(
        _read_json(data_root / "context" / "latest_research.json", {}),
        report_payload,
        research_report,
    )
    llm = _normalize_llm(
        _read_json(data_root / "analytics" / "latest_llm.json", {}),
        context,
        research,
    )
    return {
        "profile": profile,
        "latest": _load_latest_snapshot(data_root, profile=profile),
        "history": _read_json(data_root / "snapshots" / "history.json", []),
        "trades": _load_trade_history(data_root, profile=profile),
        "research": research,
        "llm": llm,
        "context": context,
        "knowledge": _load_knowledge_bundle(data_root),
        "interactions": _load_interaction_bundle(data_root, profile_id=profile["id"], multi_profile=multi_profile),
        "voice": _load_voice_bundle(data_root, profile_id=profile["id"], multi_profile=multi_profile),
        "reports": {"research": research_report, "monitor": monitor_report},
        "artifacts": _build_profile_artifacts(profile["id"], multi_profile=multi_profile),
    }


def _load_knowledge_bundle(data_root: Path) -> dict[str, Any]:
    observations_root = data_root / "observations"
    knowledge_root = data_root / "knowledge"

    recent_daily = _load_recent_json_series(observations_root / "daily", "obs_*.json", limit=4)
    recent_weekly = _load_recent_json_series(observations_root / "weekly", "week_*.json", limit=3)
    recent_monthly = _load_recent_json_series(observations_root / "monthly", "month_*.json", limit=2)

    lessons_payload = _read_json(knowledge_root / "lessons_learned.json", {"lessons": []})
    patterns_payload = _read_json(knowledge_root / "patterns_library.json", {"patterns": []})
    strategy_payload = _read_json(knowledge_root / "strategy_effectiveness.json", {})
    regime_payload = _read_json(knowledge_root / "regime_library.json", {"regimes": {}})
    proposal_entries = _read_json(data_root / "improvement_proposals.json", [])

    lessons_source = lessons_payload.get("lessons") if isinstance(lessons_payload, dict) else lessons_payload
    lessons = [
        str(item).strip()
        for item in _safe_list(lessons_source)
        if str(item).strip()
    ][-10:]
    lessons.reverse()

    patterns_source = patterns_payload.get("patterns") if isinstance(patterns_payload, dict) else patterns_payload
    patterns = [
        item
        for item in _safe_list(patterns_source)
        if isinstance(item, dict)
    ]
    patterns.sort(
        key=lambda item: (
            item.get("last_seen", ""),
            _safe_float(str(item.get("win_rate", 0))),
            int(item.get("total_occurrences", item.get("occurrences", 0)) or 0),
        ),
        reverse=True,
    )
    patterns = patterns[:8]

    strategies = _flatten_strategy_effectiveness(strategy_payload)
    regimes = _flatten_regime_library(regime_payload)
    proposals = _flatten_improvement_proposals(proposal_entries)

    current_regime = ""
    latest_weekly = recent_weekly[0] if recent_weekly else {}
    latest_monthly = recent_monthly[0] if recent_monthly else {}
    if isinstance(latest_weekly.get("regime_analysis"), dict):
        current_regime = str(latest_weekly["regime_analysis"].get("dominant", "")).strip()
    if not current_regime and recent_daily:
        current_regime = str(recent_daily[0].get("market_regime", "")).strip()

    prompt_preview = {"knowledge_context": "", "observations_context": ""}
    try:
        from agent_trader.utils.knowledge_base import KnowledgeBase

        watchlist = _read_json(data_root / "cache" / "watchlist.json", [])
        kb = KnowledgeBase(str(data_root))
        prompt_preview = {
            "knowledge_context": kb.build_knowledge_context(
                token_budget=600,
                watchlist=watchlist if isinstance(watchlist, list) else None,
                current_regime=current_regime,
            ),
            "observations_context": kb.build_observations_context(token_budget=280),
        }
    except Exception:
        prompt_preview = {"knowledge_context": "", "observations_context": ""}

    counts = {
        "daily_observations": len(list((observations_root / "daily").glob("obs_*.json"))),
        "weekly_reviews": len(list((observations_root / "weekly").glob("week_*.json"))),
        "monthly_reviews": len(list((observations_root / "monthly").glob("month_*.json"))),
        "patterns": len(
            [item for item in _safe_list(patterns_source) if isinstance(item, dict)]
        ),
        "lessons": len(
            [item for item in _safe_list(lessons_source) if str(item).strip()]
        ),
        "strategies": len(strategies),
        "regimes": len(regimes),
        "pending_proposals": len(proposals),
    }

    return {
        "counts": counts,
        "recent_observations": recent_daily,
        "weekly_reviews": recent_weekly,
        "monthly_reviews": recent_monthly,
        "latest_weekly_review": latest_weekly,
        "latest_monthly_review": latest_monthly,
        "lessons": lessons,
        "patterns": patterns,
        "strategies": strategies,
        "regimes": regimes,
        "proposals": proposals,
        "prompt_preview": prompt_preview,
        "improvement_log_present": (data_root / "IMPROVEMENT_PROPOSALS.md").exists(),
    }


def _load_interaction_bundle(data_root: Path, *, profile_id: str, multi_profile: bool) -> dict[str, Any]:
    interactions_root = data_root / "interactions"
    if not interactions_root.exists():
        return _empty_interaction_bundle()

    metadata_files = sorted(
        [
            path
            for path in interactions_root.rglob("*_interaction.json")
            if path.is_file()
        ],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    base = f"data/profiles/{profile_id}" if multi_profile else "data"
    recent: list[dict[str, Any]] = []
    latest_by_phase: dict[str, dict[str, Any]] = {}

    for path in metadata_files:
        payload = _read_json(path, {})
        if not isinstance(payload, dict):
            continue
        phase = str(payload.get("phase", "")).strip().lower() or "unknown"
        item = {
            "timestamp": payload.get("timestamp"),
            "profile": payload.get("profile", profile_id),
            "phase": phase,
            "tool": payload.get("tool", ""),
            "status": payload.get("status", "unknown"),
            "summary": payload.get("summary", ""),
            "prompt_file": payload.get("prompt_file", ""),
            "transcript_file": payload.get("transcript_file", ""),
            "metadata_file": str(path).replace("\\", "/"),
            "raw_log_file": payload.get("raw_log_file", ""),
            "prompt_source": payload.get("prompt_source", ""),
            "prompt_url": _public_interaction_path(payload.get("prompt_file", ""), profile_id=profile_id, multi_profile=multi_profile),
            "transcript_url": _public_interaction_path(payload.get("transcript_file", ""), profile_id=profile_id, multi_profile=multi_profile),
            "metadata_url": _public_interaction_path(str(path).replace("\\", "/"), profile_id=profile_id, multi_profile=multi_profile),
            "prompt_source_url": _public_repo_path(payload.get("prompt_source", "")),
        }
        recent.append(item)
        if phase not in latest_by_phase:
            latest_by_phase[phase] = item
        if len(recent) >= 12 and len(latest_by_phase) >= 4:
            break

    return {
        "counts": {
            "total": len(metadata_files),
            "recent": len(recent),
        },
        "latest": recent[0] if recent else {},
        "latest_by_phase": latest_by_phase,
        "recent": recent,
    }


def _empty_interaction_bundle() -> dict[str, Any]:
    return {
        "counts": {"total": 0, "recent": 0},
        "latest": {},
        "latest_by_phase": {},
        "recent": [],
    }


def _load_voice_bundle(data_root: Path, *, profile_id: str, multi_profile: bool) -> dict[str, Any]:
    voice_root = data_root / "voice"
    if not voice_root.exists():
        return _empty_voice_bundle()

    history_files = sorted(
        [
            path
            for path in voice_root.glob("voice_*.json")
            if path.is_file()
        ],
        key=lambda path: (path.stem, path.stat().st_mtime),
        reverse=True,
    )

    latest_payload = _read_json(voice_root / "latest_voice.json", {})
    latest_item = _normalize_voice_entry(
        latest_payload,
        raw_path=(voice_root / "latest_voice.json").as_posix(),
        profile_id=profile_id,
        multi_profile=multi_profile,
    )

    recent: list[dict[str, Any]] = []
    for path in history_files[:6]:
        payload = _read_json(path, {})
        item = _normalize_voice_entry(
            payload,
            raw_path=path.as_posix(),
            profile_id=profile_id,
            multi_profile=multi_profile,
        )
        if item:
            recent.append(item)

    if not latest_item and recent:
        latest_item = recent[0]

    return {
        "counts": {
            "total": len(history_files),
            "recent": len(recent),
        },
        "latest": latest_item,
        "recent": recent,
    }


def _normalize_voice_entry(
    payload: Any,
    *,
    raw_path: str,
    profile_id: str,
    multi_profile: bool,
) -> dict[str, Any]:
    if not isinstance(payload, dict) or not payload:
        return {}
    item = dict(payload)
    item["json_file"] = raw_path.replace("\\", "/")
    item["json_url"] = _public_voice_path(raw_path, profile_id=profile_id, multi_profile=multi_profile)
    return item


def _empty_voice_bundle() -> dict[str, Any]:
    return {
        "counts": {"total": 0, "recent": 0},
        "latest": {},
        "recent": [],
    }


def _empty_knowledge_bundle() -> dict[str, Any]:
    return {
        "counts": {
            "daily_observations": 0,
            "weekly_reviews": 0,
            "monthly_reviews": 0,
            "patterns": 0,
            "lessons": 0,
            "strategies": 0,
            "regimes": 0,
            "pending_proposals": 0,
        },
        "recent_observations": [],
        "weekly_reviews": [],
        "monthly_reviews": [],
        "latest_weekly_review": {},
        "latest_monthly_review": {},
        "lessons": [],
        "patterns": [],
        "strategies": [],
        "regimes": [],
        "proposals": [],
        "prompt_preview": {"knowledge_context": "", "observations_context": ""},
        "improvement_log_present": False,
    }


def _load_latest_snapshot(data_root: Path, *, profile: dict[str, Any]) -> dict[str, Any]:
    latest = _read_json(data_root / "snapshots" / "latest.json", {})
    return latest or {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "profile": profile["id"],
        "profile_label": profile["label"],
        "portfolio_value": 100000.0,
        "cash": 100000.0,
        "invested": 0.0,
        "total_pnl": 0.0,
        "total_pnl_pct": 0.0,
        "positions": [],
        "position_count": 0,
    }


def _load_trade_history(data_root: Path, *, profile: dict[str, Any]) -> list[dict[str, Any]]:
    completed = _read_json(data_root / "feedback" / "completed_trades.json", [])
    if completed:
        return [
            {
                **item,
                "profile": item.get("profile", profile["id"]),
                "profile_label": item.get("profile_label", profile["label"]),
            }
            for item in completed
            if isinstance(item, dict)
        ]

    trades: list[dict[str, Any]] = []
    journal_dir = data_root / "journal"
    if not journal_dir.exists():
        return trades

    for path in sorted(journal_dir.rglob("*_report.json")):
        payload = _read_json(path, {})
        signals = {
            item.get("symbol"): item
            for item in _safe_list(payload.get("signals"))
            if isinstance(item, dict) and item.get("symbol")
        }
        for trade in _safe_list(payload.get("executed")):
            if not isinstance(trade, dict):
                continue
            signal = signals.get(trade.get("symbol", ""), {})
            trades.append(
                {
                    "timestamp": payload.get("timestamp", ""),
                    "profile": payload.get("profile", {}).get("id", profile["id"]),
                    "profile_label": payload.get("profile", {}).get("label", profile["label"]),
                    "symbol": trade.get("symbol", ""),
                    "action": trade.get("action", ""),
                    "quantity": trade.get("quantity"),
                    "price": trade.get("estimated_price"),
                    "value": trade.get("estimated_value"),
                    "status": trade.get("status", ""),
                    "reasoning": signal.get("reasoning", trade.get("reason", "")),
                    "pnl": trade.get("pnl"),
                }
            )
    return trades


def _copy_interaction_files(data_root: Path, destination_root: Path, interactions: dict[str, Any]) -> None:
    source_root = data_root / "interactions"
    if not source_root.exists():
        return

    copied: set[tuple[Path, Path]] = set()
    destination_root.mkdir(parents=True, exist_ok=True)

    items = []
    if isinstance(interactions, dict):
        items.extend(_safe_list(interactions.get("recent")))
        latest = interactions.get("latest")
        if isinstance(latest, dict):
            items.append(latest)
        latest_by_phase = interactions.get("latest_by_phase", {})
        if isinstance(latest_by_phase, dict):
            phase_items = latest_by_phase.values()
        else:
            phase_items = []
        for value in phase_items:
            if isinstance(value, dict):
                items.append(value)

    for item in items:
        for key in ("prompt_file", "transcript_file", "metadata_file"):
            raw_path = str(item.get(key, "")).strip()
            if not raw_path:
                continue
            if raw_path.startswith("data/profiles/"):
                relative_parts = Path(raw_path).parts
                try:
                    relative = Path(*relative_parts[4:])
                except Exception:
                    continue
            else:
                try:
                    relative = Path(raw_path).relative_to(source_root)
                except ValueError:
                    continue
            source = source_root / relative
            destination = destination_root / relative
            if not source.exists():
                continue
            pair = (source, destination)
            if pair in copied:
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            copied.add(pair)


def _copy_voice_files(data_root: Path, destination_root: Path) -> None:
    source_root = data_root / "voice"
    if not source_root.exists():
        return
    destination_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_root, destination_root, dirs_exist_ok=True)


def _get_latest_report(data_root: Path, phase: str) -> dict[str, Any]:
    path = _get_latest_report_path(data_root, phase=phase, suffix=".json")
    return _read_json(path, {}) if path else {}


def _get_latest_report_path(data_root: Path, *, phase: str, suffix: str) -> Path | None:
    journal_dir = data_root / "journal"
    if not journal_dir.exists():
        return None
    if suffix != ".json":
        json_source = _get_latest_report_path(data_root, phase=phase, suffix=".json")
        if json_source is not None:
            paired = json_source.with_suffix(suffix)
            if paired.exists():
                return paired

    files = sorted(journal_dir.rglob(f"*_{phase}_report{suffix}"))
    if not files:
        return None
    if suffix != ".json":
        return files[-1]
    return max(files, key=_report_score)


def _get_latest_json(directory: Path) -> dict[str, Any]:
    if not directory.exists():
        return {}
    files = sorted(directory.glob("*.json"), reverse=True)
    return _read_json(files[0], {}) if files else {}


def _report_score(path: Path) -> tuple[int, str]:
    score = int(path.stat().st_size)
    payload = _read_json(path, {})
    if isinstance(payload.get("research"), dict) and payload.get("research"):
        score += 5000
    if isinstance(payload.get("screener"), dict) and payload.get("screener"):
        score += 2500
    if payload.get("signals"):
        score += 1500
    if payload.get("executed"):
        score += 1500
    if isinstance(payload.get("portfolio"), dict) and payload.get("portfolio"):
        score += 1000
    return score, path.name


def _load_profile_metadata(data_root: Path, *, profile_id: str) -> dict[str, Any]:
    saved = _read_json(data_root / "profile.json", {})
    metadata = saved if isinstance(saved, dict) else {}
    metadata.setdefault("id", profile_id)
    metadata.setdefault(
        "label",
        DEFAULT_PROFILE_LABELS.get(profile_id, profile_id.replace("-", " ").title()),
    )
    return metadata


def _build_profile_artifacts(profile_id: str, *, multi_profile: bool) -> dict[str, str]:
    base = f"data/profiles/{profile_id}" if multi_profile else "data"
    return {
        "dashboard_json": f"{base}/dashboard.json",
        "latest_json": f"{base}/latest.json",
        "history_json": f"{base}/history.json",
        "trades_json": f"{base}/trades.json",
        "research_json": f"{base}/research.json",
        "llm_json": f"{base}/llm.json",
        "context_json": f"{base}/context.json",
        "knowledge_json": f"{base}/knowledge.json",
        "interactions_json": f"{base}/interactions.json",
        "voice_json": f"{base}/voice.json",
        "latest_voice_json": f"{base}/voice/latest_voice.json",
        "improvement_json": f"{base}/improvement_proposals.json",
        "improvement_md": f"{base}/IMPROVEMENT_PROPOSALS.md",
        "research_report_json": f"{base}/report_research.json",
        "monitor_report_json": f"{base}/report_monitor.json",
        "weekly_report_json": f"{base}/report_weekly.json",
        "monthly_report_json": f"{base}/report_monthly.json",
        "research_report_md": f"{base}/report_research.md",
        "monitor_report_md": f"{base}/report_monitor.md",
    }


def _public_interaction_path(raw_path: str, *, profile_id: str, multi_profile: bool) -> str:
    path_text = str(raw_path or "").replace("\\", "/").strip()
    if not path_text:
        return ""
    if path_text.startswith("data/profiles/"):
        return path_text
    if "interactions/" in path_text:
        suffix = path_text.split("interactions/", 1)[1]
        base = f"data/profiles/{profile_id}" if multi_profile else "data"
        return f"{base}/interactions/{suffix}".replace("//", "/")
    return path_text


def _public_voice_path(raw_path: str, *, profile_id: str, multi_profile: bool) -> str:
    path_text = str(raw_path or "").replace("\\", "/").strip()
    if not path_text:
        return ""
    if path_text.startswith("data/profiles/"):
        return path_text
    if "voice/" in path_text:
        suffix = path_text.split("voice/", 1)[1]
        base = f"data/profiles/{profile_id}" if multi_profile else "data"
        return f"{base}/voice/{suffix}".replace("//", "/")
    return path_text


def _public_repo_path(raw_path: str) -> str:
    return ""


def _empty_profile_bundle(profile_id: str) -> dict[str, Any]:
    profile = {
        "id": profile_id,
        "label": DEFAULT_PROFILE_LABELS.get(profile_id, profile_id.replace("-", " ").title()),
    }
    return {
        "profile": profile,
        "latest": _load_latest_snapshot(Path("."), profile=profile),
        "history": [],
        "trades": [],
        "research": {},
        "llm": {},
        "context": {},
        "knowledge": _empty_knowledge_bundle(),
        "interactions": _empty_interaction_bundle(),
        "voice": _empty_voice_bundle(),
        "reports": {"research": {}, "monitor": {}},
        "artifacts": _build_profile_artifacts(profile_id, multi_profile=True),
    }


def _select_active_profile(profiles: dict[str, dict[str, Any]]) -> str:
    if not profiles:
        return "default"
    return max(
        profiles.items(),
        key=lambda item: (
            str(item[1].get("latest", {}).get("timestamp", "")),
            item[0],
        ),
    )[0]


def _build_comparison_bundle(profiles: dict[str, dict[str, Any]]) -> dict[str, Any]:
    summary: list[dict[str, Any]] = []
    for profile_id, bundle in profiles.items():
        profile = bundle.get("profile", {})
        latest = bundle.get("latest", {})
        llm = bundle.get("llm", {})
        trades = [item for item in bundle.get("trades", []) if isinstance(item, dict)]
        closed_trades = [trade for trade in trades if isinstance(trade.get("pnl"), (int, float))]
        wins = [trade for trade in closed_trades if (trade.get("pnl") or 0) > 0]
        win_rate = round(len(wins) / len(closed_trades) * 100, 1) if closed_trades else None
        summary.append(
            {
                "profile": profile_id,
                "label": profile.get("label", DEFAULT_PROFILE_LABELS.get(profile_id, profile_id.title())),
                "last_updated": latest.get("timestamp"),
                "portfolio_value": latest.get("portfolio_value", 0),
                "total_pnl": latest.get("total_pnl", 0),
                "total_pnl_pct": latest.get("total_pnl_pct", 0),
                "position_count": latest.get("position_count", 0),
                "trade_count": len(trades),
                "closed_trade_count": len(closed_trades),
                "win_rate": win_rate,
                "provider": llm.get("selected_provider") or llm.get("provider"),
                "model": llm.get("selected_model") or llm.get("model"),
            }
        )

    def _leader(key: str) -> str | None:
        if not summary:
            return None
        ranked = sorted(summary, key=lambda item: item.get(key) or 0, reverse=True)
        return ranked[0]["profile"]

    return {
        "summary": summary,
        "leaders": {
            "portfolio_value": _leader("portfolio_value"),
            "total_pnl": _leader("total_pnl"),
            "win_rate": _leader("win_rate"),
            "trade_count": _leader("trade_count"),
        },
    }


def _parse_legacy_news_context(text: str) -> dict[str, Any]:
    parsed: dict[str, Any] = {
        "per_symbol": {},
        "market_headlines": [],
        "news_discoveries": [],
        "hot_stocks": [],
        "finviz": {"analyst_changes": []},
    }
    if not text:
        return parsed

    section = ""
    current_symbol = ""
    current_discovery: dict[str, Any] | None = None
    current_hot_stock: dict[str, Any] | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line == "MARKET HEADLINES:":
            section = "market"
            current_symbol = ""
            continue
        if line == "PER-STOCK NEWS:":
            section = "stock"
            current_symbol = ""
            continue
        if line.startswith("NEWS-DRIVEN DISCOVERIES"):
            section = "discoveries"
            current_discovery = None
            continue
        if line.startswith("CROSS-SOURCE HOT STOCKS"):
            section = "hot"
            current_hot_stock = None
            continue
        if line.startswith("RECENT ANALYST ACTIONS:"):
            section = "analyst"
            continue

        if section == "market" and line.startswith("- ["):
            headline = _parse_legacy_headline(line)
            if headline:
                parsed["market_headlines"].append(headline)
            continue

        if section == "stock":
            match = re.match(
                r"([A-Z][A-Z0-9.-]{0,9}) \(sentiment: ([^,]+), score: ([^,)]+)",
                line,
            )
            if match:
                current_symbol = match.group(1)
                parsed["per_symbol"].setdefault(
                    current_symbol,
                    {
                        "symbol": current_symbol,
                        "news_headlines": [],
                        "sentiment": match.group(2),
                        "sentiment_score": _safe_float(match.group(3)),
                        "source_count": 0,
                    },
                )
                continue
            if line.startswith("- [") and current_symbol:
                headline = _parse_legacy_headline(line)
                if headline:
                    parsed["per_symbol"][current_symbol]["news_headlines"].append(headline)
                continue

        if section == "discoveries":
            match = re.match(
                r"([A-Z][A-Z0-9.-]{0,9}): ([a-z_]+) sentiment \(([+-]?\d+(?:\.\d+)?)\), price ([+-]?\d+(?:\.\d+)?)%",
                line,
            )
            if match:
                current_discovery = {
                    "symbol": match.group(1),
                    "sentiment_label": match.group(2),
                    "news_sentiment": _safe_float(match.group(3)),
                    "price_change_pct": _safe_float(match.group(4)),
                }
                parsed["news_discoveries"].append(current_discovery)
                continue
            if line.startswith("Headline:") and current_discovery is not None:
                current_discovery["top_headline"] = line.replace("Headline:", "", 1).strip()
                continue
            if line.startswith("Why:") and current_discovery is not None:
                current_discovery["discovery_reason"] = line.replace("Why:", "", 1).strip()
                continue

        if section == "hot":
            match = re.match(
                r"([A-Z][A-Z0-9.-]{0,9}): ([^,]+) across (\d+) sources, (\d+) mentions",
                line,
            )
            if match:
                current_hot_stock = {
                    "symbol": match.group(1),
                    "sentiment": match.group(2),
                    "source_count": int(match.group(3)),
                    "mention_count": int(match.group(4)),
                    "reasons": [],
                }
                parsed["hot_stocks"].append(current_hot_stock)
                continue
            if line.startswith("-") and current_hot_stock is not None:
                current_hot_stock["reasons"].append(line[1:].strip())
                continue

        if section == "analyst":
            match = re.match(
                r"([A-Z][A-Z0-9.-]{0,9}): (.+?) - (.+?) \((.+?) -> (.+?)\)",
                line.replace("—", "-"),
            )
            if match:
                parsed["finviz"]["analyst_changes"].append(
                    {
                        "symbol": match.group(1),
                        "firm": match.group(2),
                        "action": match.group(3),
                        "from_grade": match.group(4),
                        "to_grade": match.group(5),
                    }
                )

    for summary in parsed["per_symbol"].values():
        headlines = summary.get("news_headlines", [])
        summary["source_count"] = len(
            {
                item.get("publisher") or item.get("source")
                for item in headlines
                if item.get("publisher") or item.get("source")
            }
        )

    return parsed


def _parse_legacy_headline(line: str) -> dict[str, Any] | None:
    match = re.match(r"- \[([^\]]+)\] (.+?)(?: \[([+-]?\d+(?:\.\d+)?)\])?$", line)
    if not match:
        return None
    return {
        "title": match.group(2).strip(),
        "publisher": match.group(1).strip(),
        "source": match.group(1).strip(),
        "summary": "",
        "url": "",
        "sentiment": _safe_float(match.group(3)),
        "category": "headline",
    }


def _safe_float(value: str | None) -> float:
    if value is None:
        return 0.0
    try:
        return float(str(value).replace("+", ""))
    except ValueError:
        return 0.0


def _normalize_context(
    saved_context: dict[str, Any],
    report_payload: dict[str, Any],
    report: dict[str, Any],
) -> dict[str, Any]:
    context = dict(saved_context) if isinstance(saved_context, dict) else {}
    prompt = dict(context.get("prompt_sections") or {})
    news_inputs = dict(prompt.get("news_inputs") or {})
    legacy_news = _parse_legacy_news_context(prompt.get("news_context", ""))

    if not news_inputs:
        news_inputs = {
            "per_symbol": report_payload.get("news", {}) or {},
            "market_headlines": report_payload.get("market_headlines", []) or [],
            "news_discoveries": report_payload.get("news_discoveries", []) or [],
            "hot_stocks": report_payload.get("hot_stocks", []) or [],
            "finviz": report_payload.get("finviz", {}) or {},
        }
    if not news_inputs.get("per_symbol"):
        news_inputs["per_symbol"] = legacy_news.get("per_symbol", {})
    if not news_inputs.get("market_headlines"):
        news_inputs["market_headlines"] = legacy_news.get("market_headlines", [])
    if not news_inputs.get("news_discoveries"):
        news_inputs["news_discoveries"] = legacy_news.get("news_discoveries", [])
    if not news_inputs.get("hot_stocks"):
        news_inputs["hot_stocks"] = legacy_news.get("hot_stocks", [])
    if not news_inputs.get("finviz"):
        news_inputs["finviz"] = legacy_news.get("finviz", {})

    prompt["news_inputs"] = news_inputs
    if not prompt.get("market_context"):
        prompt["market_context"] = report_payload.get("market_context", {}) or {}
    if not prompt.get("market_data"):
        prompt["market_data"] = report_payload.get("market_data", {}) or {}
    if not prompt.get("screener_context"):
        prompt["screener_context"] = (
            report_payload.get("screener_results", {}) or report.get("screener", {}) or {}
        )
    context["prompt_sections"] = prompt
    if not context.get("symbols"):
        context["symbols"] = report_payload.get("symbols", []) or []
    if not context.get("provider"):
        context["provider"] = _extract_llm_meta(report_payload).get("provider", "")
    if not context.get("model"):
        context["model"] = _extract_llm_meta(report_payload).get("model", "")
    if not context.get("llm_meta"):
        context["llm_meta"] = _extract_llm_meta(report_payload)
    return context


def _normalize_llm(
    analytics: dict[str, Any],
    context: dict[str, Any],
    research: dict[str, Any],
) -> dict[str, Any]:
    llm = _deep_merge(_extract_llm_meta(research), analytics)
    if "provider" not in llm and context.get("provider"):
        llm["provider"] = context["provider"]
    if "model" not in llm and context.get("model"):
        llm["model"] = context["model"]
    return llm


def _extract_report_payload(report: dict[str, Any]) -> dict[str, Any]:
    payload = report.get("research")
    return payload if isinstance(payload, dict) else {}


def _extract_research_analysis(payload: dict[str, Any]) -> dict[str, Any]:
    research = payload.get("research")
    return research if isinstance(research, dict) else {}


def _extract_llm_meta(source: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(source, dict):
        return {}
    meta = source.get("_meta") or source.get("llm_meta")
    return meta if isinstance(meta, dict) else {}


def _load_recent_json_series(directory: Path, pattern: str, *, limit: int) -> list[dict[str, Any]]:
    if not directory.exists():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(directory.glob(pattern), reverse=True)[:limit]:
        payload = _read_json(path, {})
        if isinstance(payload, dict):
            records.append(payload)
    return records


def _flatten_strategy_effectiveness(payload: dict[str, Any]) -> list[dict[str, Any]]:
    strategies: list[dict[str, Any]] = []
    by_regime = payload.get("by_regime", {})
    if isinstance(by_regime, dict) and by_regime:
        aggregate: dict[str, dict[str, Any]] = {}
        for regime, strategies_payload in by_regime.items():
            if not isinstance(strategies_payload, dict):
                continue
            for name, details in strategies_payload.items():
                if not isinstance(details, dict):
                    continue
                bucket = aggregate.setdefault(
                    name,
                    {
                        "name": name,
                        "win_rates": [],
                        "avg_returns": [],
                        "best_regime": "",
                        "best_win_rate": -1.0,
                    },
                )
                win_rate = details.get("win_rate")
                avg_return = details.get("avg_return", details.get("avg_pnl"))
                if isinstance(win_rate, (int, float)):
                    bucket["win_rates"].append(float(win_rate))
                    if float(win_rate) > float(bucket["best_win_rate"]):
                        bucket["best_win_rate"] = float(win_rate)
                        bucket["best_regime"] = str(regime)
                if isinstance(avg_return, (int, float)):
                    bucket["avg_returns"].append(float(avg_return))

        for name, bucket in aggregate.items():
            win_rates = bucket.get("win_rates", [])
            avg_returns = bucket.get("avg_returns", [])
            strategies.append(
                {
                    "name": name,
                    "win_rate": (sum(win_rates) / len(win_rates)) if win_rates else None,
                    "avg_return": (sum(avg_returns) / len(avg_returns)) if avg_returns else None,
                    "best_regime": bucket.get("best_regime") or None,
                }
            )
        strategies.sort(key=lambda item: num_or_zero(item.get("win_rate")), reverse=True)
        return strategies[:8]

    for name, details in payload.items():
        if name == "last_updated" or not isinstance(details, dict):
            continue
        strategies.append(
            {
                "name": name,
                "win_rate": details.get("win_rate"),
                "avg_return": details.get("avg_return"),
                "best_regime": details.get("best_regime"),
            }
        )
    strategies.sort(key=lambda item: num_or_zero(item.get("win_rate")), reverse=True)
    return strategies[:8]


def _flatten_regime_library(payload: dict[str, Any]) -> list[dict[str, Any]]:
    regimes_payload = payload.get("regimes", {})
    if not isinstance(regimes_payload, dict) or not regimes_payload:
        top_level = {
            key: value
            for key, value in payload.items()
            if key != "regimes" and isinstance(value, dict)
        }
        regimes_payload = top_level
    if not isinstance(regimes_payload, dict):
        return []

    regimes: list[dict[str, Any]] = []
    for name, details in sorted(regimes_payload.items()):
        if not isinstance(details, dict):
            continue
        regimes.append(
            {
                "name": name,
                "preferred_strategies": _safe_list(details.get("preferred_strategies")),
                "avoid_strategies": _safe_list(details.get("avoid_strategies")),
                "rules": _safe_list(details.get("rules")),
                "position_size_modifier": details.get("position_size_modifier"),
                "stop_loss_modifier": details.get("stop_loss_modifier"),
            }
        )
    return regimes


def _flatten_improvement_proposals(entries: Any) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    if not isinstance(entries, list):
        return flattened

    for entry in reversed(entries[-8:]):
        if not isinstance(entry, dict):
            continue
        if {"title", "description", "priority"} & set(entry.keys()):
            flattened.append(
                {
                    "date": entry.get("date", ""),
                    "priority": entry.get("priority", "medium"),
                    "category": entry.get("category", "other"),
                    "title": entry.get("title", "Untitled proposal"),
                    "description": entry.get("description", ""),
                    "expected_impact": entry.get("expected_impact", ""),
                }
            )
            continue
        date = str(entry.get("date", "")).strip()
        for proposal in _safe_list(entry.get("proposals")):
            if not isinstance(proposal, dict):
                continue
            flattened.append(
                {
                    "date": date,
                    "priority": proposal.get("priority", "medium"),
                    "category": proposal.get("category", "other"),
                    "title": proposal.get("title", "Untitled proposal"),
                    "description": proposal.get("description", ""),
                    "expected_impact": proposal.get("expected_impact", ""),
                }
            )
    return flattened[:10]


def _copy_latest_report_artifact(
    data_root: Path,
    destination: Path,
    *,
    phase: str,
    suffix: str,
) -> None:
    source = _get_latest_report_path(data_root, phase=phase, suffix=suffix)
    if source:
        destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")


def _read_json(path: Path | None, default: Any) -> Any:
    if path is None or not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _copy_if_exists(source: Path, destination: Path) -> None:
    if source.exists():
        destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def num_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged
