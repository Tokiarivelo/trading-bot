"""Per-task LLM provider selection (§6.7, `configs/ai.yaml: provider_per_task`).

`ai/application/` services ask for an `LLMPort` by task name; this is the
only place that turns a `ProviderSpec` into a concrete Claude/Ollama adapter,
so re-pointing a task at a different provider is a config edit.
"""

from __future__ import annotations

from src.ai.adapters.claude import ClaudeAdapter
from src.ai.adapters.ollama import OllamaAdapter
from src.ai.ports.llm import LLMPort, ProviderSpec


class LLMProviderNotConfiguredError(Exception):
    """The task's provider is missing a required setting (e.g. no API key).

    Distinct from a plain `ValueError` so API routes can map it to 503
    ("this needs an operator to fix config/secrets") rather than a generic
    500, and distinct from network/auth errors the provider SDK itself
    raises once a call is actually attempted."""


class LLMRouter:
    def __init__(
        self,
        provider_per_task: dict[str, ProviderSpec],
        *,
        anthropic_api_key: str,
        ollama_url: str,
    ) -> None:
        self._provider_per_task = provider_per_task
        self._anthropic_api_key = anthropic_api_key
        self._ollama_url = ollama_url
        self._cache: dict[str, LLMPort] = {}

    def for_task(self, task: str) -> LLMPort:
        if task not in self._cache:
            if task not in self._provider_per_task:
                raise ValueError(f"no LLM provider configured for task {task!r} in ai.yaml")
            self._cache[task] = self._build(self._provider_per_task[task])
        return self._cache[task]

    def _build(self, spec: ProviderSpec) -> LLMPort:
        if spec.provider == "claude":
            if not self._anthropic_api_key:
                raise LLMProviderNotConfiguredError(
                    "provider 'claude' selected but TB_ANTHROPIC_API_KEY is not set — "
                    "add it to .env or switch this task to 'ollama' in configs/ai.yaml"
                )
            return ClaudeAdapter(self._anthropic_api_key, spec.model)
        if spec.provider == "ollama":
            return OllamaAdapter(self._ollama_url, spec.model)
        raise ValueError(f"unknown LLM provider: {spec.provider!r}")
