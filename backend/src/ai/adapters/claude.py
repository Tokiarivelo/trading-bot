"""Claude adapter for `LLMPort` — the Anthropic SDK, and nothing else in the
backend imports `anthropic` directly."""

from __future__ import annotations

from anthropic import AsyncAnthropic

from src.ai.ports.llm import LLMMessage


class ClaudeAdapter:
    def __init__(self, api_key: str, model: str) -> None:
        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model

    async def complete(self, message: LLMMessage, *, max_tokens: int = 4096) -> str:
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=message.system,
            messages=[{"role": "user", "content": message.user}],
        )
        return "".join(block.text for block in response.content if block.type == "text")
