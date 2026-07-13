"""Skill selection (§6.6): resolves the active skill for a symbol.

Priority is "news skill > symbol normal skill > global default" per the plan;
Phase 4 only wires the normal skills, so this always falls through to them.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from src.skills.domain.models import NormalSkill
from src.skills.ports.skill_selector import SkillDecision

logger = logging.getLogger(__name__)


class SkillSelector:
    def __init__(self, skills: dict[str, NormalSkill], timezone: str = "UTC") -> None:
        self._skills = skills
        self._tz = ZoneInfo(timezone)

    def update(self, symbol: str, skill: NormalSkill) -> None:
        """Hot-swaps the in-memory skill for `symbol` — used by
        `SkillAssignmentService` so a reassigned strategy routes live trades
        immediately, without an app restart."""
        self._skills[symbol] = skill

    def select(self, symbol: str, now: datetime | None = None) -> SkillDecision:
        skill = self._skills.get(symbol)
        if skill is None:
            return SkillDecision(allowed=False, reason=f"no skill configured for {symbol}")
        now = now or datetime.now(UTC)
        local_time = now.astimezone(self._tz).time()
        if not skill.is_active(local_time):
            return SkillDecision(
                allowed=False,
                skill_name=skill.name,
                strategy_name=skill.strategy,
                reason="outside trading session",
            )
        return SkillDecision(
            allowed=True,
            skill_name=skill.name,
            strategy_name=skill.strategy,
            risk_multiplier=skill.risk_multiplier,
        )
