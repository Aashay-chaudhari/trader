"""Tests for CLI agent utility helpers."""

import json
import os

import agent_trader.utils.cli_agent as cli_agent


def test_is_cli_available_uses_resolved_binary(monkeypatch):
    monkeypatch.setattr(cli_agent, "resolve_cli_binary", lambda provider="claude": "C:\\tool.cmd")

    assert cli_agent.is_cli_available("claude") is True


def test_run_cli_agent_uses_resolved_binary_path(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        cli_agent,
        "resolve_cli_binary",
        lambda provider="claude": "C:\\Users\\test\\AppData\\Roaming\\npm\\claude.cmd",
    )

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs

        class Result:
            returncode = 0
            stdout = json.dumps({
                "result": json.dumps({"overall_sentiment": "neutral", "stocks": {}}),
                "session_id": "sess_test",
                "num_turns": 1,
                "cost_usd": 0,
                "input_tokens": 1,
                "output_tokens": 1,
            })
            stderr = ""

        return Result()

    monkeypatch.setattr(cli_agent.subprocess, "run", fake_run)

    result = cli_agent.run_cli_agent(
        "Return JSON",
        provider="claude",
        max_turns=1,
        timeout_seconds=30,
        allowed_tools=["Read"],
    )

    assert captured["cmd"][0].endswith("claude.cmd")
    assert captured["cmd"][1:] == [
        "-p",
        "Return JSON",
        "--output-format",
        "json",
        "--max-turns",
        "1",
        "--allowedTools",
        "Read",
    ]
    assert captured["kwargs"]["cwd"] == str(cli_agent.Path.cwd())
    assert result["_meta"]["status"] == "success"
    assert result["_meta"]["provider"] == "cli:claude"


def test_run_cli_agent_surfaces_cli_json_error(monkeypatch):
    monkeypatch.setattr(
        cli_agent,
        "resolve_cli_binary",
        lambda provider="claude": "C:\\Users\\test\\AppData\\Roaming\\npm\\claude.cmd",
    )

    def fake_run(cmd, **kwargs):
        class Result:
            returncode = 1
            stdout = json.dumps({
                "type": "result",
                "subtype": "success",
                "is_error": True,
                "result": "You've hit your limit",
                "session_id": "sess_limit",
                "num_turns": 1,
                "total_cost_usd": 0,
                "usage": {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "service_tier": "standard",
                },
            })
            stderr = ""

        return Result()

    monkeypatch.setattr(cli_agent.subprocess, "run", fake_run)

    result = cli_agent.run_cli_agent(
        "Return JSON",
        provider="claude",
        max_turns=1,
        timeout_seconds=30,
    )

    assert result["_meta"]["status"] == "error"
    assert result["_meta"]["error"] == "You've hit your limit"
    assert result["_meta"]["cost_usd"] == 0
    assert result["_meta"]["usage"]["service_tier"] == "standard"


def test_run_cli_agent_codex_writes_output_file_without_search_flag(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        cli_agent,
        "resolve_cli_binary",
        lambda provider="codex": "C:\\Users\\test\\AppData\\Roaming\\npm\\codex.cmd",
    )

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        output_path = cli_agent.Path(cmd[cmd.index("-o") + 1])
        output_path.write_text(
            json.dumps({"overall_sentiment": "neutral", "stocks": {}}),
            encoding="utf-8",
        )

        class Result:
            returncode = 0
            stdout = json.dumps({"type": "result", "usage": {"input_tokens": 12}})
            stderr = ""

        return Result()

    monkeypatch.setattr(cli_agent.subprocess, "run", fake_run)

    result = cli_agent.run_cli_agent(
        "Return JSON",
        provider="codex",
        model="gpt-5.4",
        timeout_seconds=30,
    )

    assert captured["cmd"][0].endswith("codex.cmd")
    assert "--search" not in captured["cmd"]
    assert "--output-schema" not in captured["cmd"]
    assert captured["cmd"][1:7] == [
        "exec",
        "-",
        "--skip-git-repo-check",
        "--full-auto",
        "-s",
        "danger-full-access",
    ]
    assert "--json" in captured["cmd"]
    assert "-o" in captured["cmd"]
    assert captured["kwargs"]["input"] == "Return JSON"
    assert result["_meta"]["status"] == "success"
    assert result["_meta"]["provider"] == "cli:codex"
    assert result["_meta"]["model"] == "gpt-5.4"


def test_resolve_cli_binary_checks_windows_cmd_shim(monkeypatch):
    monkeypatch.setattr(cli_agent.shutil, "which", lambda name: None if name == "claude" else "C:\\tool.cmd")
    monkeypatch.setattr(cli_agent.os, "name", "nt")

    assert cli_agent.resolve_cli_binary("claude") == "C:\\tool.cmd"


def test_resolve_cli_binary_returns_none_when_not_found(monkeypatch):
    monkeypatch.setattr(cli_agent.shutil, "which", lambda name: None)
    monkeypatch.setattr(cli_agent.os, "name", "posix")

    assert cli_agent.resolve_cli_binary("claude") is None
