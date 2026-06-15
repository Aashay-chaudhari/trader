# Fresh Start Guide

This guide creates a clean application baseline and a clean Alpaca paper-trading
baseline. Those are separate systems and must be reset separately.

## Reset Model

```text
Old application artifacts                Old Alpaca paper account
  |                                         |
  v                                         v
Application hard reset                   Create new paper account
  |                                         |
  +-- clear research/monitoring              +-- blank broker history
  +-- clear portfolio/journal                 +-- chosen starting balance
  +-- clear observations/knowledge            +-- new API credentials
  +-- clear published dashboard               |
  +-- write fresh_start.json                  v
  |                                       GitHub Actions secrets
  +----------------------+--------------------+
                         |
                         v
                 Verify paper account
                         |
                         v
                 Start Codex day loop
```

## 1. Create a Clean Alpaca Account

Alpaca's current dashboard uses paper-account creation and deletion instead of
resetting an existing account's history.

1. Open the Alpaca dashboard and switch to paper trading.
2. Select the paper account number in the upper-left corner.
3. Choose **Open New Paper Account** and select the desired starting balance.
4. Generate a new API key and secret for that account.
5. In GitHub, open **Settings > Secrets and variables > Actions**.
6. Replace `ALPACA_API_KEY_CODEX` and `ALPACA_SECRET_KEY_CODEX`.
7. Run **Actions > Verify Alpaca Paper Account > Run workflow**.
8. Confirm the workflow reports zero open positions and zero open orders.
9. Optionally return to Alpaca **Account Settings** and delete the old paper
   account after the new credentials are verified.

Official reference:
https://docs.alpaca.markets/us/docs/paper-trading#reset-your-paper-trading-account

Changing only the application files does not change the Alpaca account. Closing
positions and canceling orders also does not erase fills, P&L, or account history.

## 2. Reset the Application

Local command:

```bash
./scripts/reset_for_fresh_start.sh 2026-06-15 RESET
```

GitHub alternative:

```text
Actions > Reset Application State > Run workflow
start_date: 2026-06-15
confirmation: RESET
```

The operation deletes generated state under `data/profiles/codex/`, clears the
generated `docs/` dashboard bundle, recreates profile metadata, writes
`fresh_start.json`, generates an empty dashboard, commits, pushes, and deploys
Pages.

It preserves source code, prompts, tests, workflows, and documentation. Prior
artifacts remain reachable in old Git commits for audit purposes.

## 3. Start the New Era

On the start date, paste the full contents of
`scripts/prompts/codex_day_loop_master.md` into a fresh Codex session.

The supervisor reads `fresh_start.json`, skips reviews belonging to the old era,
runs morning research at the configured Eastern Time, starts 30-minute monitor
checks, hands approved decisions to GitHub Actions, and runs evening reflection.

## Expected GitHub Activity

```text
Morning push
  -> Tests
  -> Publish Dashboard

Ready monitor decision push
  -> Codex Decision Execution
  -> execution artifact commit
  -> GitHub Pages deployment

Evening/review push
  -> Tests
  -> Publish Dashboard
```
