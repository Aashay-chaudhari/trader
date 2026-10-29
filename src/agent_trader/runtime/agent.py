from __future__ import annotations

import json
import os
import selectors
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from .config import ET
from .store import dumps, utc_now


class AgentUnavailable(RuntimeError):
    pass


class CodexRPC:
    """Authenticated subscription-only local harness; no OpenAI API client."""

    def __init__(self, config):
        self.config = config
        binary = config.codex_bin or os.environ.get("TRADER_CODEX_BIN") or shutil.which("codex")
        native = False
        if binary:
            try:
                with open(binary, "rb") as handle:
                    native = handle.read(4) == b"\x7fELF"
            except OSError:
                pass
        if not native:
            candidates = sorted(
                Path("/mnt/c/Users/aasha/.vscode/extensions").glob(
                    "openai.chatgpt-*/bin/linux-x86_64/codex"
                )
            )
            binary = str(candidates[-1]) if candidates else None
        if not binary:
            raise AgentUnavailable("Codex executable unavailable")
        self.workspace = config.state_dir / "agent-workspace"
        self.workspace.mkdir(parents=True, exist_ok=True)
        env = {
            k: v
            for k, v in os.environ.items()
            if not any(
                x in k.upper() for x in ["API_KEY", "SECRET", "NTFY", "GH_TOKEN", "GITHUB_TOKEN"]
            )
        }
        self.proc = subprocess.Popen(
            [
                binary,
                "app-server",
                "--listen",
                "stdio://",
                "--disable",
                "shell_tool",
                "--disable",
                "apps",
                "-c",
                'web_search="live"',
                "-c",
                'approval_policy="never"',
                "-c",
                'sandbox_mode="read-only"',
            ],
            cwd=self.workspace,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.proc.stdout, selectors.EVENT_READ)
        self.buffer = b""
        self.counter = 0
        self.backlog = []
        self.rpc(
            "initialize", {"clientInfo": {"name": "agent_trader", "version": "2.0.0"}}, timeout=30
        )
        self.send({"method": "initialized"})

    def send(self, message):
        self.proc.stdin.write((dumps(message) + "\n").encode())
        self.proc.stdin.flush()

    def receive(self, deadline):
        while time.monotonic() < deadline:
            if b"\n" in self.buffer:
                line, self.buffer = self.buffer.split(b"\n", 1)
                if not line:
                    continue
                message = json.loads(line)
                if "method" in message and "id" in message:
                    # This unattended research process cannot approve filesystem,
                    # tool, account, or permission escalations.
                    self.send(
                        {
                            "id": message["id"],
                            "error": {"code": -32601, "message": "Interactive requests disabled"},
                        }
                    )
                    continue
                return message
            if self.proc.poll() is not None:
                raise AgentUnavailable("Codex process exited")
            if self.selector.select(min(1, max(0.01, deadline - time.monotonic()))):
                chunk = os.read(self.proc.stdout.fileno(), 65536)
                if not chunk:
                    raise AgentUnavailable("Codex stream closed")
                self.buffer += chunk
        raise AgentUnavailable("Codex task timed out")

    def rpc(self, method, params=None, timeout=30):
        self.counter += 1
        call_id = self.counter
        self.send({"id": call_id, "method": method, "params": params or {}})
        end = time.monotonic() + timeout
        while True:
            message = self.receive(end)
            if message.get("id") == call_id:
                if "error" in message:
                    # Error messages can include caller data; don't persist raw text.
                    raise AgentUnavailable(
                        f"Codex {method} rejected ({message['error'].get('code')})"
                    )
                return message.get("result", {})
            self.backlog.append(message)

    def rate_limits(self):
        result = self.rpc("account/rateLimits/read")
        buckets = result.get("rateLimitsByLimitId") or {"codex": result.get("rateLimits", {})}
        windows = []
        for key, bucket in buckets.items():
            for name in ("primary", "secondary"):
                w = bucket.get(name)
                if w:
                    windows.append({"bucket": key, "kind": name, **w})
        return {
            "at": utc_now(),
            "windows": windows,
            "ordinary_usage_allowed": result.get("ordinaryUsageAllowed", True),
        }

    def models(self):
        return self.rpc("model/list", {"limit": 100}).get("data", [])

    def run(self, thread_id, prompt, model, effort, schema, *, max_searches=8, max_cycles=25):
        if thread_id:
            result = self.rpc(
                "thread/resume",
                {
                    "threadId": thread_id,
                    "cwd": str(self.workspace),
                    "approvalPolicy": "never",
                    "sandbox": "read-only",
                },
            )
        else:
            result = self.rpc(
                "thread/start",
                {
                    "cwd": str(self.workspace),
                    "model": model,
                    "approvalPolicy": "never",
                    "sandbox": "read-only",
                    "config": {
                        "web_search": "live",
                        "features.shell_tool": False,
                        "features.apps": False,
                    },
                },
            )
        thread_id = result["thread"]["id"]
        self.backlog.clear()
        turn = self.rpc(
            "turn/start",
            {
                "threadId": thread_id,
                "input": [{"type": "text", "text": prompt}],
                "model": model,
                "effort": effort,
                "approvalPolicy": "never",
                "sandboxPolicy": {"type": "readOnly", "networkAccess": False},
                "outputSchema": schema,
            },
        )
        turn_id = turn["turn"]["id"]
        end = time.monotonic() + self.config.max_agent_seconds
        output, usage, cycles, searches = "", {}, 0, 0
        pending = list(self.backlog)
        self.backlog.clear()
        while True:
            msg = pending.pop(0) if pending else self.receive(end)
            params = msg.get("params", {})
            if params.get("threadId", thread_id) != thread_id:
                continue
            method = msg.get("method", "")
            if method == "item/started":
                item = params.get("item", {})
                cycles += 1
                if item.get("type") == "webSearch":
                    searches += 1
                if cycles > max_cycles or searches > max_searches:
                    self.send(
                        {
                            "id": 999999,
                            "method": "turn/interrupt",
                            "params": {"threadId": thread_id, "turnId": turn_id},
                        }
                    )
                    raise AgentUnavailable("Task search/tool budget exhausted")
            if method == "item/agentMessage/delta":
                output += params.get("delta", "")
                if len(output) > 100000:
                    raise AgentUnavailable("Task output budget exhausted")
            if method == "item/completed":
                item = params.get("item", {})
                if item.get("type") == "agentMessage":
                    output = item.get("text", output)
            if method == "thread/tokenUsage/updated":
                usage = params.get("tokenUsage", {})
            if method == "turn/completed":
                result_turn = params.get("turn", {})
                if result_turn.get("status") != "completed":
                    raise AgentUnavailable("Codex turn failed or was interrupted")
                break
        return thread_id, json.loads(output), usage, {"searches": searches, "cycles": cycles}

    def close(self):
        import signal

        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
            self.proc.wait(timeout=5)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        self.selector.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def budget_check(store, quota, role, now):
    windows = quota.get("windows", [])
    if not quota.get("ordinary_usage_allowed") or not windows:
        return False, "Account quota unavailable or access limited"
    weekly = [w for w in windows if w.get("windowDurationMins", 0) >= 10000]
    if not weekly:
        return False, "Weekly quota window unavailable"
    w = weekly[0]
    used, reset = float(w["usedPercent"]), int(w["resetsAt"])
    key = f"quota-baseline:{reset}"
    baseline = store.get(key)
    if baseline is None or used < baseline - 1:
        baseline = used
        store.set(key, baseline)
    # Includes other work since baseline: intentionally conservative attribution.
    allowance_used = max(0, used - baseline)
    if used >= 80 or allowance_used >= 80:
        return False, "20% account reserve reached"
    if any(float(x.get("usedPercent", 0)) >= 90 for x in windows):
        return False, "Short-window quota nearly exhausted"
    today = now.astimezone(ET).date().isoformat()
    calls = store.rows("SELECT count(*) AS n FROM usage WHERE day=?", (today,))[0]["n"]
    night_roles = ("retrospective", "maintenance", "weekly", "monthly")
    critical_roles = ("decision", "position_review")
    ceiling = 24 if role in night_roles else (20 if role in critical_roles else 16)
    if calls >= ceiling:
        return False, "Daily model-call ceiling reached"
    reset_day = datetime.fromtimestamp(reset, timezone.utc).astimezone(ET).date()
    import numpy as np

    trading_days = max(1, int(np.busday_count(now.astimezone(ET).date(), reset_day)) + 1)
    day_key = f"quota-day:{today}:{reset}"
    day_start = store.get(day_key)
    if day_start is None:
        day_start = used
        store.set(day_key, day_start)
    daily_allowance = max(1.0, (80 - day_start) / trading_days)
    consumption = max(0, used - day_start)
    multiplier = 1.0 if role in night_roles else (0.8 if role in critical_roles else 0.45)
    if consumption >= daily_allowance * multiplier:
        return False, "Paced daily quota allocation reached"
    return True, "Within account and paced daily limits"


