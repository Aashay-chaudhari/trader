"""Generate the static GitHub Pages dashboard and JSON bundles."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from textwrap import dedent
from typing import Any

from agent_trader.utils.profiles import DEFAULT_PROFILE_LABELS


DASHBOARD_HTML = dedent(
    """
    <!doctype html>
    <html lang="en">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width,initial-scale=1">
      <title>Agent Trader Control Center</title>
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
        @media (max-width:1080px){.hero-grid,.split,.newscols,.context{grid-template-columns:1fr}}@media (max-width:760px){.page{padding:16px 12px 28px}.hero{padding:20px}}
      </style>
    </head>
    <body>
      <div class="page">
        <header class="hero">
          <div class="hero-grid">
            <div>
              <div class="pill accent">Agent Trader Control Center</div>
              <h1>What the system saw before it acted</h1>
              <p id="heroSummary">Latest research, workflow context, and article-level catalysts from the trading pipeline.</p>
              <div class="meta" id="heroMeta"></div>
            </div>
            <div class="buttons">
              <a class="btn" id="runLink" href="data/report_research.md" target="_blank" rel="noreferrer">Open latest report</a>
              <a class="btn" id="researchLink" href="data/report_research.md" target="_blank" rel="noreferrer">Research markdown</a>
              <a class="btn" id="monitorLink" href="data/report_monitor.md" target="_blank" rel="noreferrer">Monitor markdown</a>
              <a class="btn" id="contextLink" href="data/context.json" target="_blank" rel="noreferrer">Prompt context JSON</a>
              <a class="btn" id="llmLink" href="data/llm.json" target="_blank" rel="noreferrer">LLM analytics JSON</a>
              <a class="btn" id="dashboardLink" href="data/dashboard.json" target="_blank" rel="noreferrer">Dashboard bundle</a>
            </div>
          </div>
        </header>

        <section class="panel">
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

        <section class="panel">
          <div class="section"><div><h2>Workflow Map</h2><p>Hover a stage to inspect the inputs that survived into the latest run.</p></div></div>
          <div class="workflow" id="workflow"></div>
        </section>

        <section class="split">
          <div class="panel">
            <div class="section"><div><h2>Portfolio Curve</h2><p>Portfolio snapshots archived across workflow runs.</p></div></div>
            <div class="chart"><canvas id="valueChart"></canvas></div>
          </div>
          <div class="panel">
            <div class="section"><div><h2>Run Snapshot</h2><p>Provider, model, phases, and execution summary.</p></div></div>
            <div class="mini" id="runSummary"></div>
          </div>
        </section>

        <section class="panel">
          <div class="section"><div><h2>Decision board</h2><p>Recommendation, trade plan, shortlist rationale, and the articles the LLM had while making the call.</p></div></div>
          <div class="decisions" id="decisionBoard"></div>
        </section>

        <section class="panel">
          <div class="section"><div><h2>News influence explorer</h2><p>Market headlines, discoveries, hot stocks, and analyst changes.</p></div></div>
          <div class="newscols">
            <div class="stack">
              <div class="card"><h3>Market headlines</h3><div id="marketHeadlines"></div></div>
              <div class="card"><h3>News discoveries</h3><div id="discoveries"></div></div>
            </div>
            <div class="stack">
              <div class="card"><h3>Cross-source hot stocks</h3><div id="hotStocks"></div></div>
              <div class="card"><h3>Analyst tape</h3><div id="analystTape"></div></div>
            </div>
          </div>
        </section>

        <section class="panel">
          <div class="section"><div><h2>Prompt context explorer</h2><p>Market regime, shortlist rationale, saved artifacts, and LLM telemetry.</p></div></div>
          <div class="context">
            <div class="stack">
              <div class="card"><h3>Market regime</h3><p id="marketSummary">No market summary yet.</p><div class="mini" id="marketCards" style="margin-top:14px"></div></div>
              <div class="card"><h3>Artifact memory</h3><pre class="mono" id="artifactMemory">No saved artifacts yet.</pre></div>
              <div class="card"><h3>LLM telemetry</h3><div class="mini" id="llmSummary"></div><div class="stack" id="providerAttempts" style="margin-top:14px"></div></div>
            </div>
            <div class="stack">
              <div class="card"><h3>Screener rationale</h3><div class="table"><table><thead><tr><th>Symbol</th><th>Source</th><th>Score</th><th>Why</th></tr></thead><tbody id="shortlistTable"></tbody></table></div></div>
              <div class="card"><h3>Open positions</h3><div class="table"><table><thead><tr><th>Symbol</th><th>Shares</th><th>Avg Cost</th><th>Current</th><th>PnL</th></tr></thead><tbody id="positionsTable"></tbody></table></div></div>
            </div>
          </div>
        </section>

        <section class="panel">
          <div class="section"><div><h2>Trade history</h2><p>Journal-backed trade log with execution status and stored reasoning.</p></div></div>
          <div class="table"><table><thead><tr><th>Date</th><th>Symbol</th><th>Action</th><th>Qty</th><th>Price</th><th>Value</th><th>Status</th><th>Reasoning</th></tr></thead><tbody id="tradesTable"></tbody></table></div>
        </section>
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
        const empty=msg=>`<div class="empty">${esc(msg)}</div>`;
        const hover=(title,lines)=>{const items=arr(lines).filter(Boolean);return items.length?`<div class="hover"><strong>${esc(title)}</strong><ul>${items.map(x=>`<li>${esc(x)}</li>`).join("")}</ul></div>`:""};
        const listBlock=(items,fallback)=>{const vals=arr(items).filter(Boolean);return `<ul>${(vals.length?vals:[fallback]).map(x=>`<li>${esc(x)}</li>`).join("")}</ul>`};
        const miniCard=(label,value)=>`<div class="tile"><strong>${esc(label)}</strong><span>${esc(value)}</span></div>`;
        const articleCard=a=>{const url=safeUrl(a.url),pub=a.publisher||a.source||"Unknown source",sent=num(a.sentiment);const body=`<div class="article-title">${esc(truncate(a.title||"Untitled",110))}</div><div class="article-meta"><span>${esc(pub)}</span><span>${esc(dateText(a.published))}</span><span>${esc(sent===null?"Context item":"Sentiment "+sent.toFixed(1))}</span></div><div class="article-copy">${esc(truncate(a.summary||"No article summary captured.",180))}</div>`;return `<div class="article">${url?`<a href="${esc(url)}" target="_blank" rel="noreferrer">${body}</a>`:`<div class="body">${body}</div>`}${hover(a.title||"Article context",[pub,dateText(a.published),a.category?`Category: ${a.category}`:"",sent===null?"":`Sentiment: ${sent.toFixed(2)}`,a.summary||"No article summary captured."])}</div>`};
        const articleGrid=(items,msg)=>{const list=arr(items).slice(0,6);return list.length?`<div class="articles">${list.map(articleCard).join("")}</div>`:empty(msg)};
        const stackCards=(items,msg)=>{const list=arr(items);return list.length?`<div class="stack">${list.join("")}</div>`:empty(msg)};
        const sentCls=v=>{const n=num(v);return n===null?"neu":n>0.1?"pos":n<-0.1?"neg":"neu"};
        const sentLabel=v=>{const n=num(v);return n===null?"?":n>0?"+"+ n.toFixed(2):n.toFixed(2)};
        const headlineRow=a=>{const sent=num(a.sentiment),src=a.source||"",pub=a.publisher||src||"?",cat=a.category||"headline",url=safeUrl(a.url),title=a.title||"Untitled";return `<div class="headline-row">`+`<div class="hl-sent ${sentCls(sent)}">${sentLabel(sent)}</div>`+`<div class="hl-body">`+`<div class="hl-title">${url?`<a href="${esc(url)}" target="_blank" rel="noreferrer" style="color:inherit;text-decoration:none">${esc(truncate(title,120))}</a>`:esc(truncate(title,120))}</div>`+`<div class="hl-meta"><span class="source-tag">${esc(src)}</span>${esc(pub)} &middot; ${esc(cat)} &middot; ${esc(dateText(a.published))}</div>`+`</div></div>`};
        const headlineList=(items,msg)=>{const list=arr(items);return list.length?`<div class="headline-list">${list.map(headlineRow).join("")}</div>`:empty(msg)};
        const sourceBreakdown=items=>{const counts={};arr(items).forEach(a=>{const s=a.source||"unknown";counts[s]=(counts[s]||0)+1});return Object.keys(counts).length?`<div class="source-breakdown">${Object.entries(counts).sort((a,b)=>b[1]-a[1]).map(([s,c])=>`<span class="src-chip"><span class="source-tag">${esc(s)}</span>${c} article${c>1?"s":""}</span>`).join("")}</div>`:""};
        const labelFromId=id=>String(id||"default").replace(/[-_]+/g," ").replace(/\\b\\w/g,m=>m.toUpperCase());

        let dashboardBundle=null;
        let selectedProfile=null;
        let valueChartInstance=null;

        function bundleProfiles(bundle){
          const profiles=obj(bundle.profiles);
          if(Object.keys(profiles).length)return profiles;
          const fallbackProfile=obj(bundle.profile);
          const profileId=fallbackProfile.id||bundle.active_profile||"default";
          return {[profileId]:{profile:{id:profileId,label:fallbackProfile.label||labelFromId(profileId)},latest:obj(bundle.latest),history:arr(bundle.history),trades:arr(bundle.trades),research:obj(bundle.research),llm:obj(bundle.llm),context:obj(bundle.context),reports:obj(bundle.reports),artifacts:obj(bundle.artifacts)}};
        }

        function comparisonSummary(bundle,profiles){
          const summary=arr(obj(bundle.comparison).summary);
          if(summary.length)return summary;
          return Object.entries(profiles).map(([profileId,profileBundle])=>{const latest=obj(profileBundle.latest),llm=obj(profileBundle.llm),trades=arr(profileBundle.trades),closed=trades.filter(t=>typeof t==="object"&&typeof t.pnl==="number"),wins=closed.filter(t=>(t.pnl||0)>0);return {profile:profileId,label:obj(profileBundle.profile).label||labelFromId(profileId),last_updated:latest.timestamp,portfolio_value:latest.portfolio_value,total_pnl:latest.total_pnl,total_pnl_pct:latest.total_pnl_pct,trade_count:trades.length,closed_trade_count:closed.length,win_rate:closed.length?Math.round(wins.length/closed.length*1000)/10:null,provider:llm.selected_provider||llm.provider,model:llm.selected_model||llm.model};});
        }

        function initialProfile(bundle,profiles){
          if(bundle.active_profile&&profiles[bundle.active_profile])return bundle.active_profile;
          return Object.keys(profiles)[0]||"default";
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

        function updateLinks(profileBundle,runUrl){
          const artifacts=obj(profileBundle.artifacts);
          const researchPath=artifacts.research_report_md||"data/report_research.md";
          const monitorPath=artifacts.monitor_report_md||"data/report_monitor.md";
          document.getElementById("researchLink").href=researchPath;
          document.getElementById("monitorLink").href=monitorPath;
          document.getElementById("contextLink").href=artifacts.context_json||"data/context.json";
          document.getElementById("llmLink").href=artifacts.llm_json||"data/llm.json";
          document.getElementById("dashboardLink").href=artifacts.dashboard_json||"data/dashboard.json";
          const runLink=document.getElementById("runLink");
          if(runUrl){runLink.href=runUrl;runLink.textContent="Open GitHub Actions run";}else{runLink.href=researchPath;runLink.textContent="Open latest report";}
        }

        function renderProfile(profileBundle,bundle){
          const profile=obj(profileBundle.profile), latest=obj(profileBundle.latest), trades=arr(profileBundle.trades), reports=obj(profileBundle.reports), reportResearch=obj(reports.research), reportMonitor=obj(reports.monitor), reportPayload=obj(reportResearch.research);
          const research=Object.keys(obj(profileBundle.research)).length?obj(profileBundle.research):obj(reportPayload.research), context=obj(profileBundle.context), prompt=obj(context.prompt_sections), newsInputs=obj(prompt.news_inputs), perSymbol=obj(newsInputs.per_symbol), screener=obj(prompt.screener_context), market=obj(prompt.market_context);
          const llm=Object.keys(obj(profileBundle.llm)).length?obj(profileBundle.llm):(obj(research._meta)||obj(context.llm_meta));
          const shortlist=arr(screener.shortlist), marketHeadlines=arr(newsInputs.market_headlines), discoveries=arr(newsInputs.news_discoveries), hotStocks=arr(newsInputs.hot_stocks), analystChanges=arr(obj(newsInputs.finviz).analyst_changes), positions=arr(latest.positions);
          const totalArticles=Object.values(perSymbol).reduce((s,v)=>s+arr(obj(v).news_headlines).length,0)+marketHeadlines.length;
          const best=arr(research.best_opportunities), signals=arr(reportMonitor.signals), approved=arr(obj(reportMonitor.risk).approved_trades), rejected=arr(obj(reportMonitor.risk).rejected_trades), executed=arr(reportMonitor.executed);

          const runUrl=llm.runtime?.github?.run_url||context.llm_meta?.runtime?.github?.run_url||"";
          updateLinks(profileBundle,runUrl);
          document.getElementById("heroSummary").textContent=[`${profile.label||labelFromId(profile.id)} is active.`,research.market_summary,research.market_regime?`Regime: ${research.market_regime}`:"",best.length?`Top ideas: ${best.join(", ")}`:""].filter(Boolean).join(" | ")||"Latest research and workflow context loaded.";
          document.getElementById("heroMeta").innerHTML=[["Strategist",profile.label||labelFromId(profile.id)],["Last Updated",dateText(latest.timestamp||bundle.generated_at)],["Provider",llm.selected_provider||llm.provider||context.provider||"-"],["Model",llm.selected_model||llm.model||context.model||"-"],["Symbols",String(arr(context.symbols).length||Object.keys(perSymbol).length||Object.keys(obj(research.stocks)).length)],["Prompt Articles",String(totalArticles)],["Best Opportunities",best.join(", ")||"None"]].map(([l,v])=>`<div class="card" style="padding:14px"><div class="label">${esc(l)}</div><div>${esc(v)}</div></div>`).join("");
          document.getElementById("portfolioValue").textContent=fmtMoney(latest.portfolio_value); document.getElementById("cashValue").textContent=fmtMoney(latest.cash); document.getElementById("positionCount").textContent=String(latest.position_count||positions.length); document.getElementById("tradeCount").textContent=String(trades.length); document.getElementById("articleCount").textContent=String(totalArticles); document.getElementById("modeNote").textContent=trades.some(t=>(t.status||"").toLowerCase()!=="dry_run")?"Live execution detected":"Dry-run history";
          const pnl=document.getElementById("totalPnl"); pnl.textContent=signMoney(latest.total_pnl); pnl.className="value "+cls(latest.total_pnl); const pnlPct=document.getElementById("totalPnlPct"); pnlPct.textContent=fmtPct(latest.total_pnl_pct); pnlPct.className="sub "+cls(latest.total_pnl_pct);

          document.getElementById("workflow").innerHTML=[
            {title:"News",summary:"Headlines, filings, and analyst changes were gathered before research.",metric:String(totalArticles),lines:[`${marketHeadlines.length} market headlines`,`${discoveries.length} discoveries`,`${hotStocks.length} hot stocks`,...marketHeadlines.slice(0,3).map(x=>x.title||"")]},
            {title:"Screener",summary:"News and technical context narrowed the universe into a shortlist.",metric:String(shortlist.length),lines:[`Total scanned: ${screener.total_scanned||0}`,`Candidates found: ${screener.candidates_found||0}`,`News boosts: ${screener.news_discovered||0}`,...shortlist.slice(0,3).map(x=>`${x.symbol||"?"} - ${x.discovery_reason||x.top_headline||x.source||"technical setup"}`)]},
            {title:"Research",summary:"The LLM returned the structured thesis and trade plan.",metric:String(best.length),lines:[`Overall sentiment: ${research.overall_sentiment||"unknown"}`,`Market regime: ${research.market_regime||market.market_regime||"unknown"}`,`Provider: ${llm.selected_provider||llm.provider||context.provider||"-"}`,`Model: ${llm.selected_model||llm.model||context.model||"-"}`,`Total tokens: ${llm.usage?.total_tokens??"n/a"}`]},
            {title:"Monitor / Execution",summary:"Signals, approvals, and trades were archived for follow-up.",metric:String(executed.length),lines:[`${signals.length} signals`,`${approved.length} approved trades`,`${rejected.length} rejected trades`,...executed.slice(0,3).map(x=>`${x.symbol||"?"} ${String((x.action||"").toUpperCase())} ${x.quantity||0}`)]}
          ].map(x=>`<article class="stage"><div class="top"><div><div class="label">${esc(x.title)}</div><p>${esc(x.summary)}</p></div><div class="metric">${esc(x.metric)}</div></div>${hover(x.title+" details",x.lines)}</article>`).join("");

          document.getElementById("runSummary").innerHTML=[["Research Run",reportResearch.run_id||"-"],["Research Time",dateText(reportResearch.timestamp||context.timestamp)],["Monitor Time",dateText(reportMonitor.timestamp)],["Signals",String(signals.length)],["Approved",String(approved.length)],["Executed",String(executed.length)],["Quota Note",llm.quota_note||"No quota note recorded"],["Platform",llm.runtime?.platform||"-"]].map(([l,v])=>miniCard(l,String(v))).join("");

          const researchStocks=obj(research.stocks), shortlistMap=Object.fromEntries(shortlist.map(x=>[x.symbol,x])), symbols=[]; [...best,...Object.keys(researchStocks),...Object.keys(perSymbol),...shortlist.map(x=>x.symbol)].forEach(s=>{if(s&&!symbols.includes(s))symbols.push(s)});
          document.getElementById("decisionBoard").innerHTML=symbols.length?symbols.map(symbol=>{const analysis=obj(researchStocks[symbol]), news=obj(perSymbol[symbol]), pick=obj(shortlistMap[symbol]), plan=obj(analysis.trade_plan), rec=analysis.recommendation||"watch", headlines=arr(news.news_headlines), srcCount=news.source_count||0; return `<article class="decision"><div class="top"><div><h3>${esc(symbol)}</h3><p>${esc(analysis.technical_setup||analysis.news_summary||pick.discovery_reason||"No narrative stored for this symbol.")}</p></div><span class="pill ${rec==="buy"?"good":rec==="sell"?"bad":"warn"}">${esc(rec)}</span></div><div class="mini">${miniCard("Sentiment",analysis.sentiment||news.sentiment||"neutral")}${miniCard("Confidence",analysis.confidence!==undefined?Math.round(Number(analysis.confidence)*100)+"%":"-")}${miniCard("News Impact",analysis.news_impact||"none")}${miniCard("Sources",String(srcCount)+" provider"+(srcCount!==1?"s":""))}${miniCard("Headlines",String(headlines.length))}${miniCard("Entry",fmtMoney(plan.entry))}${miniCard("Stop",fmtMoney(plan.stop_loss))}${miniCard("Target",fmtMoney(plan.target))}${miniCard("R / R",plan.risk_reward_ratio!==undefined?Number(plan.risk_reward_ratio).toFixed(2):"-")}${miniCard("Shortlist",pick.source||"research")}</div>${sourceBreakdown(headlines)}<div class="list"><strong>Why it was interesting</strong>${listBlock([pick.discovery_reason||pick.top_headline||analysis.news_summary||"No shortlist rationale captured.",`Score: ${pick.score!==undefined?Number(pick.score).toFixed(3):"n/a"} | Source: ${pick.source||"n/a"}`],"No shortlist rationale captured.")}</div><div class="list"><strong>Key observations</strong>${listBlock(analysis.key_observations,"No observations were returned.")}</div><div class="list"><strong>Catalysts</strong>${listBlock(analysis.catalysts,"No catalysts were listed.")}</div><div class="list"><strong>Risks</strong>${listBlock(analysis.risks,"No explicit risks were listed.")}</div><div class="list"><strong>All headlines that influenced this decision (${headlines.length})</strong>${headlineList(headlines,"No symbol-specific articles were captured for this decision.")}</div></article>`}).join(""):empty("No research decisions available yet.");

          document.getElementById("marketHeadlines").innerHTML=articleGrid(marketHeadlines,"No market headlines were captured in the latest run.");
          document.getElementById("discoveries").innerHTML=stackCards(discoveries.map(x=>`<div class="tile"><strong>${esc(x.symbol||"?")}</strong><span>${esc(x.discovery_reason||x.top_headline||"No discovery reason captured.")}</span><div class="sub">${esc((x.sentiment_label||"mixed")+" | "+(x.news_sentiment!==undefined?Number(x.news_sentiment).toFixed(2):"n/a"))}</div></div>`),"No news-driven discoveries were stored for the latest run.");
          document.getElementById("hotStocks").innerHTML=stackCards(hotStocks.map(x=>`<div class="tile"><strong>${esc(x.symbol||"?")}</strong><span>${esc((x.sentiment||"mixed")+" across "+String(x.source_count||0)+" sources")}</span><div class="sub">${esc(truncate(arr(x.reasons).join(" | "),160)||"No reasons captured.")}</div></div>`),"No cross-source hot stocks were persisted.");
          document.getElementById("analystTape").innerHTML=stackCards(analystChanges.map(x=>`<div class="tile"><strong>${esc(x.symbol||"?")}</strong><span>${esc((x.firm||"?")+": "+(x.action||"?"))}</span><div class="sub">${esc((x.from_grade||"?")+" -> "+(x.to_grade||"?"))}</div></div>`),"No analyst changes were captured.");

          document.getElementById("marketSummary").textContent=research.market_summary||"No market summary available.";
          const marketCards=[]; if(market.market_regime)marketCards.push(["Regime",market.market_regime]); if(market.sp500?.change_pct!==undefined)marketCards.push(["SPY",fmtPct(market.sp500.change_pct)]); if(market.nasdaq?.change_pct!==undefined)marketCards.push(["QQQ",fmtPct(market.nasdaq.change_pct)]); if(market.vix?.value!==undefined)marketCards.push(["VIX",String(market.vix.value)]); if(market.treasury_10y?.yield_pct!==undefined)marketCards.push(["10Y Yield",market.treasury_10y.yield_pct+"%"]); if(arr(market.sector_leaders).length)marketCards.push(["Leaders",arr(market.sector_leaders).map(x=>`${x.sector} ${fmtPct(x.daily_pct)}`).join(", ")]); if(arr(market.sector_laggards).length)marketCards.push(["Laggards",arr(market.sector_laggards).map(x=>`${x.sector} ${fmtPct(x.daily_pct)}`).join(", ")]);
          document.getElementById("marketCards").innerHTML=marketCards.length?marketCards.map(([l,v])=>miniCard(l,v)).join(""):empty("No market regime cards were captured.");
          document.getElementById("artifactMemory").textContent=prompt.artifact_context||"No saved artifacts yet.";
          document.getElementById("llmSummary").innerHTML=[["Provider",llm.selected_provider||llm.provider||context.provider||"-"],["Model",llm.selected_model||llm.model||context.model||"-"],["Input Tokens",llm.usage?.input_tokens??"-"],["Output Tokens",llm.usage?.output_tokens??"-"],["Total Tokens",llm.usage?.total_tokens??"-"],["Capacity Before Request",String(llm.rate_limits?.estimates?.tokens_remaining_before_request_estimate??llm.rate_limits?.estimates?.input_tokens_remaining_before_request_estimate??"n/a")],["Latency",llm.duration_ms?`${Math.round(Number(llm.duration_ms))} ms`:"-"],["Run ID",llm.runtime?.github?.run_id||"-"],["Request ID",llm.request_id||"-"],["Quota Note",llm.quota_note||"No quota note recorded"]].map(([l,v])=>miniCard(l,String(v))).join("");
          document.getElementById("providerAttempts").innerHTML=arr(llm.attempts).length?arr(llm.attempts).map(x=>`<div class="tile"><strong>${esc((x.provider||"?")+" / "+(x.model||"?"))}</strong><span>${esc("Status: "+(x.status||"unknown"))}</span><div class="sub">${esc(x.duration_ms!==undefined?`${x.duration_ms} ms`:"duration n/a")}${x.error?` | ${esc(truncate(String(x.error),90))}`:""}</div></div>`).join(""):empty("No provider attempts were recorded.");

          document.getElementById("shortlistTable").innerHTML=shortlist.length?shortlist.map(x=>`<tr><td><strong>${esc(x.symbol||"")}</strong></td><td>${esc(x.source||"")}</td><td>${x.score!==undefined?Number(x.score).toFixed(3):"-"}</td><td>${esc(x.discovery_reason||x.top_headline||"Technical move only")}</td></tr>`).join(""):`<tr><td colspan="4">${empty("No shortlist stored in latest context.")}</td></tr>`;
          document.getElementById("positionsTable").innerHTML=positions.length?positions.map(x=>`<tr><td><strong>${esc(x.symbol)}</strong></td><td>${esc(x.shares)}</td><td>${fmtMoney(x.avg_cost)}</td><td>${fmtMoney(x.current_price)}</td><td class="${cls(x.unrealized_pnl)}">${signMoney(x.unrealized_pnl)}</td></tr>`).join(""):`<tr><td colspan="5">${empty("No positions yet.")}</td></tr>`;
          document.getElementById("tradesTable").innerHTML=trades.length?trades.slice(-60).reverse().map(x=>`<tr><td>${esc(dateText(x.timestamp))}</td><td><strong>${esc(x.symbol||"")}</strong></td><td>${esc(String((x.action||"").toUpperCase()))}</td><td>${esc(x.quantity??"-")}</td><td>${fmtMoney(x.price)}</td><td>${fmtMoney(x.value)}</td><td>${esc(x.status||"-")}</td><td>${esc(x.reasoning||x.reason||"-")}</td></tr>`).join(""):`<tr><td colspan="8">${empty("No trades yet.")}</td></tr>`;

          if(valueChartInstance){valueChartInstance.destroy();valueChartInstance=null;}
          const history=arr(profileBundle.history); if(history.length&&window.Chart){valueChartInstance=new Chart(document.getElementById("valueChart").getContext("2d"),{type:"line",data:{labels:history.map(x=>dateText(x.timestamp)),datasets:[{label:"Portfolio Value",data:history.map(x=>x.portfolio_value),borderColor:"#7dd3fc",backgroundColor:"rgba(125,211,252,.12)",fill:true,tension:.25,borderWidth:2,pointRadius:2}]},options:{maintainAspectRatio:false,plugins:{legend:{labels:{color:"#95a7ca"}}},scales:{x:{ticks:{color:"#95a7ca",maxTicksLimit:8},grid:{color:"rgba(126,166,235,.08)"}},y:{ticks:{color:"#95a7ca",callback:v=>"$"+Number(v).toLocaleString()},grid:{color:"rgba(126,166,235,.08)"}}}}});}
        }

        function renderDashboard(){
          const profiles=bundleProfiles(dashboardBundle||{});
          if(!selectedProfile||!profiles[selectedProfile])selectedProfile=initialProfile(dashboardBundle||{},profiles);
          renderComparison(dashboardBundle||{},profiles);
          renderProfile(profiles[selectedProfile]||Object.values(profiles)[0]||{},dashboardBundle||{});
        }

        window.selectProfile=profileId=>{selectedProfile=profileId;renderDashboard();};

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

    profile_roots = _discover_profile_roots(data_root)
    bundle = _build_dashboard_bundle(data_root, profile_roots=profile_roots)
    (docs_root / "index.html").write_text(DASHBOARD_HTML, encoding="utf-8")
    _write_json(data_out / "dashboard.json", bundle)
    _write_json(data_out / "latest.json", bundle["latest"])
    _write_json(data_out / "history.json", bundle["history"])
    _write_json(data_out / "trades.json", bundle["trades"])
    _write_json(data_out / "research.json", bundle["research"])
    _write_json(data_out / "llm.json", bundle["llm"])
    _write_json(data_out / "context.json", bundle["context"])
    _write_json(data_out / "report_research.json", bundle["reports"]["research"])
    _write_json(data_out / "report_monitor.json", bundle["reports"]["monitor"])
    active_root = profile_roots.get(bundle["active_profile"], data_root)
    _copy_latest_report_artifact(active_root, data_out / "report_research.md", phase="research", suffix=".md")
    _copy_latest_report_artifact(active_root, data_out / "report_monitor.md", phase="monitor", suffix=".md")

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
        _write_json(profile_out / "report_research.json", profile_bundle["reports"]["research"])
        _write_json(profile_out / "report_monitor.json", profile_bundle["reports"]["monitor"])
        _copy_latest_report_artifact(profile_root, profile_out / "report_research.md", phase="research", suffix=".md")
        _copy_latest_report_artifact(profile_root, profile_out / "report_monitor.md", phase="monitor", suffix=".md")

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
        "reports": {"research": research_report, "monitor": monitor_report},
        "artifacts": _build_profile_artifacts(profile["id"], multi_profile=multi_profile),
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
    base = f"data/profiles/{profile_id}"
    return {
        "dashboard_json": f"{base}/dashboard.json",
        "latest_json": f"{base}/latest.json",
        "history_json": f"{base}/history.json",
        "trades_json": f"{base}/trades.json",
        "research_json": f"{base}/research.json",
        "llm_json": f"{base}/llm.json",
        "context_json": f"{base}/context.json",
        "research_report_json": f"{base}/report_research.json",
        "monitor_report_json": f"{base}/report_monitor.json",
        "research_report_md": f"{base}/report_research.md",
        "monitor_report_md": f"{base}/report_monitor.md",
    }


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


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged
