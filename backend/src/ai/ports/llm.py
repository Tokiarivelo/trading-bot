"""LLMPort (§6.7): provider-agnostic interface for every AI task.

Only `ai/application/` calls this; nothing else in the backend talks to
Claude/Ollama directly, so swapping a task's provider is a `configs/ai.yaml`
edit, not a code change.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class LLMMessage:
    system: str
    user: str


#: Provider ids the settings page (AI_PROVIDER_SETTINGS_PLAN.md) and
#: `LLMRouter` know how to build an adapter for. "Hermes Agent" is not a
#: separate id — it's a `hermes3:*` model preset on top of "ollama" (see
#: plan §2.2). "openclaw" ships as an explicitly unverified integration
#: (plan §2.4/§9.4) until its real API contract is confirmed. "openai",
#: "mistral", "groq", "deepseek", and "xai" all speak the same
#: OpenAI-compatible chat-completions wire format as "openclaw"
#: (`adapters/openai_compatible.py`); "gemini" has its own wire contract
#: (`adapters/gemini.py`).
KNOWN_PROVIDERS = (
    "claude",
    "openai",
    "gemini",
    "mistral",
    "groq",
    "deepseek",
    "xai",
    "claude_code",
    "openclaw",
    "ollama",
)


@dataclass(frozen=True)
class ProviderSpec:
    """One `configs/ai.yaml: provider_per_task` entry (or a settings-page
    override) — which adapter and model to use for a named AI task
    (e.g. "pdf_extraction")."""

    provider: str  # one of KNOWN_PROVIDERS
    model: str


@runtime_checkable
class LLMPort(Protocol):
    async def complete(self, message: LLMMessage, *, max_tokens: int = 4096) -> str:
        """Return the model's raw text completion for `message`.

        Callers that need structured output (e.g. a `StrategySpec` JSON
        object) are responsible for prompting for JSON and parsing the
        result themselves — this port stays a plain text-in/text-out
        boundary so both providers implement the same tiny surface.
        """
        ...
