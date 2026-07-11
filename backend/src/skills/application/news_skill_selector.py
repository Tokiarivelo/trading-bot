"""News-aware skill selection (§6.6, §8): checks the active news window
before falling through to the symbol's `NormalSkill`, implementing the
plan's priority "news skill > symbol normal skill > global default".
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from src.news.domain.models import NewsWindow
from src.skills.domain.models import NewsSkill
from src.skills.ports.news_window_source import NewsWindowSourcePort
from src.skills.ports.skill_selector import SkillDecision, SkillSelectorPort

logger = logging.getLogger(__name__)

# The engine's only entry timeframe is M5 (configs/app.yaml: engine.entry_timeframe),
# so "wait N candles" translates directly to "wait N * 5 minutes" post-event.
_M5_MINUTES = 5


class NewsSkillSelector:
    def __init__(
        self,
        normal_selector: SkillSelectorPort,
        news_skills: dict[str, NewsSkill],
        window_source: NewsWindowSourcePort,
    ) -> None:
        self._normal = normal_selector
        self._news_skills = news_skills
        self._windows = window_source

    def select(self, symbol: str, now: datetime | None = None) -> SkillDecision:
        now = now or datetime.now(UTC)
        window = self._windows.active_window_for(symbol, now)
        if window is None:
            return self._normal.select(symbol, now)

        skill = self._news_skills.get(window.skill)
        if skill is None:
            logger.warning("news window active for unregistered skill: %s", window.skill)
            return self._normal.select(symbol, now)

        if window.is_pre(now):
            return self._pre_event_decision(skill, window, symbol, now)
        return self._post_event_decision(skill, window, symbol, now)

    def _pre_event_decision(
        self, skill: NewsSkill, window: NewsWindow, symbol: str, now: datetime
    ) -> SkillDecision:
        if skill.pre_event.block_new_entries:
            return SkillDecision(
                allowed=False,
                skill_name=skill.name,
                reason=f"news window pre-event block: {window.event.name}",
            )
        return self._normal.select(symbol, now)

    def _post_event_decision(
        self, skill: NewsSkill, window: NewsWindow, symbol: str, now: datetime
    ) -> SkillDecision:
        resume_at = window.event.time + timedelta(
            minutes=skill.post_event.wait_candles_m5 * _M5_MINUTES
        )
        if now < resume_at:
            return SkillDecision(
                allowed=False,
                skill_name=skill.name,
                reason=f"news window post-event cooldown until {resume_at.isoformat()}: "
                f"{window.event.name}",
            )

        max_spread_points = skill.post_event.max_spread_points or None
        if skill.post_event.strategy_override:
            return SkillDecision(
                allowed=True,
                skill_name=skill.name,
                strategy_name=skill.post_event.strategy_override,
                risk_multiplier=skill.post_event.risk_multiplier,
                max_spread_points=max_spread_points,
            )

        fallback = self._normal.select(symbol, now)
        if not fallback.allowed:
            return fallback
        return SkillDecision(
            allowed=True,
            skill_name=skill.name,
            strategy_name=fallback.strategy_name,
            risk_multiplier=skill.post_event.risk_multiplier,
            max_spread_points=max_spread_points,
        )
