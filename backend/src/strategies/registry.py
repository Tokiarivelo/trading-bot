"""Strategy registry (§6.5): name -> `Strategy` instance lookup.

Phase 4 registered the one hand-written baseline strategy directly. Phase 6
adds AI-generated files under `generated/`, loaded through
`strategies/sandbox.py` and tracked by `strategies/application/versioning.py`
(`StrategyVersionService.activate_version`/`load_active_into_registry` call
`register()` here) — this class itself stays a plain in-memory map either way.
"""

from __future__ import annotations

from src.strategies.domain.models import Strategy


class StrategyRegistry:
    def __init__(self) -> None:
        self._strategies: dict[str, Strategy] = {}

    def register(self, strategy: Strategy) -> None:
        self._strategies[strategy.spec.name] = strategy

    def get(self, name: str) -> Strategy | None:
        return self._strategies.get(name)
