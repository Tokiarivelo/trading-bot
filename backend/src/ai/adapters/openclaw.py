"""OpenClaw adapter for `LLMPort` (AI_PROVIDER_SETTINGS_PLAN.md §2.4, §9.4).

UNVERIFIED: OpenClaw's real API contract was not available when this adapter
was written. The wire format below assumes an OpenAI-compatible
`/v1/chat/completions` endpoint (bearer-token auth, `choices[0].message.content`
response) — the most common self-hosted-agent HTTP contract, chosen as a
reasonable placeholder rather than confirmed against real OpenClaw docs.
`LLMPort` is the only contract every caller depends on, so if the real
OpenClaw API differs, only this method's body needs to change. The settings
page must surface this provider as "beta / unverified" until confirmed.
"""

from __future__ import annotations

from src.ai.adapters.openai_compatible import OpenAICompatibleAdapter


class OpenClawAdapter(OpenAICompatibleAdapter):
    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        super().__init__(f"{base_url}/v1", api_key, model)