def run_task(config, role, prompt, response_model, model, effort, day, *, searches=8, cycles=25):
    from .store import Store

    store = Store(config.state_dir / "trader.sqlite3")
    try:
        with CodexRPC(config) as rpc:
            before = rpc.rate_limits()
            store.set("quota", before)
            allowed, reason = budget_check(store, before, role, datetime.now(timezone.utc))
            if not allowed:
                store.set("entry_budget_blocked", True)
                store.event("budget_skip", {"role": role, "reason": reason})
                raise AgentUnavailable(reason)
            usage_cursor = store.db.execute(
                "INSERT INTO usage(at,day,role,model,input_tokens,cached_tokens,output_tokens,quota_delta,payload) VALUES(?,?,?,?,0,0,0,0,?)",
                (utc_now(), day, role, model, dumps({"state": "started"})),
            )
            usage_id = usage_cursor.lastrowid
            thread_id = store.get(f"thread:{day}")
            t, payload, usage, counters = rpc.run(
                thread_id,
                prompt[: config.max_input_chars],
                model,
                effort,
                response_model.model_json_schema(),
                max_searches=searches,
                max_cycles=cycles,
            )
            store.set(f"thread:{day}", t)
            parsed = response_model.model_validate(payload)
            available = [m.get("id") for m in rpc.models()]
            readiness = store.get("readiness", {})
            readiness["models_available"] = all(
                m in available
                for m in (
                    config.research_model,
                    config.decision_model,
                    config.light_model,
                    config.maintenance_model,
                )
            )
            store.set("readiness", readiness)
            after = rpc.rate_limits()
            store.set("quota", after)
            store.set(
                "entry_budget_blocked",
                not after.get("ordinary_usage_allowed", True)
                or any(
                    float(w.get("usedPercent", 0))
                    >= (80 if w.get("windowDurationMins", 0) >= 10000 else 90)
                    for w in after.get("windows", [])
                ),
            )
            before_w = next((w for w in before["windows"] if w["windowDurationMins"] >= 10000), {})
            after_w = next((w for w in after["windows"] if w["windowDurationMins"] >= 10000), {})
            delta = max(0, after_w.get("usedPercent", 0) - before_w.get("usedPercent", 0))
            last = usage.get("last") or usage.get("total") or {}
            store.db.execute(
                """UPDATE usage SET at=?,day=?,role=?,model=?,input_tokens=?,cached_tokens=?,output_tokens=?,quota_delta=?,payload=? WHERE id=?""",
                (
                    utc_now(),
                    day,
                    role,
                    model,
                    last.get("inputTokens", 0),
                    last.get("cachedInputTokens", 0),
                    last.get("outputTokens", 0),
                    delta,
                    dumps(counters),
                    usage_id,
                ),
            )
            store.event("agent_task", {"role": role, "model": model, **counters})
            return parsed.model_dump(mode="json")
    finally:
        store.close()
