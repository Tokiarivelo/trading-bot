"""Port: which strategy/skill applies to a symbol right now.

Owned by `skills` (the provider), mirroring `market_data.ports.MarketDataPort`
— consumers (the engine) import this directly rather than re-declaring it.
Implemented by `skills.application.skill_selector.SkillSelector`; news-window
overrides (Phase 8) plug in behind the same port.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, kw_only=True)
class SkillDecision:
    allowed: bool
    skill_name: str = ""
    strategy_name: str = ""
    risk_multiplier: float = 1.0
    reason: str = ""
    max_spread_points: int | None = None
    """News-skill spread cap override (§6.6 `post_event.max_spread_points`);
    `None` means use the symbol's configured `max_spread_points` unchanged."""


class SkillSelectorPort(Protocol):
    def select(self, symbol: str, now: datetime) -> SkillDecision: ...
