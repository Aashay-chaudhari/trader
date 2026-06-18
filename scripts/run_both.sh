#!/usr/bin/env bash
# Run a prompt phase for the active GPT/Codex strategist, then commit and push.
#
# Usage:
#   ./scripts/run_both.sh morning
#   ./scripts/run_both.sh monitor
#   ./scripts/run_both.sh evening
#   ./scripts/run_both.sh weekly
#   ./scripts/run_both.sh monthly
#   ./scripts/run_both.sh evolve
#
# Notes:
#   - Claude is disabled for now. The runner only updates data/profiles/codex.

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

PHASE="${1:?Usage: $0 <morning|monitor|evening|weekly|monthly|evolve> [serial|parallel]}"
RUN_STYLE="${2:-serial}"
DATE="$(date +%Y-%m-%d)"

export AGENT_PROFILE="${AGENT_PROFILE:-codex}"
export AGENT_LABEL="${AGENT_LABEL:-Codex Strategist}"
export DATA_DIR="${DATA_DIR:-data/profiles/${AGENT_PROFILE}}"
export MONITOR_RUNTIME="${MONITOR_RUNTIME:-codex_loop}"
export MONITOR_EXECUTION_OWNER="${MONITOR_EXECUTION_OWNER:-github_actions}"
export RUN_MODE="${RUN_MODE:-paper}"

if [[ "$MONITOR_EXECUTION_OWNER" != "github_actions" && "$MONITOR_EXECUTION_OWNER" != "local" ]]; then
  echo "Error: MONITOR_EXECUTION_OWNER must be github_actions or local."
  exit 1
fi

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

