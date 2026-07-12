"""Gemini adapter for `LLMPort` — Google's Generative Language REST API.

Its wire contract differs from every other provider here (query-string API
key auth, `contents`/`parts` request shape, `candidates` response shape), so
unlike OpenAI/Groq/Mistral/DeepSeek/xAI it can't share `OpenAICompatibleAdapter`.
"""

from __future__ import annotations

import httpx

from src.ai.ports.llm import LLMMessage

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/"


class GeminiAdapter:
    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    async def complete(self, message: LLMMessage, *, max_tokens: int = 4096) -> str:
        async with httpx.AsyncClient(base_url=_BASE_URL, timeout=120.0) as client:
            response = await client.post(
                f"models/{self._model}:generateContent",
                params={"key": self._api_key},
                json={
                    "systemInstruction": {"parts": [{"text": message.system}]},
                    "contents": [{"role": "user", "parts": [{"text": message.user}]}],
                    "generationConfig": {"maxOutputTokens": max_tokens},
                },
            )
            response.raise_for_status()
            data = response.json()
            parts = data["candidates"][0]["content"]["parts"]
            return "".join(part.get("text", "") for part in parts)
