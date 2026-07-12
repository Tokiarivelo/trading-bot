"""ClaudeCodeAdapter — headless `claude -p` subprocess calls
(AI_PROVIDER_SETTINGS_PLAN.md §9.1). Flags asserted here match what was
verified against a real Claude Code install: `--tools ""` (not
`--allowed-tools`), `--strict-mcp-config` with no `--mcp-config`, and no
`--system-prompt` (it defeats the CLI's own prompt cache)."""

from __future__ import annotations

import asyncio
import json

import pytest

from src.ai.adapters.claude_code import ClaudeCodeAdapter
from src.ai.ports.llm import LLMMessage


class _FakeProcess:
    def __init__(self, stdout: bytes, stderr: bytes = b"", returncode: int = 0) -> None:
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr


def _patch_subprocess(monkeypatch, process: _FakeProcess, captured: list):
    async def _fake_exec(*args, **kwargs):
        captured.append(args)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)


async def test_complete_returns_result_field(monkeypatch):
    payload = {"type": "result", "is_error": False, "result": "pong"}
    captured: list = []
    _patch_subprocess(monkeypatch, _FakeProcess(json.dumps(payload).encode()), captured)

    adapter = ClaudeCodeAdapter("claude", "sonnet")
    result = await adapter.complete(LLMMessage(system="sys", user="say pong"))

    assert result == "pong"


async def test_complete_disables_tools_and_mcp_and_session_persistence(monkeypatch):
    payload = {"type": "result", "is_error": False, "result": "ok"}
    captured: list = []
    _patch_subprocess(monkeypatch, _FakeProcess(json.dumps(payload).encode()), captured)

    adapter = ClaudeCodeAdapter("claude", "sonnet")
    await adapter.complete(LLMMessage(system="sys", user="user"))

    (args,) = captured
    assert args[0] == "claude"
    assert "-p" in args
    assert "--tools" in args
    assert args[args.index("--tools") + 1] == ""
    assert "--allowed-tools" not in args
    assert "--strict-mcp-config" in args
    assert "--mcp-config" not in args
    assert "--no-session-persistence" in args
    assert "--system-prompt" not in args
    assert "--model" in args
    assert args[args.index("--model") + 1] == "sonnet"


async def test_complete_folds_system_into_prompt_text(monkeypatch):
    payload = {"type": "result", "is_error": False, "result": "ok"}
    captured: list = []
    _patch_subprocess(monkeypatch, _FakeProcess(json.dumps(payload).encode()), captured)

    adapter = ClaudeCodeAdapter("claude", "sonnet")
    await adapter.complete(LLMMessage(system="SYS_TEXT", user="USER_TEXT"))

    (args,) = captured
    prompt = args[args.index("-p") + 1]
    assert "SYS_TEXT" in prompt
    assert "USER_TEXT" in prompt


async def test_nonzero_exit_raises(monkeypatch):
    captured: list = []
    _patch_subprocess(monkeypatch, _FakeProcess(b"", b"boom", returncode=1), captured)

    adapter = ClaudeCodeAdapter("claude", "sonnet")
    with pytest.raises(RuntimeError, match="boom"):
        await adapter.complete(LLMMessage(system="s", user="u"))


async def test_is_error_result_raises(monkeypatch):
    payload = {"type": "result", "is_error": True, "result": ""}
    captured: list = []
    _patch_subprocess(monkeypatch, _FakeProcess(json.dumps(payload).encode()), captured)

    adapter = ClaudeCodeAdapter("claude", "sonnet")
    with pytest.raises(RuntimeError, match="error result"):
        await adapter.complete(LLMMessage(system="s", user="u"))


async def test_extra_args_are_appended(monkeypatch):
    payload = {"type": "result", "is_error": False, "result": "ok"}
    captured: list = []
    _patch_subprocess(monkeypatch, _FakeProcess(json.dumps(payload).encode()), captured)

    adapter = ClaudeCodeAdapter("claude", "sonnet", extra_args="--agent reviewer")
    await adapter.complete(LLMMessage(system="s", user="u"))

    (args,) = captured
    assert "--agent" in args
    assert args[args.index("--agent") + 1] == "reviewer"
