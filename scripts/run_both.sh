#!/usr/bin/env bash
# Run a prompt phase for the active GPT/Codex strategist, then commit and push.
#
# Usage:
#   ./scripts/run_both.sh morning
#   ./scripts/run_both.sh evening
#   ./scripts/run_both.sh weekly
#   ./scripts/run_both.sh monthly
#   ./scripts/run_both.sh evolve
#   ./scripts/run_both.sh morning
#
# Notes:
#   - Claude is disabled for now. The runner only updates data/profiles/codex.

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

PHASE="${1:?Usage: $0 <morning|evening|weekly|monthly|evolve> [serial|parallel]}"
RUN_MODE="${2:-serial}"
DATE="$(date +%Y-%m-%d)"

# Codex execution budgets (override via environment variables if needed)
CODEX_MAX_SECONDS="${CODEX_MAX_SECONDS:-900}"
CODEX_MAX_WEB_SEARCHES="${CODEX_MAX_WEB_SEARCHES:-10}"
CODEX_MAX_AGENT_LOOPS="${CODEX_MAX_AGENT_LOOPS:-30}"
CODEX_REASONING_EFFORT="${CODEX_REASONING_EFFORT:-medium}"
CODEX_SANDBOX_MODE="${CODEX_SANDBOX_MODE:-workspace-write}"
CODEX_APPROVAL_POLICY="${CODEX_APPROVAL_POLICY:-never}"
CODEX_HOST_WRITE="${CODEX_HOST_WRITE:-true}"

if command -v python >/dev/null 2>&1; then
  PYTHON_CMD=(python)
elif command -v uv >/dev/null 2>&1; then
  export UV_CACHE_DIR="${UV_CACHE_DIR:-$PWD/.tmp/uv-cache}"
  PYTHON_CMD=(uv run --extra dev python)
else
  echo "Error: neither python nor uv is available."
  exit 1
fi

if command -v codex >/dev/null 2>&1; then
  CODEX_BIN="$(command -v codex)"
