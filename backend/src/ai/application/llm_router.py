"""Per-task LLM provider selection (§6.7, `configs/ai.yaml: provider_per_task`,
AI_PROVIDER_SETTINGS_PLAN.md §4.1/§6.4).

`ai/application/` services ask for an `LLMPort` by task name; this is the
only place that turns a `ProviderSpec` into a concrete adapter, so
re-pointing a task at a different provider is a config edit (or, once the
settings page lands, a runtime `set_override` call — no code change either
way).

`container.py` builds one `factories` dict — one closure per known provider,
each capturing only the one secret/setting it needs from `Settings` — so
`LLMRouter` itself never sees raw credentials. Adding a fifth provider later
is a new adapter class + one more factory entry; this class doesn't change.
"""

from __future__ import annotations

from collections.abc import Callable

from src.ai.ports.llm import LLMPort, ProviderSpec

ProviderFactory = Callable[[ProviderSpec], LLMPort]


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
        factories: dict[str, ProviderFactory],
        *,
        overrides: dict[str, ProviderSpec] | None = None,
    ) -> None:
        self._provider_per_task = provider_per_task
        self._factories = factories
        self._overrides: dict[str, ProviderSpec] = dict(overrides or {})
        # Keyed by (task, provider, model) rather than just `task`: setting
        # or clearing an override changes the key, so the next `for_task()`
        # call transparently builds (and caches) the new adapter — no
        # separate cache-invalidation step needed (plan §10).
        self._cache: dict[tuple[str, str, str], LLMPort] = {}

    def resolve(self, task: str) -> tuple[ProviderSpec, str] | None:
        """The spec `for_task(task)` would build right now, plus whether it
        came from a settings-page override or the `configs/ai.yaml` default —
        `None` if `task` has neither (settings-service list/status use, plan
        §6.5)."""
        if task in self._overrides:
            return self._overrides[task], "override"
        spec = self._provider_per_task.get(task)
        return (spec, "default") if spec is not None else None

    def for_task(self, task: str) -> LLMPort:
        resolved = self.resolve(task)
        if resolved is None:
            raise ValueError(f"no LLM provider configured for task {task!r} in ai.yaml")
        spec, _source = resolved
        cache_key = (task, spec.provider, spec.model)
        if cache_key not in self._cache:
            self._cache[cache_key] = self._build(spec)
        return self._cache[cache_key]

    def build_adapter(self, spec: ProviderSpec) -> LLMPort:
        """Build a fresh, uncached adapter for `spec` — used for one-off live
        probes (`ProviderSettingsService.test_provider()`) that shouldn't
        pollute the per-task cache `for_task()` relies on."""
        return self._build(spec)

    def check_configured(self, spec: ProviderSpec) -> tuple[bool, str | None]:
        """Whether `spec.provider` has its required secret/URL set, without
        making a network call or revealing the secret — builds (but never
        calls) an adapter and catches `LLMProviderNotConfiguredError`. Also
        catches the plain `ValueError` `_build` raises for a provider with no
        registered factory, so a catalog entry ahead of its factory wiring
        (or a test's deliberately partial factory dict) reads as merely
        "not configured" rather than raising through the settings page. Backs
        the settings page's per-task and per-provider status badges (plan
        §6.5); `test_provider` is the separate live-call probe."""
        try:
            self.build_adapter(spec)
        except (LLMProviderNotConfiguredError, ValueError) as exc:
            return False, str(exc)
        return True, None

    def set_override(self, task: str, spec: ProviderSpec) -> None:
        """Point `task` at `spec` for the life of this process (settings-page
        write path). Does not touch `configs/ai.yaml`; callers are
        responsible for persisting the override themselves (plan §6.5)."""
        self._overrides[task] = spec

    def clear_override(self, task: str) -> None:
        """Revert `task` to its `configs/ai.yaml` default."""
        self._overrides.pop(task, None)

    def clear_provider_cache(self, provider: str) -> None:
        """Drop every cached adapter built for `provider`, so the next
        `for_task()`/`build_adapter()` call rebuilds one with fresh
        credentials — needed after a settings-page API-key write, since a
        cached adapter closure would otherwise keep using the key it was
        built with until process restart (plan §6.5 key-management
        extension)."""
        self._cache = {k: v for k, v in self._cache.items() if k[1] != provider}

    def _build(self, spec: ProviderSpec) -> LLMPort:
        factory = self._factories.get(spec.provider)
        if factory is None:
            raise ValueError(f"unknown LLM provider: {spec.provider!r}")
        return factory(spec)
