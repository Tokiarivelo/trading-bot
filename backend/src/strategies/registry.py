"""Strategy registry (§6.5): name -> `Strategy` instance lookup.

Phase 4 registered the one hand-written baseline strategy directly. Phase 6
adds AI-generated files under `generated/`, loaded through
`strategies/sandbox.py` and tracked by `strategies/application/versioning.py`
(`StrategyVersionService.activate_version`/`load_active_into_registry` call
`register()` here) — this class itself stays a plain in-memory map either way.

`pause`/`resume` back the per-bot pause action (distinct from the engine-wide
kill switch): a paused name is kept registered but `get()` hides it, so the
trade loop's existing "no strategy registered" skip path takes over with no
changes needed in `engine/`.
"""

from __future__ import annotations

from src.strategies.domain.models import Strategy


class StrategyRegistry:
    def __init__(self) -> None:
        self._strategies: dict[str, Strategy] = {}
        self._paused: set[str] = set()

    def register(self, strategy: Strategy) -> None:
        self._strategies[strategy.spec.name] = strategy

    def unregister(self, name: str) -> None:
        self._strategies.pop(name, None)
        self._paused.discard(name)

    def get(self, name: str) -> Strategy | None:
        if name in self._paused:
            return None
        return self._strategies.get(name)

    def pause(self, name: str) -> None:
        self._paused.add(name)

    def resume(self, name: str) -> None:
        self._paused.discard(name)
