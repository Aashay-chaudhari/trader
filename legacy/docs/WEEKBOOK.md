# Weekbook

## Every Trading Morning

Ideal window: 8:15 AM to 8:45 AM ET.

```powershell
& "C:\Program Files\Git\bin\bash.exe" ./scripts/run_both.sh morning parallel
```

Confirm:

- the Codex session succeeds or records an intentional same-day skip
- morning sanity validation passes
- `data/profiles/codex/cache/morning_research.json` and `watchlist.json` are current
- the research commit reaches `origin/main`
- GitHub Pages lists the morning interaction

## During Market Hours

No local command is normally required. The `Trading Pipeline` runs every 30 minutes across the configured weekday market window. Python applies the exact market-hours guard.

Check GitHub Actions when:

- no monitor interaction appears after a scheduled interval
- the dashboard stops updating
- an expected paper order is absent
- market-data or model evidence looks incomplete

For a manual monitor run, use GitHub Actions workflow dispatch with `low_cost_mode=true` and `reset_state=false`.

## Every Trading Evening

```powershell
& "C:\Program Files\Git\bin\bash.exe" ./scripts/run_both.sh evening parallel
```

Confirm the daily observation, knowledge updates, proposal backlog, voice summary, interaction transcript, dashboard, commit, and push.

## Weekend and Periodic Work

```powershell
& "C:\Program Files\Git\bin\bash.exe" ./scripts/run_both.sh weekly parallel
& "C:\Program Files\Git\bin\bash.exe" ./scripts/run_both.sh monthly parallel
& "C:\Program Files\Git\bin\bash.exe" ./scripts/run_both.sh evolve parallel
```

Weekly review consolidates recent evidence. Monthly review updates longer-term strategy trust. Evolution review converts the improvement backlog into explicit engineering recommendations.

## Recovery

Morning failure:

1. Inspect `.tmp/cli_logs/` and the newest interaction transcript.
2. Confirm the current Codex desktop CLI is available.
3. Rerun the morning command; idempotency prevents duplicate research after valid files exist.

Monitor failure:

1. Check the Actions job that failed: monitor, publish, or deploy.
2. Verify `OPENAI_API_KEY`, Alpaca credentials, and `MONITOR_RUN_MODE`.
3. Inspect the retained `strategist-codex-monitor` artifact.
4. Dispatch the workflow manually after correcting configuration.

Dashboard failure:

```powershell
$env:UV_CACHE_DIR="$PWD\.tmp\uv-cache"
uv run --extra dev python -m agent_trader dashboard
```

