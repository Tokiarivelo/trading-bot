"""Registry-based provider selection (AI_PROVIDER_SETTINGS_PLAN.md §4.1/§6.4):
`LLMRouter` dispatches to whichever factory matches `ProviderSpec.provider`,
resolves settings-page overrides before `configs/ai.yaml` defaults, and
rebuilds (rather than serves a stale cached adapter) the moment an override
changes a task's provider or model."""

from __future__ import annotations

import pytest

from src.ai.application.llm_router import LLMProviderNotConfiguredError, LLMRouter
from src.ai.ports.llm import LLMMessage, ProviderSpec


class _FakeAdapter:
    def __init__(self, tag: str) -> None:
        self.tag = tag

    async def complete(self, message: LLMMessage, *, max_tokens: int = 4096) -> str:
        return self.tag


def _factories(build_log: list[ProviderSpec]) -> dict:
    def _make(provider: str):
        def _factory(spec: ProviderSpec):
            build_log.append(spec)
            return _FakeAdapter(f"{provider}:{spec.model}")

        return _factory

    def _unconfigured(spec: ProviderSpec):
        raise LLMProviderNotConfiguredError("provider 'unconfigured' needs a secret")

    return {"claude": _make("claude"), "ollama": _make("ollama"), "unconfigured": _unconfigured}


def test_for_task_uses_configured_provider():
    router = LLMRouter(
        {"pdf_extraction": ProviderSpec(provider="claude", model="claude-sonnet-5")},
        _factories([]),
    )
    llm = router.for_task("pdf_extraction")
    assert llm.tag == "claude:claude-sonnet-5"


def test_for_task_unknown_task_raises():
    router = LLMRouter({}, _factories([]))
    with pytest.raises(ValueError, match="pdf_extraction"):
        router.for_task("pdf_extraction")


def test_for_task_unknown_provider_raises():
    router = LLMRouter(
        {"pdf_extraction": ProviderSpec(provider="not_a_provider", model="x")},
        _factories([]),
    )
    with pytest.raises(ValueError, match="not_a_provider"):
        router.for_task("pdf_extraction")


def test_adapter_is_cached_per_task_provider_model():
    build_log: list[ProviderSpec] = []
    router = LLMRouter(
        {"pdf_extraction": ProviderSpec(provider="claude", model="claude-sonnet-5")},
        _factories(build_log),
    )
    first = router.for_task("pdf_extraction")
    second = router.for_task("pdf_extraction")
    assert first is second
    assert len(build_log) == 1


def test_set_override_takes_effect_on_next_call_without_restart():
    router = LLMRouter(
        {"pdf_extraction": ProviderSpec(provider="claude", model="claude-sonnet-5")},
        _factories([]),
    )
    assert router.for_task("pdf_extraction").tag == "claude:claude-sonnet-5"

    router.set_override("pdf_extraction", ProviderSpec(provider="ollama", model="hermes3:8b"))

    assert router.for_task("pdf_extraction").tag == "ollama:hermes3:8b"


def test_clear_override_reverts_to_yaml_default():
    router = LLMRouter(
        {"pdf_extraction": ProviderSpec(provider="claude", model="claude-sonnet-5")},
        _factories([]),
    )
    router.set_override("pdf_extraction", ProviderSpec(provider="ollama", model="hermes3:8b"))
    router.clear_override("pdf_extraction")

    assert router.for_task("pdf_extraction").tag == "claude:claude-sonnet-5"


def test_override_reuses_cached_adapter_if_same_spec_seen_before():
    build_log: list[ProviderSpec] = []
    router = LLMRouter(
        {"pdf_extraction": ProviderSpec(provider="claude", model="claude-sonnet-5")},
        _factories(build_log),
    )
    router.for_task("pdf_extraction")  # builds claude:claude-sonnet-5
    router.set_override("pdf_extraction", ProviderSpec(provider="ollama", model="hermes3:8b"))
    router.for_task("pdf_extraction")  # builds ollama:hermes3:8b
    router.clear_override("pdf_extraction")
    router.for_task("pdf_extraction")  # reuses the still-cached claude:claude-sonnet-5

    assert len(build_log) == 2


def test_resolve_reports_default_source():
    router = LLMRouter(
        {"pdf_extraction": ProviderSpec(provider="claude", model="claude-sonnet-5")},
        _factories([]),
    )
    spec, source = router.resolve("pdf_extraction")
    assert spec == ProviderSpec(provider="claude", model="claude-sonnet-5")
    assert source == "default"


def test_resolve_reports_override_source():
    router = LLMRouter(
        {"pdf_extraction": ProviderSpec(provider="claude", model="claude-sonnet-5")},
        _factories([]),
    )
    router.set_override("pdf_extraction", ProviderSpec(provider="ollama", model="hermes3:8b"))
    spec, source = router.resolve("pdf_extraction")
    assert spec == ProviderSpec(provider="ollama", model="hermes3:8b")
    assert source == "override"


def test_resolve_unknown_task_returns_none():
    router = LLMRouter({}, _factories([]))
    assert router.resolve("pdf_extraction") is None


def test_check_configured_true_when_factory_succeeds():
    router = LLMRouter({}, _factories([]))
    ok, reason = router.check_configured(ProviderSpec(provider="claude", model="claude-sonnet-5"))
    assert ok is True
    assert reason is None


def test_check_configured_false_when_factory_raises_not_configured():
    router = LLMRouter({}, _factories([]))
    ok, reason = router.check_configured(ProviderSpec(provider="unconfigured", model="x"))
    assert ok is False
    assert "secret" in reason


def test_check_configured_false_when_provider_has_no_registered_factory():
    router = LLMRouter({}, _factories([]))
    ok, reason = router.check_configured(ProviderSpec(provider="no_such_provider", model="x"))
    assert ok is False
    assert "no_such_provider" in reason


def test_clear_provider_cache_forces_rebuild_for_that_provider_only():
    build_log: list[ProviderSpec] = []
    router = LLMRouter(
        {
            "pdf_extraction": ProviderSpec(provider="claude", model="claude-sonnet-5"),
            "code_generation": ProviderSpec(provider="ollama", model="hermes3:8b"),
        },
        _factories(build_log),
    )
    router.for_task("pdf_extraction")
    router.for_task("code_generation")
    assert len(build_log) == 2

    router.clear_provider_cache("claude")

    router.for_task("code_generation")  # still cached, ollama untouched
    assert len(build_log) == 2

    router.for_task("pdf_extraction")  # claude cache was dropped, rebuilds
    assert len(build_log) == 3


def test_build_adapter_does_not_use_or_populate_task_cache():
    build_log: list[ProviderSpec] = []
    router = LLMRouter(
        {"pdf_extraction": ProviderSpec(provider="claude", model="claude-sonnet-5")},
        _factories(build_log),
    )
    router.build_adapter(ProviderSpec(provider="claude", model="claude-sonnet-5"))
    assert len(build_log) == 1
    # for_task still builds its own instance rather than reusing the probe's
    router.for_task("pdf_extraction")
    assert len(build_log) == 2
