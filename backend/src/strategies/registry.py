"""Strategy registry (§6.5): name -> `Strategy` instance lookup.

Phase 4 registers the one hand-written baseline strategy directly; Phase 6
adds AI-generated files under `generated/` plus sandboxed dynamic loading and
versioning. Until then this is a plain in-memory map — no filesystem
discovery, no sandbox, because every registered strategy here is
human-written and trusted.
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
