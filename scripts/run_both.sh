#!/usr/bin/env bash
# Run a prompt phase for BOTH strategists, then commit and push.
#
# Usage:
#   ./scripts/run_both.sh morning
#   ./scripts/run_both.sh evening
#   ./scripts/run_both.sh weekly
#   ./scripts/run_both.sh monthly
#   ./scripts/run_both.sh morning parallel
#
# Notes:
#   - Default mode is serial.
#   - In parallel mode, both strategists run concurrently and we commit only
#     after BOTH succeed.

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

PHASE="${1:?Usage: $0 <morning|evening|weekly|monthly> [serial|parallel]}"
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

if [[ "$RUN_MODE" == "--parallel" ]]; then
  RUN_MODE="parallel"
fi
if [[ "$RUN_MODE" != "serial" && "$RUN_MODE" != "parallel" ]]; then
  echo "Unknown run mode: $RUN_MODE"
  echo "Usage: $0 <morning|evening|weekly|monthly> [serial|parallel]"
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
  *)
    echo "Unknown phase: $PHASE"
    echo "Usage: $0 <morning|evening|weekly|monthly> [serial|parallel]"
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

# Ensure required cache directories exist before agents run.
mkdir -p data/profiles/claude/cache data/profiles/codex/cache
mkdir -p data/profiles/claude/interactions data/profiles/codex/interactions
mkdir -p data/profiles/claude/voice data/profiles/codex/voice

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

  python - "$metadata_path" "$profile" "$phase" "$tool" "$prompt_file" "$transcript_file" "$raw_log_file" "$status" "$prompt_source" <<'PY'
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

pretty_print_claude_stream() {
  python -u -c '
import json
import sys

def out(msg):
    print(msg, flush=True)

for raw in sys.stdin:
    line = raw.strip()
    if not line:
        continue
    try:
        obj = json.loads(line)
    except Exception:
        out(line)
        continue

    typ = obj.get("type")
    if typ == "system":
        model = obj.get("model", "unknown")
        tools = obj.get("tools", [])
        out(f"[init] model={model} tools={len(tools)}")
    elif typ == "stream_event":
        event = obj.get("event", {})
        etype = event.get("type")
        if etype == "message_start":
            out("[assistant] generating...")
        elif etype == "content_block_start":
            cb = event.get("content_block", {})
            if cb.get("type") == "tool_use":
                name = cb.get("name", "tool")
                out(f"[tool] {name}")
        elif etype == "content_block_delta":
            delta = event.get("delta", {})
            text = delta.get("text")
            if text:
                print(text, end="", flush=True)
        elif etype == "content_block_stop":
            print("", flush=True)
    elif typ == "result":
        turns = obj.get("num_turns")
        duration_ms = obj.get("duration_ms")
        cost = obj.get("total_cost_usd")
        out(f"[result] turns={turns} duration_ms={duration_ms} cost_usd={cost}")
'
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

run_claude_once() {
  local phase_label="$1"
  local prompt_source="$2"
  local prompt_template="$3"
  local prompt allowed ts log status
  local interaction_dir prompt_file transcript_file metadata_file

  prompt="${prompt_template//\{\{PROFILE\}\}/claude}"
  allowed="Read,Write,Edit,Glob,Grep,Bash,WebSearch,WebFetch"
  ts="$(date '+%H%M%S')"
  log=".tmp/cli_logs/claude_${phase_label}_${DATE}_${ts}.ndjson"
  interaction_dir="data/profiles/claude/interactions/${DATE}"
  mkdir -p "$interaction_dir"
  prompt_file="${interaction_dir}/${ts}_${phase_label}_prompt.md"
  transcript_file="${interaction_dir}/${ts}_${phase_label}_transcript.txt"
  metadata_file="${interaction_dir}/${ts}_${phase_label}_interaction.json"
  printf "%s\n" "$prompt" > "$prompt_file"

  echo "Streaming Claude events (${phase_label}) - log: $log"
  set +e
  echo "$prompt" | claude \
    --print \
    --verbose \
    --output-format stream-json \
    --include-partial-messages \
    --allowedTools "$allowed" \
    | tee "$log" \
    | pretty_print_claude_stream \
    | tee "$transcript_file"
  status=$?
  set -e
  write_interaction_metadata \
    "$metadata_file" "claude" "$phase_label" "claude" \
    "$prompt_file" "$transcript_file" "$log" "$status" "$prompt_source"
  if [[ "$status" -ne 0 ]]; then
    echo "Error: Claude exited with status $status."
    return "$status"
  fi
}

run_claude() {
  echo "--------------------------------------------"
  echo "Running Claude strategist"
  echo "--------------------------------------------"

  run_claude_once "$PHASE" "$PROMPT_FILE" "$PROMPT_TEMPLATE"

  if [[ -n "$EXTRA_PROMPT_TEMPLATE" ]]; then
    echo ""
    echo "Running Claude strategist voice check"
    echo ""
    run_claude_once "voice" "$EXTRA_PROMPT_FILE" "$EXTRA_PROMPT_TEMPLATE"
  fi

  echo ""
  echo "Claude strategist complete."
  echo ""
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

  if ! codex exec --help >/dev/null 2>&1; then
    echo "Error: this Codex CLI version does not support 'codex exec'."
    echo "Please upgrade Codex CLI (npm install -g @openai/codex) and retry."
    return 1
  fi

  if [[ "$CODEX_HOST_WRITE" == "true" ]]; then
    # Host-write mode is needed for non-interactive runs that must persist file edits.
    codex_cmd=(
      codex
      --dangerously-bypass-approvals-and-sandbox
      --search
      exec
      -c "model_reasoning_effort=\"${CODEX_REASONING_EFFORT}\""
    )
  else
    codex_cmd=(
      codex
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
  echo "Running strategists in PARALLEL mode..."
  echo ""

  set +e
  (run_claude 2>&1 | sed 's/^/[CLAUDE] /') &
  CLAUDE_PID=$!

  (run_codex 2>&1 | sed 's/^/[CODEX] /') &
  CODEX_PID=$!

  wait "$CLAUDE_PID"
  CLAUDE_STATUS=$?
  wait "$CODEX_PID"
  CODEX_STATUS=$?
  set -e

  if [[ "$CLAUDE_STATUS" -ne 0 || "$CODEX_STATUS" -ne 0 ]]; then
    echo "One or more strategist runs failed."
    echo "Claude exit code: $CLAUDE_STATUS"
    echo "Codex exit code: $CODEX_STATUS"
    exit 1
  fi
else
  run_claude
  run_codex
fi

echo "Committing and pushing..."
echo "Regenerating dashboard..."
python -m agent_trader dashboard

git add data/profiles/claude/ data/profiles/codex/ docs/ WEEKBOOK.md
if git diff --staged --quiet; then
  echo "No changes to commit."
else
  git commit -m "[$COMMIT_TAG] $DATE dual-strategist update"
  git push origin main
  echo "Pushed to main."
fi

echo ""
echo "============================================"
echo "Done! Both strategists updated."
echo "============================================"
