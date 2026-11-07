from __future__ import annotations

import hashlib
import json
import os
import selectors
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .budget import account_limit_reason, budget_check
from .config import ET
from .store import dumps, utc_now


class AgentUnavailable(RuntimeError):
    pass


def validation_diagnostics(exc, schema):
    """Field/type diagnostics without Pydantic's echoed inputs or error context."""
    from pydantic import ValidationError

    if not isinstance(exc, ValidationError):
        return {}
    fields = set()

    def collect(value):
        if isinstance(value, dict):
            fields.update(value.get("properties", {}))
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(schema)
    # Only developer-authored messages in this explicit map may become public
    # categories. Arbitrary exception messages can contain model/source content.
    known_rules = {
        "Value error, Signal target exceeds the maximum opportunities in the fixed study":
            "signal_target_exceeds_opportunities",
        "Value error, External factual claims require cited sources": "missing_external_sources",
        "Value error, Observation-led ideas need recorded evidence, alternatives and a prediction":
            "incomplete_observation_evidence",
    }
    errors = exc.errors(include_input=False, include_url=False, include_context=False)
    details = []
    for error in errors[:20]:
        detail = {
            "path": [
                part if isinstance(part, int) or part in fields else "<unrecognized-field>"
                for part in error.get("loc", ())[:12]
            ],
            "type": error["type"],
        }
        if error.get("msg") in known_rules:
            detail["rule"] = known_rules[error["msg"]]
        details.append(detail)
    return {"validation_errors": details, "validation_error_count": len(errors)}


def bounded_failure_reply(payload, raw_text=None):
    """Retain bounded invalid evidence privately; never export this object."""
    text = raw_text if raw_text is not None else dumps(payload)
    if len(text) <= 100000 and raw_text is None:
        return payload
    return {
        "text_excerpt": text[:100000],
        "characters": len(text),
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
        "truncated": len(text) > 100000,
        "format": "unparsed_reply" if raw_text is not None else "oversize_json",
    }


def normalized_rate_limits(result):
    buckets = result.get("rateLimitsByLimitId") or {"codex": result.get("rateLimits", {})}
    windows = []
    for key, bucket in buckets.items():
        for name in ("primary", "secondary"):
            window = bucket.get(name)
            if window:
                windows.append({"bucket": key, "kind": name, **window})
    return {
        "at": utc_now(), "windows": windows,
        "ordinary_usage_allowed": result.get("ordinaryUsageAllowed", True),
    }


def quota_change(before, after):
    """Compare one identified weekly bucket, never unlike percentage scales."""
    import math

    def windows(quota):
        result = []
        for window in quota.get("windows", []):
            if not isinstance(window, dict):
                continue
            values = [window.get(k) for k in ("usedPercent", "windowDurationMins", "resetsAt")]
            if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
                continue
            used, duration, reset = values
            if not 0 <= used <= 100 or duration < 10000:
                continue
            identity = (str(window.get("bucket", "")), str(window.get("kind", "")), duration, reset)
            result.append((identity, used))
        return result

    prior = windows(before)
    if not prior:
        return 0, False, {"status": "weekly_window_unavailable"}
    identity, used = min(prior, key=lambda item: (-item[1], item[0]))
    matches = [value for key, value in windows(after) if key == identity]
    unambiguous = sum(key == identity for key, _ in prior) == 1 and len(matches) == 1
    current = matches[0] if unambiguous else None
    reported = current is not None and current >= used
    basis = {
        "selection": "most_consumed_weekly_at_admission",
        "bucket_fingerprint": hashlib.sha256(dumps(identity[:2]).encode()).hexdigest()[:16],
        "kind": identity[1] if identity[1] in ("primary", "secondary") else "other",
        "window_duration_minutes": identity[2], "resets_at": identity[3],
        "before_used_percent": used, "after_used_percent": current,
        "status": "comparable" if reported else ("counter_decreased" if current is not None else "reset_or_unavailable"),
        "scope": "One account-wide meter change, including external usage; not project token consumption.",
    }
    return (current - used if reported else 0), reported, basis


def response_schema(model):
    """Transport requires every property, including locally defaulted fields.

    Pydantic defaults keep old stored records readable; model output must still
    state those fields explicitly. This does not weaken local model validation.
    """
    schema = model.model_json_schema()

    def visit(value):
        if isinstance(value, dict):
            value.pop("default", None)
            if value.get("type") == "object" and "properties" in value:
                value["required"] = list(value["properties"])
                value["additionalProperties"] = False
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(schema)
    return schema


