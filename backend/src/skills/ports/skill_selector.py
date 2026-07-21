"""Port: which strategy/skill applies to a symbol right now.

Owned by `skills` (the provider), mirroring `market_data.ports.MarketDataPort`
— consumers (the engine) import this directly rather than re-declaring it.
Implemented by `skills.application.skill_selector.SkillSelector`; news-window
overrides (Phase 8) plug in behind the same port.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
    magic: int = 0
    """MT5 magic number identifying which bot placed an order from this
    decision — 0 (no attribution) for blocked/disallowed decisions."""
    param_overrides: dict[str, float | int | str | bool] = field(default_factory=dict)
    """This bot's per-bot overrides of its strategy's `StrategySpec.params`
    (see `skills.domain.models.NormalSkill.param_overrides`) — merged onto a
    fresh copy of the strategy's spec by
    `engine.application.trade_loop._effective_strategy`, never mutating the
    shared `StrategyRegistry` instance."""
    htf_veto_override: bool | None = None
    """This bot's per-bot override of `StrategySpec.htf_veto`; `None` means
    inherit the strategy's own default."""


class SkillSelectorPort(Protocol):
    def select_all(self, symbol: str, now: datetime) -> list[SkillDecision]:
        """One decision per bot currently active on `symbol` — empty if
        none are. A blocked bot still contributes its own `allowed=False`
        decision so callers can log why, distinct from "no bots configured
        at all"."""
        ...
