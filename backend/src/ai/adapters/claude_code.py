"""Claude Code adapter for `LLMPort` — headless `claude -p` subprocess calls
using the operator's local Claude Code login/subscription instead of
`TB_ANTHROPIC_API_KEY` (AI_PROVIDER_SETTINGS_PLAN.md §2.1, §9.1).

Flags are verified against a real Claude Code install, not guessed:
`--tools ""` (not `--allowed-tools`) fully disables the built-in tool set —
confirmed by a live call returning `"permission_denials":[]` with no
permission prompts — and `--strict-mcp-config` with no `--mcp-config`
guarantees zero MCP tools load. This keeps the call a pure text-in/text-out
boundary, never touching the filesystem/network/broker.

Do not add `--system-prompt`: a live comparison showed it invalidates the
CLI's own prompt cache (11,830 fresh cache-creation tokens, $0.071) instead
of avoiding the ~8.5k-11.8k token fixed overhead every headless call pays,
so `message.system` is folded into the prompt text like every other
LLMMessage instead.
"""

from __future__ import annotations

import asyncio
import json
import shlex

from src.ai.ports.llm import LLMMessage

_TIMEOUT_S = 180.0


class ClaudeCodeAdapter:
    def __init__(self, binary: str, model: str, extra_args: str = "") -> None:
        self._binary = binary
        self._model = model
        self._extra_args = shlex.split(extra_args) if extra_args else []

    async def complete(self, message: LLMMessage, *, max_tokens: int = 4096) -> str:
        # Claude Code manages output length itself (no CLI flag maps to
        # `max_tokens`); callers that need a hard cap should keep prompting
        # for concise output, same as they already do for the other adapters.
        del max_tokens
        prompt = f"{message.system}\n\n{message.user}"
        proc = await asyncio.create_subprocess_exec(
            self._binary,
            "-p",
            prompt,
            "--model",
            self._model,
            "--output-format",
            "json",
            "--tools",
            "",
            "--strict-mcp-config",
            "--no-session-persistence",
            *self._extra_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_TIMEOUT_S)
        if proc.returncode != 0:
            raise RuntimeError(f"claude code exited {proc.returncode}: {stderr.decode()[:500]}")
        payload = json.loads(stdout)
        if payload.get("is_error"):
            raise RuntimeError(f"claude code returned an error result: {payload!r}")
        return payload["result"]
