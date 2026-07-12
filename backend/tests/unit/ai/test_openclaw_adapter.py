"""OpenClawAdapter — UNVERIFIED assumed OpenAI-compatible chat-completions
contract (AI_PROVIDER_SETTINGS_PLAN.md §2.4/§9.4). These tests pin down the
adapter's own behavior against its assumed wire format; if OpenClaw's real
API differs, only `OpenClawAdapter`/`OpenAICompatibleAdapter` and this file
should need to change — `LLMPort` callers are unaffected either way."""

from __future__ import annotations

import httpx
import pytest

from src.ai.adapters import openai_compatible as openai_compatible_module
from src.ai.adapters.openclaw import OpenClawAdapter
from src.ai.ports.llm import LLMMessage


class _FakeAsyncClient:
    def __init__(self, handler, **kwargs) -> None:
        self._handler = handler
        self.base_url = kwargs.get("base_url")

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def post(self, path: str, *, headers=None, json=None) -> httpx.Response:
        return self._handler(self.base_url, path, headers, json)


def _patch_client(monkeypatch, handler):
    monkeypatch.setattr(
        openai_compatible_module.httpx,
        "AsyncClient",
        lambda **kwargs: _FakeAsyncClient(handler, **kwargs),
    )


async def test_complete_sends_openai_compatible_request_and_parses_response(monkeypatch):
    captured = {}

    def handler(base_url, path, headers, json):
        captured["base_url"] = base_url
        captured["path"] = path
        captured["headers"] = headers
        captured["json"] = json
        request = httpx.Request("POST", f"http://openclaw.local/v1/{path}")
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "pong"}}]}, request=request
        )

    _patch_client(monkeypatch, handler)

    adapter = OpenClawAdapter("http://openclaw.local", "secret-key", "openclaw-1")
    result = await adapter.complete(LLMMessage(system="sys", user="ping"), max_tokens=256)

    assert result == "pong"
    assert captured["base_url"] == "http://openclaw.local/v1/"
    assert captured["path"] == "chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer secret-key"
    assert captured["json"]["model"] == "openclaw-1"
    assert captured["json"]["max_tokens"] == 256
    assert captured["json"]["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "ping"},
    ]


async def test_http_error_status_raises(monkeypatch):
    def handler(base_url, path, headers, json):
        request = httpx.Request("POST", f"http://openclaw.local/v1/{path}")
        return httpx.Response(500, text="server error", request=request)

    _patch_client(monkeypatch, handler)

    adapter = OpenClawAdapter("http://openclaw.local", "secret-key", "openclaw-1")
    with pytest.raises(httpx.HTTPStatusError):
        await adapter.complete(LLMMessage(system="s", user="u"))
