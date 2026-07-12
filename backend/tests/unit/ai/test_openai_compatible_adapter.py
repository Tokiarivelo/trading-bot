"""OpenAICompatibleAdapter — the shared wire-format adapter used directly for
OpenAI, Groq, Mistral, DeepSeek, and xAI (each just a different `base_url`),
and via `OpenClawAdapter` for OpenClaw. `test_openclaw_adapter.py` covers the
subclass; these tests pin down the base class against a real `base_url` that
has a path component (e.g. OpenAI's "/v1"), since that's the case where a
naive leading-slash request path would silently drop it."""

from __future__ import annotations

import httpx
import pytest

from src.ai.adapters import openai_compatible as openai_compatible_module
from src.ai.adapters.openai_compatible import OpenAICompatibleAdapter
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


async def test_complete_preserves_base_url_path_component(monkeypatch):
    captured = {}

    def handler(base_url, path, headers, json):
        captured["base_url"] = base_url
        captured["path"] = path
        request = httpx.Request("POST", f"https://api.openai.com/v1/{path}")
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "pong"}}]}, request=request
        )

    _patch_client(monkeypatch, handler)

    adapter = OpenAICompatibleAdapter("https://api.openai.com/v1", "sk-test", "gpt-5.6-luna")
    result = await adapter.complete(LLMMessage(system="sys", user="ping"))

    assert result == "pong"
    # A base_url without a trailing slash gets one added, and the request
    # path stays relative (no leading "/") — together these make httpx
    # append to "/v1" instead of replacing it.
    assert captured["base_url"] == "https://api.openai.com/v1/"
    assert captured["path"] == "chat/completions"


async def test_complete_sends_bearer_auth_and_messages(monkeypatch):
    captured = {}

    def handler(base_url, path, headers, json):
        captured["headers"] = headers
        captured["json"] = json
        request = httpx.Request("POST", f"https://api.groq.com/openai/v1/{path}")
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "pong"}}]}, request=request
        )

    _patch_client(monkeypatch, handler)

    adapter = OpenAICompatibleAdapter(
        "https://api.groq.com/openai/v1", "gsk-test", "openai/gpt-oss-20b"
    )
    await adapter.complete(LLMMessage(system="sys", user="ping"), max_tokens=128)

    assert captured["headers"]["Authorization"] == "Bearer gsk-test"
    assert captured["json"]["model"] == "openai/gpt-oss-20b"
    assert captured["json"]["max_tokens"] == 128
    assert captured["json"]["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "ping"},
    ]


async def test_http_error_status_raises(monkeypatch):
    def handler(base_url, path, headers, json):
        request = httpx.Request("POST", f"https://api.openai.com/v1/{path}")
        return httpx.Response(401, text="invalid api key", request=request)

    _patch_client(monkeypatch, handler)

    adapter = OpenAICompatibleAdapter("https://api.openai.com/v1", "bad-key", "gpt-5.6-luna")
    with pytest.raises(httpx.HTTPStatusError):
        await adapter.complete(LLMMessage(system="s", user="u"))
