"""Ollama adapter for `LLMPort` — local models over Ollama's HTTP API, the
free/offline fallback (§3, §6.7)."""

from __future__ import annotations

import httpx

from src.ai.ports.llm import LLMMessage


class OllamaAdapter:
    def __init__(self, base_url: str, model: str) -> None:
        self._base_url = base_url
        self._model = model

    async def complete(self, message: LLMMessage, *, max_tokens: int = 4096) -> str:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=120.0) as client:
            response = await client.post(
                "/api/chat",
                json={
                    "model": self._model,
                    "stream": False,
                    "options": {"num_predict": max_tokens},
                    "messages": [
                        {"role": "system", "content": message.system},
                        {"role": "user", "content": message.user},
                    ],
                },
            )
            response.raise_for_status()
            return response.json()["message"]["content"]