class CodexRPC:
    """Authenticated subscription-only local harness; no OpenAI API client."""

    def __init__(self, config):
        self.config = config
        self.proc = self.selector = None
        self._closed = False
        self._cleanup_complete = False
        self._reaped = False
        self._kill_sent = False
        self._closed_resources = set()
        self._close_lock = threading.Lock()
        self._io_lock = threading.Lock()
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
        try:
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
        except BaseException as exc:
            try:
                self.close()
            except Exception as cleanup_error:
                exc.add_note("Codex initialization cleanup failed: " + type(cleanup_error).__name__)
            raise


    def send(self, message):
        with self._io_lock:
            if self._closed:
                raise AgentUnavailable("Codex client closed")
            self.proc.stdin.write((dumps(message) + "\n").encode())
            self.proc.stdin.flush()

    def receive(self, deadline):
        while time.monotonic() < deadline:
            if self._closed:
                raise AgentUnavailable("Codex client closed")
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
            with self._io_lock:
                if self._closed:
                    raise AgentUnavailable("Codex client closed")
                ready = self.selector.select(min(1, max(0.01, deadline - time.monotonic())))
                if self._closed:
                    raise AgentUnavailable("Codex client closed")
                if ready:
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
        return normalized_rate_limits(self.rpc("account/rateLimits/read"))

    def models(self):
        return self.rpc("model/list", {"limit": 100}).get("data", [])

    def run(self, thread_id, prompt, model, effort, schema, *, max_searches=8, max_cycles=25):
        # Kept on the RPC instance so an interruption cannot discard reported
        # tokens, turn identity or the phase that failed before run() returns.
        self.last_attempt = {"phase": "thread_setup", "state": "started", "usage": {}}
        try:
            result = self._run(
                thread_id, prompt, model, effort, schema,
                max_searches=max_searches, max_cycles=max_cycles,
            )
            self.last_attempt["state"] = "completed"
            return result
        except Exception:
            self.last_attempt["state"] = "failed"
            raise

    def _run(self, thread_id, prompt, model, effort, schema, *, max_searches=8, max_cycles=25):
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
        self.last_attempt.update({"thread_id": thread_id, "phase": "turn_start"})
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
        self.last_attempt.update({"turn_id": turn_id, "phase": "turn_stream"})
        end = time.monotonic() + self.config.max_agent_seconds
        output, usage, cycles, searches = "", {}, 0, 0
        budget_notice = False
        budget_notice_status = "not_sent"
        web_inflight = 0
        pending = list(self.backlog)
        self.backlog.clear()
        while True:
            self.last_attempt["counters"] = {
                "searches": searches,
                "cycles": cycles,
                "budget_notice": budget_notice,
                "budget_notice_status": budget_notice_status,
            }
            msg = pending.pop(0) if pending else self.receive(end)
            if msg.get("id") == 999998:
                budget_notice_status = "rejected" if msg.get("error") else "accepted"
                continue
            params = msg.get("params", {})
            if params.get("threadId", thread_id) != thread_id:
                continue
            if params.get("turnId", turn_id) != turn_id:
                continue
            method = msg.get("method", "")
            if method == "turn/completed" and params.get("turn", {}).get("id", turn_id) != turn_id:
                continue
            if method == "account/rateLimits/updated":
                quota = normalized_rate_limits(params)
                self.last_attempt["quota"] = quota
                reason = account_limit_reason(quota)
                if reason:
                    self.last_attempt["phase"] = "quota_interrupt"
                    self.last_attempt["quota_stop_reason"] = reason
                    self.send({
                        "id": 999999, "method": "turn/interrupt",
                        "params": {"threadId": thread_id, "turnId": turn_id},
                    })
                    raise AgentUnavailable(reason)
            if method == "item/started":
                item = params.get("item", {})
                cycles += 1
                if item.get("type") == "webSearch":
                    searches += 1
                    web_inflight += 1
                if cycles > max_cycles or searches > max_searches:
                    self.send(
                        {
                            "id": 999999,
                            "method": "turn/interrupt",
                            "params": {"threadId": thread_id, "turnId": turn_id},
                        }
                    )
                    raise AgentUnavailable("Task search/tool budget exhausted")
            # Let an in-flight source finish before asking for the final answer.
            # Hard ceilings above still interrupt at tool start.
            if method == "item/completed":
                if params.get("item", {}).get("type") == "webSearch":
                    web_inflight = max(0, web_inflight - 1)
                if (
                    not budget_notice
                    and not web_inflight
                    and (
                        (max_searches > 1 and searches >= max_searches - 1)
                        or cycles >= max_cycles - 3
                    )
                ):
                    self.send(
                        {
                            "id": 999998,
                            "method": "turn/steer",
                            "params": {
                                "threadId": thread_id,
                                "expectedTurnId": turn_id,
                                "input": [
                                    {
                                        "type": "text",
                                        "text": "The bounded task budget is nearly exhausted. Finish now with the evidence already obtained, explicit unknowns, and the required JSON schema. Do not request more tools.",
                                    }
                                ],
                            },
                        }
                    )
                    budget_notice = True
                    budget_notice_status = "pending"
            if method == "item/agentMessage/delta":
                output += params.get("delta", "")
                if len(output) > 100000:
                    raise AgentUnavailable("Task output budget exhausted")
            if method == "item/completed":
                item = params.get("item", {})
                if item.get("type") == "agentMessage":
                    output = item.get("text", output)
                    if len(output) > 100000:
                        raise AgentUnavailable("Task output budget exhausted")
            if method == "thread/tokenUsage/updated":
                usage = params.get("tokenUsage", {})
                self.last_attempt["usage"] = usage
            if method == "turn/completed":
                result_turn = params.get("turn", {})
                self.last_attempt["turn_status"] = result_turn.get("status", "unknown")
                if result_turn.get("status") != "completed":
                    raise AgentUnavailable("Codex turn failed or was interrupted")
                break
        self.last_attempt["phase"] = "reply_json"
        self.last_attempt["raw_reply"] = output
        payload = json.loads(output)
        self.last_attempt.pop("raw_reply", None)
        self.last_attempt["phase"] = "reply_complete"
        return (
            thread_id,
            payload,
            usage,
            {
                "searches": searches,
                "cycles": cycles,
                "budget_notice": budget_notice,
                "budget_notice_status": budget_notice_status,
            },
        )

    def close(self):
        import signal

        with self._close_lock:
            if self._cleanup_complete:
                return
            self._closed = True
            try:
                if self.proc is not None and not self._reaped:
                    if not self._kill_sent:
                        try:
                            os.killpg(self.proc.pid, signal.SIGTERM)
                        except ProcessLookupError:
                            pass
                        try:
                            self.proc.wait(timeout=5)
                            self._reaped = True
                        except subprocess.TimeoutExpired:
                            try:
                                os.killpg(self.proc.pid, signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                            self._kill_sent = True
                    if not self._reaped:
                        self.proc.wait(timeout=5)
                        self._reaped = True
            finally:
                # receive() holds this lock for at most its one-second selector
                # wait; marking closed above prevents another read from starting.
                with self._io_lock:
                    try:
                        self._close_resource("selector", self.selector)
                    finally:
                        try:
                            self._close_resource("stdin", self.proc.stdin if self.proc else None)
                        finally:
                            self._close_resource("stdout", self.proc.stdout if self.proc else None)
            self._cleanup_complete = True

    def _close_resource(self, name, resource):
        if resource is not None and name not in self._closed_resources:
            resource.close()
            self._closed_resources.add(name)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def record_application_outcome(store, task_key, outcome, validation_code=None):
    """Link application validation to inference without rewriting token evidence."""
    if outcome not in ("accepted", "rejected", "deferred"):
        raise ValueError("Unsupported application outcome")
    if not task_key:
        return None
    from .research_work import WORK_VALIDATION_CODES
    from contextlib import nullcontext

    code = None
    if outcome == "rejected":
        code = (
            validation_code
            if isinstance(validation_code, str) and validation_code in WORK_VALIDATION_CODES
            else "application_error"
        )
    with (nullcontext() if store.db.in_transaction else store.transaction()):
        row = store.db.execute(
            "SELECT id,payload FROM usage WHERE json_extract(payload,'$.task_key')=? "
            "ORDER BY id DESC LIMIT 1", (task_key,),
        ).fetchone()
        if row is None:
            return None  # Data-only tasks have no inference attempt.
        payload = json.loads(row["payload"])
        if payload.get("state") != "completed" or payload.get("terminal_outcome") != "validated":
            return None
        prior = payload.get("application_outcome")
        if prior in ("accepted", "rejected", "deferred"):
            return row["id"] if prior == outcome else None
        payload.update({
            "application_outcome": outcome,
            "application_at": utc_now(),
            "application_validation_code": code,
        })
        store.db.execute("UPDATE usage SET payload=? WHERE id=?", (dumps(payload), row["id"]))
    return row["id"]


def run_task(
    config, role, prompt, response_model, model, effort, day, *, searches=8, cycles=25,
    scope=None, task_key=None
):
    from .store import Store

    if len(prompt) > config.max_input_chars:
        raise AgentUnavailable(
            "Complete evidence packet exceeds input budget; shrink whole records before calling the model"
        )
    schema = response_schema(response_model)
    schema_id = hashlib.sha256(dumps(schema).encode()).hexdigest()
    prompt_id = hashlib.sha256(prompt.encode()).hexdigest()
    # An explicit durable job key links retries even if refreshed evidence changes
    # the prompt. Without one, only identical requests are grouped together.
    request_id = hashlib.sha256(
        dumps([day, role, scope, task_key or prompt_id, schema_id]).encode()
    ).hexdigest()
    phase = "quota_preflight"
    store = Store(config.state_dir / "trader.sqlite3")
    try:
        with CodexRPC(config) as rpc:
            before = rpc.rate_limits()
            store.set("quota", before)
            # Independent probes and the daemon share this ledger. Admission and
            # the counted reservation must be atomic across their connections;
            # no network request or inference is performed under this lock.
            with store.transaction():
                admitted_at = datetime.now(timezone.utc)
                usage_day = admitted_at.astimezone(ET).date().isoformat()
                allowed, reason = budget_check(store, before, role, admitted_at)
                if not allowed:
                    store.set("entry_budget_blocked", True)
                    store.event("budget_skip", {"role": role, "reason": reason})
                else:
                    previous = store.rows(
                        "SELECT id FROM usage WHERE json_extract(payload,'$.request_id')=? "
                        "ORDER BY id DESC LIMIT 1", (request_id,),
                    )
                    attempt = {
                        "state": "started", "request_id": request_id,
                        "task_key": task_key, "task_day": day,
                        "schema_id": schema_id, "schema_name": response_model.__name__,
                        "previous_attempt_id": "usage:" + str(previous[0]["id"]) if previous else None,
                        "started_at": admitted_at.isoformat(),
                    }
                    cursor = store.db.execute(
                        "INSERT INTO usage(at,day,role,model,input_tokens,cached_tokens,output_tokens,quota_delta,payload) VALUES(?,?,?,?,0,0,0,0,?)",
                        (admitted_at.isoformat(), usage_day, role, model, dumps(attempt)),
                    )
                    reserved_id = cursor.lastrowid
                    attempt["attempt_id"] = "usage:" + str(reserved_id)
                    store.db.execute(
                        "UPDATE usage SET payload=? WHERE id=?", (dumps(attempt), reserved_id)
                    )
            if not allowed:
                raise AgentUnavailable(reason)
            usage_id = reserved_id
            # Give the reviewer fresh context rather than the researcher's thread.
            thread_key = (
                f"thread:research_validation:{day}"
                if role == "research_validation"
                else f"thread:{day}:{role}"
            )
            if scope:
                thread_key = f"thread:probe:{scope}:{role}"
            thread_id = store.get(thread_key)
            context_key = "context-policy:" + thread_key
            context = store.get(context_key, {})
            # Explicit memory is the durable handoff; do not grow one cross-role
            # transcript indefinitely or expose a reviewer to the author's history.
            fresh_roles = (
                "decision",
                "position_review",
                "research_validation",
                "research_audit_review",
                "probe_validation",
                "deep_research_review",
            )
            rotated = bool(
                thread_id
                and (
                    role in fresh_roles
                    or context.get("turns", 0) >= 2
                    or context.get("last_input_tokens", 0) > 48000
                )
            )
            if rotated:
                thread_id = None
                context = {}
            phase = "inference"
            t, payload, usage, counters = rpc.run(
                thread_id,
                prompt,
                model,
                effort,
                schema,
                max_searches=searches,
                max_cycles=cycles,
            )
            store.set(thread_key, t)
            phase = "schema_validation"
            parsed = response_model.model_validate(payload)
            phase = "metadata_refresh"
            metadata_errors = []
            try:
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
            except Exception as refresh_error:
                metadata_errors.append({
                    "phase": "model_catalog_refresh", "error_type": type(refresh_error).__name__
                })
            try:
                after = rpc.rate_limits()
            except Exception as refresh_error:
                metadata_errors.append({
                    "phase": "quota_refresh", "error_type": type(refresh_error).__name__
                })
                after = {"at": utc_now(), "windows": [], "ordinary_usage_allowed": False}
            store.set("quota", after)
            store.set(
                "entry_budget_blocked",
                bool(metadata_errors)
                or not store.get("readiness", {}).get("models_available", False)
                or bool(account_limit_reason(after)),
            )
            delta, delta_reported, delta_basis = quota_change(before, after)
            last = usage.get("last") or usage.get("total") or {}
            store.set(
                context_key,
                {
                    "turns": context.get("turns", 0) + 1,
                    "last_input_tokens": last.get("inputTokens", 0),
                    "at": utc_now(),
                },
            )
            phase = "result_persistence"
            completed = {
                **attempt, **counters, "state": "completed", "terminal_outcome": "validated",
                "completed_at": utc_now(), "quota_delta_reported": delta_reported,
                "quota_delta_basis": delta_basis,
                "reply_usage_reported": "inputTokens" in last or "outputTokens" in last,
                "metadata_errors": metadata_errors,
                "application_outcome": "pending" if task_key else "untracked",
            }
            store.db.execute(
                """UPDATE usage SET at=?,day=?,role=?,model=?,input_tokens=?,cached_tokens=?,output_tokens=?,quota_delta=?,payload=? WHERE id=?""",
                (
                    utc_now(),
                    usage_day,
                    role,
                    model,
                    last.get("inputTokens", 0),
                    last.get("cachedInputTokens", 0),
                    last.get("outputTokens", 0),
                    delta,
                    dumps(completed),
                    usage_id,
                ),
            )
            store.event(
                "agent_task", {
                    "role": role, "model": model, "context_rotated": rotated,
                    **{k: v for k, v in completed.items() if k != "task_key"},
                }
            )
            return parsed.model_dump(mode="json")
    except Exception as exc:
        if "usage_id" in locals():
            rpc_attempt = getattr(rpc, "last_attempt", {})
            failed_phase = rpc_attempt.get("phase", phase) if phase == "inference" else phase
            outcome = {
                "schema_validation": "schema_rejected",
                "reply_json": "invalid_json",
                "quota_interrupt": "quota_interrupted",
                "result_persistence": "persistence_failed",
            }.get(failed_phase, "inference_failed")
            failure = {
                **attempt,
                **rpc_attempt.get("counters", {}),
                "state": "failed",
                "error_type": type(exc).__name__,
                "phase": failed_phase,
                "terminal_outcome": outcome,
                "completed_at": utc_now(),
                **validation_diagnostics(exc, schema),
                "partial_tokens": "unavailable unless reported before interruption",
            }
            if rpc_attempt.get("quota"):
                store.set("quota", rpc_attempt["quota"])
                store.set("entry_budget_blocked", True)
                failure["quota_stop_reason"] = rpc_attempt.get("quota_stop_reason")
            if "usage" in locals():
                measured_usage = usage
                failure.update(counters)
            else:
                measured_usage = rpc_attempt.get("usage", {})
            measured = measured_usage.get("last") or measured_usage.get("total") or measured_usage
            failure["reply_usage_reported"] = "inputTokens" in measured or "outputTokens" in measured
            if failure["reply_usage_reported"]:
                failure["partial_tokens"] = (
                    "completed reply usage retained; application validation failed"
                    if failed_phase == "schema_validation"
                    else "reported usage retained; full turn total may be unavailable"
                )
            has_reply = "payload" in locals() or "raw_reply" in rpc_attempt
            if has_reply:
                from .quality import record_artifact

                try:
                    reply = bounded_failure_reply(
                        payload if "payload" in locals() else None, rpc_attempt.get("raw_reply")
                    )
                    artifact_id = "agent-attempt:" + str(usage_id)
                    store.memory_put(artifact_id, "agent_attempt_artifact", {
                        **failure, "day": day, "role": role,
                        "task_key": task_key, "prompt_id": prompt_id,
                        "thread_id": rpc_attempt.get("thread_id"),
                        "turn_id": rpc_attempt.get("turn_id"), "reply": reply,
                    })
                    failure["artifact_id"] = artifact_id
                    if failed_phase == "schema_validation":
                        record_artifact(
                            store, day, role, reply, "schema-rejected:" + str(usage_id), "rejected"
                        )
                except Exception as capture_error:
                    failure["artifact_capture_error"] = type(capture_error).__name__
            store.db.execute(
                "UPDATE usage SET input_tokens=?,cached_tokens=?,output_tokens=?,payload=? WHERE id=?",
                (
                    measured.get("inputTokens", 0), measured.get("cachedInputTokens", 0),
                    measured.get("outputTokens", 0), dumps(failure), usage_id,
                ),
            )
            store.event("agent_task_failed", {
                "role": role, "model": model,
                **{k: v for k, v in failure.items() if k != "task_key"},
            })
        raise
    finally:
        store.close()
