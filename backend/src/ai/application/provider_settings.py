"""Settings-page application service (AI_PROVIDER_SETTINGS_PLAN.md §6.5): the
only place that turns a settings-page write into both a persisted override
(`ProviderConfigRepository`, survives a restart) and a live `LLMRouter`
override (takes effect on the task's very next call, no restart needed).
`ai/api/routes_settings.py` (Phase 10.3) is a thin wrapper around this.
"""

from __future__ import annotations

from src.ai.adapters.provider_config_repository import ProviderConfigRepository
from src.ai.adapters.provider_secret_store import ProviderSecretStore
from src.ai.application.llm_router import LLMProviderNotConfiguredError, LLMRouter
from src.ai.domain.provider_config import KNOWN_TASKS, ProviderTestResult, TaskProviderStatus
from src.ai.ports.llm import KNOWN_PROVIDERS, LLMMessage, ProviderSpec

#: A cheap, fixed model per provider — used both as `test_provider()`'s
#: throwaway connectivity probe model (deliberately not task-specific: the
#: endpoint tests a provider, not a task/model pairing) and as the
#: placeholder `ProviderSpec.model` for `provider_configured_map()`'s
#: `check_configured` calls, which never make a network call so the exact
#: model doesn't matter there. `openclaw`'s value is a guess, same as the
#: rest of its integration (plan §2.4/§9.4) — unverified until a real
#: instance confirms it.
_TEST_MODELS = {
    "claude": "claude-haiku-4-5",
    "openai": "gpt-5.6-luna",
    "gemini": "gemini-3.1-flash-lite",
    "mistral": "mistral-small-latest",
    "groq": "openai/gpt-oss-20b",
    "deepseek": "deepseek-v4-flash",
    "xai": "grok-4.3",
    "ollama": "hermes3:8b",
    "claude_code": "haiku",
    "openclaw": "default",
}

#: Providers whose adapter needs an API key at all — matches `needs_secret`
#: on the settings page's provider catalog (`routes_settings.py`). "ollama"
#: (local server URL only) and "claude_code" (local CLI binary) don't take a
#: key here.
_KEY_PROVIDERS = frozenset(KNOWN_PROVIDERS) - {"ollama", "claude_code"}

_TEST_MESSAGE = LLMMessage(system="", user="Reply with exactly one word: pong")


class UnknownTaskError(ValueError):
    """`task` is not one of `KNOWN_TASKS` — the settings page only ever
    offers the 4 real AI tasks, so this means a client bug, not an operator
    typo the UI could make."""


class UnknownProviderError(ValueError):
    """`provider` is not one of `KNOWN_PROVIDERS`."""


class ProviderSettingsService:
    def __init__(
        self,
        repository: ProviderConfigRepository,
        llm_router: LLMRouter,
        provider_secrets: ProviderSecretStore,
    ) -> None:
        self._repository = repository
        self._llm_router = llm_router
        self._provider_secrets = provider_secrets

    def list_tasks(self) -> list[TaskProviderStatus]:
        statuses = []
        for task in KNOWN_TASKS:
            status = self._status_for_task(task)
            if status is not None:
                statuses.append(status)
        return statuses

    def set_task_provider(self, task: str, provider: str, model: str) -> TaskProviderStatus:
        _validate_task(task)
        _validate_provider(provider)
        self._repository.set(task, provider, model)
        self._llm_router.set_override(task, ProviderSpec(provider=provider, model=model))
        status = self._status_for_task(task)
        assert status is not None  # we just set an override for it
        return status

    def clear_task_provider(self, task: str) -> TaskProviderStatus:
        _validate_task(task)
        self._repository.clear(task)
        self._llm_router.clear_override(task)
        status = self._status_for_task(task)
        if status is None:
            raise ValueError(f"task {task!r} has no configs/ai.yaml default to revert to")
        return status

    async def test_provider(self, provider: str, message: str | None = None) -> ProviderTestResult:
        _validate_provider(provider)
        spec = ProviderSpec(provider=provider, model=_TEST_MODELS[provider])
        probe = LLMMessage(system="", user=message) if message else _TEST_MESSAGE
        try:
            adapter = self._llm_router.build_adapter(spec)
            reply = await adapter.complete(probe, max_tokens=64 if message else 8)
        except LLMProviderNotConfiguredError as exc:
            return ProviderTestResult(provider=provider, ok=False, message=str(exc))
        except Exception as exc:
            return ProviderTestResult(provider=provider, ok=False, message=str(exc))
        return ProviderTestResult(provider=provider, ok=True, reply=reply if message else None)

    def set_provider_key(self, provider: str, api_key: str) -> None:
        """Save `provider`'s API key, encrypted at rest, taking precedence
        over its `.env` fallback immediately — `LLMRouter.clear_provider_cache`
        drops any adapter already cached with the old key/no key, so the
        very next call for any task on this provider picks it up, no
        backend restart needed (mirrors `set_task_provider`'s live-effect
        guarantee)."""
        _validate_provider(provider)
        if provider not in _KEY_PROVIDERS:
            raise UnknownProviderError(f"provider {provider!r} does not take an API key")
        self._provider_secrets.set(provider, api_key)
        self._llm_router.clear_provider_cache(provider)

    def clear_provider_key(self, provider: str) -> None:
        """Remove `provider`'s settings-page key, reverting it to its
        `.env` fallback (or "not configured" if that's empty too)."""
        _validate_provider(provider)
        self._provider_secrets.clear(provider)
        self._llm_router.clear_provider_cache(provider)

    def provider_configured_map(self) -> dict[str, bool]:
        """Whether each of `KNOWN_PROVIDERS` is usable right now — settings-page
        key, `.env` fallback, or (for ollama/claude_code) local URL/binary —
        without a network call or revealing any secret. Backs the provider
        catalog's per-row status badge (plan §6.5), independent of any task."""
        result = {}
        for provider in KNOWN_PROVIDERS:
            spec = ProviderSpec(provider=provider, model=_TEST_MODELS[provider])
            configured, _reason = self._llm_router.check_configured(spec)
            result[provider] = configured
        return result

    def _status_for_task(self, task: str) -> TaskProviderStatus | None:
        resolved = self._llm_router.resolve(task)
        if resolved is None:
            return None
        spec, source = resolved
        configured, _reason = self._llm_router.check_configured(spec)
        return TaskProviderStatus(
            task=task,
            provider=spec.provider,
            model=spec.model,
            source=source,
            configured=configured,
        )


def _validate_task(task: str) -> None:
    if task not in KNOWN_TASKS:
        raise UnknownTaskError(f"unknown AI task: {task!r} (known: {', '.join(KNOWN_TASKS)})")


def _validate_provider(provider: str) -> None:
    if provider not in KNOWN_PROVIDERS:
        raise UnknownProviderError(
            f"unknown LLM provider: {provider!r} (known: {', '.join(KNOWN_PROVIDERS)})"
        )
