"""Port: where the engine gets a strategy instance by name.

Implemented by `strategies.registry.StrategyRegistry` — the engine depends
only on this Protocol, never on the strategies module's internals.
"""

from __future__ import annotations

from typing import Protocol

from src.strategies.domain.models import Strategy


class StrategySourcePort(Protocol):
    def get(self, name: str) -> Strategy | None: ...
