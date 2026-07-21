"""Skill selection (§6.6): resolves the active bots for a symbol.

Priority is "news skill > symbol normal skills > global default" per the
plan; Phase 4 only wires the normal skills, so this always falls through to
them. A symbol may have several `NormalSkill`s active at once (several bots
trading it concurrently) — `select_all` returns one decision per bot.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from src.skills.domain.models import NormalSkill, magic_number
from src.skills.ports.skill_selector import SkillDecision

logger = logging.getLogger(__name__)


class SkillSelector:
    def __init__(self, skills: dict[str, list[NormalSkill]], timezone: str = "UTC") -> None:
        """`skills` is `NormalSkillRepository.load_all()`'s shape (symbol ->
        its active bots); stored internally keyed by bot slug too, for O(1)
        `set`/`remove` from `SkillAssignmentService`."""
        self._skills: dict[str, dict[str, NormalSkill]] = {
            symbol: {skill.name.rsplit("/", 1)[-1]: skill for skill in bots}
            for symbol, bots in skills.items()
        }
        self._tz = ZoneInfo(timezone)

    def set(self, skill: NormalSkill) -> None:
        """Hot-adds or replaces (by `skill.name`'s bot slug) a bot's skill on
        its symbol — used by `SkillAssignmentService` so activating or
        reassigning a bot routes live trades immediately, no app restart."""
        bot_slug = skill.name.rsplit("/", 1)[-1]
        self._skills.setdefault(skill.symbol, {})[bot_slug] = skill

    def remove(self, symbol: str, bot_slug: str) -> None:
        bots = self._skills.get(symbol)
        if bots is not None:
            bots.pop(bot_slug, None)

    def select_all(self, symbol: str, now: datetime | None = None) -> list[SkillDecision]:
        bots = self._skills.get(symbol)
        if not bots:
            return []
        now = now or datetime.now(UTC)
        local_time = now.astimezone(self._tz).time()
        return [self._decide(skill, local_time) for skill in bots.values()]

    def _decide(self, skill: NormalSkill, local_time: time) -> SkillDecision:
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
            magic=magic_number(skill.symbol, skill.name),
            param_overrides=skill.param_overrides,
            htf_veto_override=skill.htf_veto_override,
        )
