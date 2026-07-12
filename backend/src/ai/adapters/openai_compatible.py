"""Shared adapter for every `LLMPort` provider whose HTTP contract is the
common `POST {base_url}/chat/completions` Bearer-token shape — OpenAI, Groq,
Mistral, DeepSeek, xAI, and (assumed, unverified) OpenClaw all speak this
wire format, so one class covers all of them; `container.py` picks the
`base_url` per provider. Adding a sixth OpenAI-compatible provider is a new
factory entry there, not a new adapter class.
"""

from __future__ import annotations

import httpx

from src.ai.ports.llm import LLMMessage


class OpenAICompatibleAdapter:
    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        # A trailing slash plus a relative (no leading "/") request path is
        # required for httpx to append to `base_url`'s path instead of
        # replacing it — an absolute "/chat/completions" would resolve
        # against the host root and silently drop e.g. OpenAI's "/v1".
        self._base_url = base_url if base_url.endswith("/") else f"{base_url}/"
        self._api_key = api_key
        self._model = model

    async def complete(self, message: LLMMessage, *, max_tokens: int = 4096) -> str:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=120.0) as client:
            response = await client.post(
                "chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self._model,
                    "max_tokens": max_tokens,
                    "messages": [
                        {"role": "system", "content": message.system},
                        {"role": "user", "content": message.user},
                    ],
                },
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
