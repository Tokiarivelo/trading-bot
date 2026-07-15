"""Wire models for symbol -> strategy routing (§6.6). Mirrors
`skills/domain/models.py`; the domain stays framework-free."""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.skills.domain.models import NormalSkill


class SessionWindowOut(BaseModel):
    start: str = Field(description="Session start, HH:MM, in the app's configured timezone.")
    end: str = Field(description="Session end, HH:MM, in the app's configured timezone.")


class NormalSkillOut(BaseModel):
    name: str = Field(description="Skill id, e.g. 'normal/xauusd'.")
    symbol: str = Field(description="Broker symbol this assignment routes.")
    strategy: str = Field(
        description="Strategy family currently trading this symbol — a name from "
        "GET /strategies/versions, not a version id."
    )
    risk_multiplier: float = Field(
        description="Position-size multiplier applied while this skill is active."
    )
    sessions: list[SessionWindowOut] = Field(
        description="Trading session windows in which this assignment is active; empty means "
        "always active."
    )
    newly_activated: bool = Field(
        default=False,
        description="True only on the PUT response when this call just activated a "
        "previously-inactive symbol for live automated trading (persisted to "
        "configs/app.yaml, hot-added to candle streaming and the spread gate). Always False "
        "on GET /skills/normal, since a listing isn't an action outcome.",
    )

    @staticmethod
    def from_domain(skill: NormalSkill, *, newly_activated: bool = False) -> NormalSkillOut:
        return NormalSkillOut(
            name=skill.name,
            symbol=skill.symbol,
            strategy=skill.strategy,
            risk_multiplier=skill.risk_multiplier,
            sessions=[
                SessionWindowOut(
                    start=window.start.strftime("%H:%M"), end=window.end.strftime("%H:%M")
                )
                for window in skill.sessions
            ],
            newly_activated=newly_activated,
        )


class AssignStrategyIn(BaseModel):
    strategy_name: str = Field(
        description="Strategy family to route this symbol's live trades to — must currently "
        "have an active, non-paused version (see GET /strategies/versions?status=active).",
        min_length=1,
    )
