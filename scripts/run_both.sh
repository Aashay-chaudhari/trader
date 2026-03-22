#!/usr/bin/env bash
# Run a prompt phase for BOTH strategists, then commit and push.
#
# Usage:
#   ./scripts/run_both.sh morning     # Morning research for both
#   ./scripts/run_both.sh evening     # Evening reflection for both
#   ./scripts/run_both.sh weekly      # Weekly review for both
#   ./scripts/run_both.sh monthly     # Monthly retrospective for both
#
# What it does:
#   1. Reads the prompt template for the given phase
#   2. Replaces {{PROFILE}} with "claude", runs it via Claude Code CLI
#   3. Replaces {{PROFILE}} with "codex", runs it via Codex CLI
#   4. Commits all changes and pushes to main
#
# Prerequisites:
#   - Claude Code CLI installed: npm install -g @anthropic-ai/claude-code
#   - Codex CLI installed: npm install -g @openai/codex
#   - Both authenticated (claude login / codex login)

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

PHASE="${1:?Usage: $0 <morning|evening|weekly|monthly>}"
DATE=$(date +%Y-%m-%d)

# Map phase to prompt file and commit tag
case "$PHASE" in
  morning)
    PROMPT_FILE="scripts/prompts/morning_research.md"
    COMMIT_TAG="research"
    ;;
  evening)
    PROMPT_FILE="scripts/prompts/evening_reflection.md"
    COMMIT_TAG="reflection"
    ;;
  weekly)
    PROMPT_FILE="scripts/prompts/weekly_review.md"
    COMMIT_TAG="weekly"
    ;;
  monthly)
    PROMPT_FILE="scripts/prompts/monthly_retrospective.md"
    COMMIT_TAG="monthly"
    ;;
  *)
    echo "Unknown phase: $PHASE"
    echo "Usage: $0 <morning|evening|weekly|monthly>"
    exit 1
    ;;
esac

if [ ! -f "$PROMPT_FILE" ]; then
  echo "Error: Prompt file not found: $PROMPT_FILE"
  exit 1
fi

PROMPT_TEMPLATE=$(cat "$PROMPT_FILE")

echo "============================================"
echo "  Agent Trader — $PHASE ($DATE)"
echo "============================================"
echo ""

# ── Pull latest ──────────────────────────────────────────────────────
echo "Pulling latest from main..."
git pull --ff-only origin main || true
echo ""

# ── Run Claude strategist ────────────────────────────────────────────
echo "┌────────────────────────────────────────┐"
echo "│  Running Claude strategist...          │"
echo "└────────────────────────────────────────┘"
CLAUDE_PROMPT="${PROMPT_TEMPLATE//\{\{PROFILE\}\}/claude}"
echo "$CLAUDE_PROMPT" | claude --print

echo ""
echo "Claude strategist complete."
echo ""

# ── Run Codex strategist ─────────────────────────────────────────────
echo "┌────────────────────────────────────────┐"
echo "│  Running Codex strategist...           │"
echo "└────────────────────────────────────────┘"
CODEX_PROMPT="${PROMPT_TEMPLATE//\{\{PROFILE\}\}/codex}"
echo "$CODEX_PROMPT" | codex --print

echo ""
echo "Codex strategist complete."
echo ""

# ── Commit and push ──────────────────────────────────────────────────
echo "Committing and pushing..."
git add data/profiles/claude/ data/profiles/codex/
if git diff --staged --quiet; then
  echo "No changes to commit."
else
  git commit -m "[$COMMIT_TAG] $DATE dual-strategist update"
  git push origin main
  echo "Pushed to main."
fi

echo ""
echo "============================================"
echo "  Done! Both strategists updated."
echo "============================================"
