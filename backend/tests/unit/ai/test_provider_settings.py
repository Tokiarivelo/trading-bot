"""Settings-page application service (AI_PROVIDER_SETTINGS_PLAN.md §6.5):
list/set/clear resolve through a real `LLMRouter` (in-memory, deterministic)
wired with fake provider factories, against a fake in-memory repository —
`test_llm_router.py` already covers `LLMRouter` resolution/caching in
isolation, so these tests focus on the service's validation and persistence
wiring instead of re-deriving router behavior."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.ai.application.llm_router import LLMProviderNotConfiguredError, LLMRouter
from src.ai.application.provider_settings import (
    ProviderSettingsService,
    UnknownProviderError,
    UnknownTaskError,
)
from src.ai.domain.provider_config import TaskProviderOverride
from src.ai.ports.llm import LLMMessage, ProviderSpec

_DEFAULTS = {
    "pdf_extraction": ProviderSpec(provider="claude", model="claude-sonnet-5"),
    "code_generation": ProviderSpec(provider="claude", model="claude-sonnet-5"),
    "ten_trade_review": ProviderSpec(provider="claude", model="claude-haiku-4-5"),
    "code_refinement": ProviderSpec(provider="claude", model="claude-sonnet-5"),
}


class _FakeAdapter:
    def __init__(self, behavior: str) -> None:
        self._behavior = behavior

    async def complete(self, message: LLMMessage, *, max_tokens: int = 4096) -> str:
        if self._behavior == "error":
            raise RuntimeError("connection refused")
        return "pong"


def _factories(secret_store: _FakeSecretStore) -> dict:
    def _claude(spec: ProviderSpec):
        return _FakeAdapter("ok")

    def _ollama(spec: ProviderSpec):
        return _FakeAdapter("error")

    def _claude_code(spec: ProviderSpec):
        raise LLMProviderNotConfiguredError("provider 'claude_code' binary not found on PATH")

    def _openai(spec: ProviderSpec):
        if not secret_store.get("openai"):
            raise LLMProviderNotConfiguredError("provider 'openai' selected but no API key is set")
        return _FakeAdapter("ok")

    return {
        "claude": _claude,
        "ollama": _ollama,
        "claude_code": _claude_code,
        "openai": _openai,
    }


class _FakeRepository:
    def __init__(self) -> None:
        self._overrides: dict[str, TaskProviderOverride] = {}

    def get_all(self) -> dict[str, TaskProviderOverride]:
        return dict(self._overrides)

    def set(self, task: str, provider: str, model: str) -> TaskProviderOverride:
        override = TaskProviderOverride(
            task=task, provider=provider, model=model, updated_at=datetime.now(UTC)
        )
        self._overrides[task] = override
        return override

    def clear(self, task: str) -> None:
        self._overrides.pop(task, None)


class _FakeSecretStore:
    def __init__(self) -> None:
        self._keys: dict[str, str] = {}

    def get(self, provider: str) -> str | None:
        return self._keys.get(provider)

    def has(self, provider: str) -> bool:
        return provider in self._keys

    def set(self, provider: str, api_key: str) -> None:
        self._keys[provider] = api_key

    def clear(self, provider: str) -> None:
        self._keys.pop(provider, None)


@pytest.fixture
def secret_store() -> _FakeSecretStore:
    return _FakeSecretStore()


@pytest.fixture
def service(secret_store: _FakeSecretStore) -> ProviderSettingsService:
    router = LLMRouter(dict(_DEFAULTS), _factories(secret_store))
    return ProviderSettingsService(
        repository=_FakeRepository(), llm_router=router, provider_secrets=secret_store
    )


def test_list_tasks_reports_yaml_defaults(service):
    statuses = {s.task: s for s in service.list_tasks()}
    assert set(statuses) == set(_DEFAULTS)
    assert statuses["pdf_extraction"].provider == "claude"
    assert statuses["pdf_extraction"].source == "default"
    assert statuses["pdf_extraction"].configured is True


def test_list_tasks_reports_unconfigured_provider(service):
    service.set_task_provider("code_generation", "claude_code", "sonnet")
    statuses = {s.task: s for s in service.list_tasks()}
    assert statuses["code_generation"].configured is False


def test_set_task_provider_persists_and_overrides_router(service):
    status = service.set_task_provider("pdf_extraction", "ollama", "hermes3:8b")
    assert status.task == "pdf_extraction"
    assert status.provider == "ollama"
    assert status.model == "hermes3:8b"
    assert status.source == "override"


def test_set_task_provider_unknown_task_raises(service):
    with pytest.raises(UnknownTaskError):
        service.set_task_provider("not_a_real_task", "claude", "claude-sonnet-5")


def test_set_task_provider_unknown_provider_raises(service):
    with pytest.raises(UnknownProviderError):
        service.set_task_provider("pdf_extraction", "not_a_provider", "x")


def test_clear_task_provider_reverts_to_default(service):
    service.set_task_provider("pdf_extraction", "ollama", "hermes3:8b")
    status = service.clear_task_provider("pdf_extraction")
    assert status.provider == "claude"
    assert status.source == "default"


def test_clear_task_provider_unknown_task_raises(service):
    with pytest.raises(UnknownTaskError):
        service.clear_task_provider("not_a_real_task")


async def test_test_provider_ok(service):
    result = await service.test_provider("claude")
    assert result.ok is True
    assert result.message is None
    assert result.reply is None


async def test_test_provider_with_message_returns_reply(service):
    result = await service.test_provider("claude", "hello")
    assert result.ok is True
    assert result.reply == "pong"


async def test_test_provider_reports_sdk_error(service):
    result = await service.test_provider("ollama")
    assert result.ok is False
    assert "connection refused" in result.message


async def test_test_provider_reports_not_configured(service):
    result = await service.test_provider("claude_code")
    assert result.ok is False
    assert "PATH" in result.message


async def test_test_provider_unknown_provider_raises(service):
    with pytest.raises(UnknownProviderError):
        await service.test_provider("not_a_provider")


async def test_test_provider_known_provider_without_factory_reports_failure(service):
    # "openclaw" is a KNOWN_PROVIDERS entry but this test's fake factories
    # dict doesn't wire one up — exercises the router's own "unknown
    # provider" ValueError being surfaced as a failed result, not a crash.
    result = await service.test_provider("openclaw")
    assert result.ok is False


def test_set_provider_key_makes_provider_configured(service):
    assert service.provider_configured_map()["openai"] is False
    service.set_provider_key("openai", "sk-test")
    assert service.provider_configured_map()["openai"] is True


def test_set_provider_key_takes_effect_without_restart(service, secret_store):
    # Mirrors set_task_provider's live-effect guarantee: a key saved via the
    # service is immediately visible to the next check, no caching lag.
    service.set_provider_key("openai", "sk-test")
    assert secret_store.get("openai") == "sk-test"


def test_clear_provider_key_reverts_to_not_configured(service):
    service.set_provider_key("openai", "sk-test")
    service.clear_provider_key("openai")
    assert service.provider_configured_map()["openai"] is False


def test_set_provider_key_unknown_provider_raises(service):
    with pytest.raises(UnknownProviderError):
        service.set_provider_key("not_a_provider", "x")


def test_clear_provider_key_unknown_provider_raises(service):
    with pytest.raises(UnknownProviderError):
        service.clear_provider_key("not_a_provider")


def test_set_provider_key_rejects_key_less_providers(service):
    with pytest.raises(UnknownProviderError):
        service.set_provider_key("ollama", "x")


def test_provider_configured_map_covers_every_known_provider(service):
    result = service.provider_configured_map()
    assert result["claude"] is True
    # check_configured only builds the adapter, never calls complete(), so
    # ollama's fake factory (which builds fine but errors on complete())
    # still reads as configured — that's test_provider's job to catch.
    assert result["ollama"] is True
    assert result["claude_code"] is False  # fake factory raises LLMProviderNotConfiguredError
    # Providers with no fake factory wired up at all still report False,
    # not a crash (LLMRouter.check_configured swallows the "unknown
    # provider" ValueError too).
    assert result["gemini"] is False
