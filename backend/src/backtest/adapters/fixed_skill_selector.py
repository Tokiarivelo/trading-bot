"""SkillSelectorPort for backtests: always route to the strategy under test.

A strategy backtest (`<strategy> <symbol> <period>`) has no news/session
skill logic in scope — it exists to answer "how would this one strategy have
performed," not "how would the live skill-selection pipeline have performed."
"""

from __future__ import annotations

from datetime import datetime

from src.skills.ports.skill_selector import SkillDecision


class FixedSkillSelector:
    def __init__(self, strategy_name: str) -> None:
        self._strategy_name = strategy_name

    def select(self, symbol: str, now: datetime) -> SkillDecision:
        return SkillDecision(
            allowed=True,
            skill_name="backtest",
            strategy_name=self._strategy_name,
            risk_multiplier=1.0,
        )