CODEX_BIN="${CODEX_BIN:-}"
if [[ -z "$CODEX_BIN" ]]; then
  for candidate in /c/Users/"${USERNAME:-$USER}"/AppData/Local/OpenAI/Codex/bin/*/codex.exe; do
    if [[ -x "$candidate" ]]; then
      CODEX_BIN="$candidate"
      break
    fi
  done
fi
if [[ -z "$CODEX_BIN" ]] && command -v codex >/dev/null 2>&1; then
  CODEX_BIN="$(command -v codex)"
fi

if [[ -z "$CODEX_BIN" ]]; then
  echo "Error: Codex CLI was not found on PATH or in the Codex desktop app install."
  exit 1
fi

if [[ "$RUN_STYLE" == "--parallel" ]]; then
  RUN_STYLE="parallel"
fi
if [[ "$RUN_STYLE" != "serial" && "$RUN_STYLE" != "parallel" ]]; then
  echo "Unknown run style: $RUN_STYLE"
  echo "Usage: $0 <morning|monitor|evening|weekly|monthly|evolve> [serial|parallel]"
  exit 1
fi

case "$PHASE" in
  morning)
    PROMPT_FILE="scripts/prompts/morning_research.md"
    EXTRA_PROMPT_FILE=""
    COMMIT_TAG="research"
    ;;
  monitor)
    PROMPT_FILE="scripts/prompts/monitor_check.md"
    EXTRA_PROMPT_FILE=""
    COMMIT_TAG="monitor"
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
    echo "Usage: $0 <morning|monitor|evening|weekly|monthly|evolve> [serial|parallel]"
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
echo "  Agent Trader - $PHASE ($DATE) [$RUN_STYLE]"
echo "============================================"
echo ""

echo "Pulling latest from main..."
git pull --ff-only origin main || true
echo ""

# Ensure required cache directories exist before the agent runs.
mkdir -p data/profiles/codex/cache
mkdir -p data/profiles/codex/interactions
mkdir -p data/profiles/codex/voice

echo "Bootstrapping profile structure and empty learning schemas..."
"${PYTHON_CMD[@]}" - <<'PY'
import os

from agent_trader.config.settings import get_settings
from agent_trader.utils.knowledge_base import KnowledgeBase
from agent_trader.utils.profiles import ensure_profile_metadata

settings = get_settings()
ensure_profile_metadata(settings)
KnowledgeBase(os.environ["DATA_DIR"]).ensure_cold_start_schemas()
print(f"Profile ready: {os.environ['DATA_DIR']}")
PY
echo ""

print_local_runtime_config() {
  "${PYTHON_CMD[@]}" - <<'PY'
from agent_trader.config.settings import get_settings

settings = get_settings()
alpaca_ready = bool(settings.alpaca_api_key and settings.alpaca_secret_key)

print("Local runtime configuration:")
print(f"  profile={settings.agent_profile}")
print(f"  data_dir={settings.data_dir}")
print(f"  run_mode={settings.run_mode}")
print(f"  monitor_runtime={settings.monitor_runtime}")
print(f"  monitor_execution_owner={settings.monitor_execution_owner}")
print(f"  alpaca_paper_credentials={'available' if alpaca_ready else 'missing'}")
if settings.monitor_execution_owner == "github_actions":
    print("  broker_handoff=GitHub Actions will use repository Alpaca secrets")
elif settings.run_mode == "paper" and not alpaca_ready:
    print("  warning=paper analysis is active, but broker execution will fall back to dry_run")
PY
  echo ""
}

print_local_runtime_config

push_main() {
  if git push origin HEAD:main; then
    return 0
  fi

  local windows_git="/mnt/c/Program Files/Git/cmd/git.exe"
  if [[ -x "$windows_git" ]]; then
    echo "WSL Git push was unavailable; retrying with Windows Git Credential Manager..."
    GCM_INTERACTIVE=Never "$windows_git" push origin HEAD:main
    return 0
  fi

  echo "Error: push failed and Windows Git fallback was not found."
  return 1
}

validate_morning_cache() {
  local profile="$1"
  if [[ "$PHASE" != "morning" ]]; then
    return 0
  fi

  echo "Validating ${profile} morning research against recent market prices..."
  "${PYTHON_CMD[@]}" - "$profile" <<'PY'
import subprocess
import sys

from agent_trader.utils.morning_sanity import (
    demote_stale_entries,
    enrich_morning_theory_fields,
    validate_morning_research_file,
)

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

enriched = enrich_morning_theory_fields(data_dir, reference_prices=ref_prices)
if enriched:
    preview = ", ".join(enriched[:8])
    suffix = "..." if len(enriched) > 8 else ""
    print(f"[sanity] Enriched theory metadata: {preview}{suffix}")
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

prepare_monitor_context() {
  if [[ "$PHASE" != "monitor" ]]; then
    return 0
  fi

  echo "Preparing local Codex monitor context..."
  "${PYTHON_CMD[@]}" -m agent_trader monitor-local-prepare
}

monitor_context_status() {
  "${PYTHON_CMD[@]}" - <<'PY'
import json
from pathlib import Path

path = Path("data/profiles/codex/cache/local_monitor_context.json")
payload = json.loads(path.read_text(encoding="utf-8-sig"))
print(payload.get("status", "unknown"))
PY
}

apply_monitor_decision() {
  if [[ "$PHASE" != "monitor" ]]; then
    return 0
  fi

  echo "Applying local Codex monitor decision..."
  "${PYTHON_CMD[@]}" -m agent_trader monitor-local-apply
}

stamp_monitor_decision_run_id() {
  if [[ "$PHASE" != "monitor" ]]; then
    return 0
  fi

  "${PYTHON_CMD[@]}" - <<'PY'
import json
import os
from pathlib import Path

cache_dir = Path(os.environ["DATA_DIR"]) / "cache"
context_path = cache_dir / "local_monitor_context.json"
decision_path = cache_dir / "local_monitor_decision.json"
context = json.loads(context_path.read_text(encoding="utf-8-sig"))
decision = json.loads(decision_path.read_text(encoding="utf-8-sig"))
run_id = str(context.get("run_id") or "").strip()
decision_run_id = str(decision.get("run_id") or "").strip()

if not run_id:
    raise SystemExit("Prepared monitor context has no run_id.")
if decision_run_id and decision_run_id != run_id:
    raise SystemExit(
        f"Monitor decision run_id mismatch: decision={decision_run_id}, context={run_id}"
    )

decision["run_id"] = run_id
decision_path.write_text(json.dumps(decision, indent=2), encoding="utf-8")
print(f"Stamped monitor decision run_id={run_id}")
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

if [[ "$RUN_STYLE" == "parallel" ]]; then
  echo "Parallel mode requested, but Claude is disabled. Running Codex only."
fi
if [[ "$PHASE" == "monitor" ]]; then
  prepare_monitor_context
  monitor_status="$(monitor_context_status)"
  case "$monitor_status" in
    ready)
      run_codex
      stamp_monitor_decision_run_id
      if [[ "$MONITOR_EXECUTION_OWNER" == "local" ]]; then
        apply_monitor_decision
      else
        echo "Broker execution handed off to GitHub Actions after this decision is pushed."
      fi
      ;;
    no_candidates)
      echo "Skipping Codex monitor call (context status: $monitor_status)."
      apply_monitor_decision
      ;;
    skipped)
      echo "Skipping Codex monitor call and execution (context status: $monitor_status)."
      ;;
    error)
      echo "Local monitor context has an error. Run morning research first or inspect data/profiles/codex/cache/local_monitor_context.json."
      exit 1
      ;;
    *)
      echo "Unknown local monitor context status: $monitor_status"
      exit 1
      ;;
  esac
else
  run_codex
fi

echo "Committing and pushing..."
echo "Regenerating dashboard..."
"${PYTHON_CMD[@]}" -m agent_trader dashboard

git add data/profiles/codex/ docs/ WEEKBOOK.md
if git diff --staged --quiet; then
  echo "No changes to commit."
else
  git commit -m "[$COMMIT_TAG] $DATE codex strategist update"
  push_main
  echo "Pushed to main."
  if [[ "$PHASE" == "monitor" && "$monitor_status" == "ready" && "$MONITOR_EXECUTION_OWNER" == "github_actions" ]]; then
    echo "GitHub Actions will now apply the decision, commit execution artifacts, and publish Pages."
  fi
fi

echo ""
echo "============================================"
echo "Done! Codex strategist updated."
echo "============================================"