else
  CODEX_BIN=""
  for candidate in /c/Users/"${USERNAME:-$USER}"/AppData/Local/OpenAI/Codex/bin/*/codex.exe; do
    if [[ -x "$candidate" ]]; then
      CODEX_BIN="$candidate"
    fi
  done
fi

if [[ -z "$CODEX_BIN" ]]; then
  echo "Error: Codex CLI was not found on PATH or in the Codex desktop app install."
  exit 1
fi

if [[ "$RUN_MODE" == "--parallel" ]]; then
  RUN_MODE="parallel"
fi
if [[ "$RUN_MODE" != "serial" && "$RUN_MODE" != "parallel" ]]; then
  echo "Unknown run mode: $RUN_MODE"
  echo "Usage: $0 <morning|evening|weekly|monthly|evolve> [serial|parallel]"
  exit 1
fi

case "$PHASE" in
  morning)
    PROMPT_FILE="scripts/prompts/morning_research.md"
    EXTRA_PROMPT_FILE=""
    COMMIT_TAG="research"
    ;;
  evening)
    PROMPT_FILE="scripts/prompts/evening_reflection.md"
    EXTRA_PROMPT_FILE="scripts/prompts/strategist_voice.md"
    COMMIT_TAG="reflection"
    ;;
  weekly)
    PROMPT_FILE="scripts/prompts/weekly_review.md"
    EXTRA_PROMPT_FILE=""
    COMMIT_TAG="weekly"
    ;;
  monthly)
    PROMPT_FILE="scripts/prompts/monthly_retrospective.md"
    EXTRA_PROMPT_FILE=""
    COMMIT_TAG="monthly"
    ;;
  evolve)
    PROMPT_FILE="scripts/prompts/evolution_review.md"
    EXTRA_PROMPT_FILE=""
    COMMIT_TAG="evolution"
    ;;
  *)
    echo "Unknown phase: $PHASE"
    echo "Usage: $0 <morning|evening|weekly|monthly|evolve> [serial|parallel]"
    exit 1
    ;;
esac

if [[ ! -f "$PROMPT_FILE" ]]; then
  echo "Error: Prompt file not found: $PROMPT_FILE"
  exit 1
fi

PROMPT_TEMPLATE="$(cat "$PROMPT_FILE")"
EXTRA_PROMPT_TEMPLATE=""
if [[ -n "$EXTRA_PROMPT_FILE" ]]; then
  if [[ ! -f "$EXTRA_PROMPT_FILE" ]]; then
    echo "Error: Extra prompt file not found: $EXTRA_PROMPT_FILE"
    exit 1
  fi
  EXTRA_PROMPT_TEMPLATE="$(cat "$EXTRA_PROMPT_FILE")"
fi

mkdir -p .tmp/cli_logs

echo "============================================"
echo "  Agent Trader - $PHASE ($DATE) [$RUN_MODE]"
echo "============================================"
echo ""

echo "Pulling latest from main..."
git pull --ff-only origin main || true
echo ""

# Ensure required cache directories exist before the agent runs.
mkdir -p data/profiles/codex/cache
mkdir -p data/profiles/codex/interactions
mkdir -p data/profiles/codex/voice

validate_morning_cache() {
  local profile="$1"
  if [[ "$PHASE" != "morning" ]]; then
    return 0
  fi

  echo "Validating ${profile} morning research against recent market prices..."
  "${PYTHON_CMD[@]}" - "$profile" <<'PY'
import subprocess
import sys

from agent_trader.utils.morning_sanity import demote_stale_entries, validate_morning_research_file

profile = sys.argv[1]
data_dir = f"data/profiles/{profile}"

# Pass 1: fetch prices once and auto-demote any buy/sell whose entry is too stale.
demoted, ref_prices = demote_stale_entries(data_dir)
if demoted:
    print(f"[sanity] Auto-demoted to watch (stale entry): {', '.join(demoted)}")
    # Re-stage the corrected file so the commit picks up the fix.
    subprocess.run(
        ["git", "add", f"{data_dir}/cache/morning_research.json"],
        check=False,
    )

# Pass 2: validate the (possibly corrected) file. Only structural errors remain now.
result = validate_morning_research_file(data_dir, reference_prices=ref_prices)

if result.reference_prices:
    preview = ", ".join(
        f"{symbol}={price:.2f}" for symbol, price in sorted(result.reference_prices.items())[:6]
    )
    print(f"[sanity] Reference prices: {preview}")

for warning in result.warnings:
    print(f"[sanity] warning: {warning}")

if result.errors:
    print("[sanity] errors detected:")
    for error in result.errors:
        print(f"  - {error}")
    raise SystemExit(1)

print("[sanity] Morning cache passed validation.")
PY
}

write_interaction_metadata() {
  local metadata_path="$1"
  local profile="$2"
  local phase="$3"
  local tool="$4"
  local prompt_file="$5"
  local transcript_file="$6"
  local raw_log_file="$7"
  local status="$8"
  local prompt_source="$9"

  "${PYTHON_CMD[@]}" - "$metadata_path" "$profile" "$phase" "$tool" "$prompt_file" "$transcript_file" "$raw_log_file" "$status" "$prompt_source" <<'PY'
import json
import sys
from datetime import datetime
from pathlib import Path

(
    metadata_path,
    profile,
    phase,
    tool,
    prompt_file,
    transcript_file,
    raw_log_file,
    status,
    prompt_source,
) = sys.argv[1:]

transcript_path = Path(transcript_file)
summary_lines = []
if transcript_path.exists():
    for raw in transcript_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("[init]") or line.startswith("[assistant]") or line.startswith("[result]"):
            continue
        summary_lines.append(line)
        if len(summary_lines) >= 4:
            break

payload = {
    "timestamp": datetime.now().astimezone().isoformat(),
    "profile": profile,
    "phase": phase,
    "tool": tool,
    "status": "success" if status == "0" else "failed",
    "prompt_source": prompt_source,
    "prompt_file": prompt_file.replace("\\", "/"),
    "transcript_file": transcript_file.replace("\\", "/"),
    "raw_log_file": raw_log_file.replace("\\", "/"),
    "summary": " | ".join(summary_lines[:3]),
}

metadata = Path(metadata_path)
metadata.write_text(json.dumps(payload, indent=2), encoding="utf-8")

interactions_root = metadata.parent.parent
(interactions_root / "latest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
(interactions_root / f"latest_{phase}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
PY
}

strip_ps_encoding_warning() {
  sed -E \
    -e '/^Cannot set property\. Property setting is supported only on core types in this language mode\.$/d' \
    -e '/^At line:1 char:1$/d' \
    -e '/^\+ \[Console\]::OutputEncoding=\[System\.Text\.Encoding\]::UTF8;$/d' \
    -e '/^\+ ~+$/d' \
    -e '/^[[:space:]]*\+ CategoryInfo[[:space:]]+: InvalidOperation: \(:\) \[\], RuntimeException$/d' \
    -e '/^[[:space:]]*\+ FullyQualifiedErrorId : PropertySetterNotSupportedInConstrainedLanguage$/d'
}

run_codex_once() {
  local phase_label="$1"
  local prompt_source="$2"
  local prompt_template="$3"
  local prompt ts log status
  local interaction_dir prompt_file transcript_file metadata_file
  local -a codex_cmd
  prompt="${prompt_template//\{\{PROFILE\}\}/codex}"
  prompt="$prompt

---

## Runtime Limits (injected by runner)

You must stay within these limits:
- Max web searches: ${CODEX_MAX_WEB_SEARCHES}
- Max agent loops/tool cycles: ${CODEX_MAX_AGENT_LOOPS}
- Max runtime budget: ${CODEX_MAX_SECONDS} seconds

Behavior under limits:
- Prioritize highest-signal sources first.
- Do not exceed the limits.
- If you are close to limits, stop searching and finalize with best-effort output.
- If limits materially reduce quality, state that briefly in your output (do not ask for permission).
"
  ts="$(date '+%H%M%S')"
  log=".tmp/cli_logs/codex_${phase_label}_${DATE}_${ts}.log"
  interaction_dir="data/profiles/codex/interactions/${DATE}"
  mkdir -p "$interaction_dir"
  prompt_file="${interaction_dir}/${ts}_${phase_label}_prompt.md"
  transcript_file="${interaction_dir}/${ts}_${phase_label}_transcript.txt"
  metadata_file="${interaction_dir}/${ts}_${phase_label}_interaction.json"
  printf "%s\n" "$prompt" > "$prompt_file"

  if ! "$CODEX_BIN" exec --help >/dev/null 2>&1; then
    echo "Error: this Codex CLI version does not support 'codex exec'."
    echo "Please upgrade Codex CLI (npm install -g @openai/codex) and retry."
    return 1
  fi

  if [[ "$CODEX_HOST_WRITE" == "true" ]]; then
    # Host-write mode is needed for non-interactive runs that must persist file edits.
    codex_cmd=(
      "$CODEX_BIN"
      --dangerously-bypass-approvals-and-sandbox
      --search
      exec
      -c "model_reasoning_effort=\"${CODEX_REASONING_EFFORT}\""
    )
  else
    codex_cmd=(
      "$CODEX_BIN"
      -a "$CODEX_APPROVAL_POLICY"
      --search
      exec
      -s "$CODEX_SANDBOX_MODE"
      --add-dir data
      --add-dir data/profiles
      --add-dir data/profiles/codex
      --add-dir data/profiles/codex/cache
      -c "model_reasoning_effort=\"${CODEX_REASONING_EFFORT}\""
    )
  fi

  echo "Streaming Codex output (${phase_label}) - log: $log"
  echo "Codex limits: timeout=${CODEX_MAX_SECONDS}s, max_web_searches=${CODEX_MAX_WEB_SEARCHES}, max_loops=${CODEX_MAX_AGENT_LOOPS}, effort=${CODEX_REASONING_EFFORT}, host_write=${CODEX_HOST_WRITE}, sandbox=${CODEX_SANDBOX_MODE}, approval=${CODEX_APPROVAL_POLICY}"
  set +e
  echo "$prompt" | timeout "$CODEX_MAX_SECONDS" "${codex_cmd[@]}" | tee "$log" | strip_ps_encoding_warning | tee "$transcript_file"
  status=$?
  set -e
  write_interaction_metadata \
    "$metadata_file" "codex" "$phase_label" "codex" \
    "$prompt_file" "$transcript_file" "$log" "$status" "$prompt_source"
  if [[ "$status" -eq 124 ]]; then
    echo "Error: Codex timed out after ${CODEX_MAX_SECONDS}s (guardrail triggered)."
    echo "Increase CODEX_MAX_SECONDS if you want a longer run."
    return 1
  fi
  if [[ "$status" -ne 0 ]]; then
    echo "Error: Codex exited with status $status."
    return "$status"
  fi

  validate_morning_cache "codex"
}

run_codex() {
  echo "--------------------------------------------"
  echo "Running Codex strategist"
  echo "--------------------------------------------"

  run_codex_once "$PHASE" "$PROMPT_FILE" "$PROMPT_TEMPLATE"

  if [[ -n "$EXTRA_PROMPT_TEMPLATE" ]]; then
    echo ""
    echo "Running Codex strategist voice check"
    echo ""
    run_codex_once "voice" "$EXTRA_PROMPT_FILE" "$EXTRA_PROMPT_TEMPLATE"
  fi

  echo ""
  echo "Codex strategist complete."
  echo ""
}

if [[ "$RUN_MODE" == "parallel" ]]; then
  echo "Parallel mode requested, but Claude is disabled. Running Codex only."
fi
run_codex

echo "Committing and pushing..."
echo "Regenerating dashboard..."
"${PYTHON_CMD[@]}" -m agent_trader dashboard

git add data/profiles/codex/ docs/ WEEKBOOK.md
if git diff --staged --quiet; then
  echo "No changes to commit."
else
  git commit -m "[$COMMIT_TAG] $DATE codex strategist update"
  git push origin HEAD:main
  echo "Pushed to main."
fi

echo ""
echo "============================================"
echo "Done! Codex strategist updated."
echo "============================================"
