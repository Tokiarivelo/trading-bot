"""Wire models for symbol -> bots routing (§6.6). Mirrors
`skills/domain/models.py`; the domain stays framework-free."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from src.skills.domain.models import NormalSkill
from src.strategies.domain.models import Strategy


def _scalar_params(params: dict[str, Any]) -> dict[str, float | int | str | bool]:
    """Strategy params that are safe to show/override through a generic
    per-bot form — some strategies (e.g. pob_snd_zones_xauusd) carry
    structured params like `session_windows: tuple[tuple[int, int], ...]`
    that aren't a single scalar value; those stay off `strategy_default_params`
    (and therefore can't be targeted by `param_overrides` either — see
    `SkillAssignmentService._validate_overrides`, which still rejects them by
    type even if a caller tries)."""
    return {k: v for k, v in params.items() if isinstance(v, (bool, int, float, str))}


class SessionWindowOut(BaseModel):
    start: str = Field(description="Session start, HH:MM, in the app's configured timezone.")
    end: str = Field(description="Session end, HH:MM, in the app's configured timezone.")


class SessionWindowIn(BaseModel):
    start: str = Field(description="Session start, HH:MM, in the app's configured timezone.")
    end: str = Field(description="Session end, HH:MM, in the app's configured timezone.")


class NormalSkillOut(BaseModel):
    name: str = Field(description="Skill id, e.g. 'normal/xauusd/breakout_v1'.")
    bot_name: str = Field(
        description="This bot's short id on its symbol (the last segment of `name`) — the "
        "path segment used by PUT/DELETE .../bots/{bot_name}."
    )
    symbol: str = Field(description="Broker symbol this bot trades.")
    strategy: str = Field(
        description="Strategy family this bot currently trades — a name from "
        "GET /strategies/versions, not a version id."
    )
    risk_multiplier: float = Field(
        description="Position-size multiplier applied while this bot is active."
    )
    sessions: list[SessionWindowOut] = Field(
        description="Trading session windows in which this bot is active; empty means "
        "always active."
    )
    param_overrides: dict[str, float | int | str | bool] = Field(
        description="Per-bot overrides of this strategy's tunable params, keyed by param "
        "name — only explicitly overridden keys appear here; every other param runs at its "
        "`strategy_default_params` value. Set via PUT .../bots/{bot_name}/config."
    )
    htf_veto_override: bool | None = Field(
        description="Per-bot override of the engine's HTF veto (see StrategySpec.htf_veto). "
        "`null` means this bot inherits the strategy's own `strategy_default_htf_veto`."
    )
    strategy_default_params: dict[str, float | int | str | bool] = Field(
        description="This bot's strategy's own declared param defaults, straight from its "
        "currently registered StrategySpec.params — the base every key in `param_overrides` "
        "layers on top of. Empty if the strategy isn't currently registered (e.g. paused)."
    )
    strategy_default_htf_veto: bool = Field(
        description="This bot's strategy's own declared StrategySpec.htf_veto — the base "
        "`htf_veto_override` layers on top of. True if the strategy isn't currently "
        "registered (matches StrategySpec.htf_veto's own default)."
    )
    newly_activated: bool = Field(
        default=False,
        description="True only on the POST .../bots response when this call just activated a "
        "previously-inactive symbol for live automated trading (persisted to "
        "configs/app.yaml, hot-added to candle streaming and the spread gate). Always False "
        "on GET /skills/normal, since a listing isn't an action outcome.",
    )

    @staticmethod
    def from_domain(
        skill: NormalSkill, *, newly_activated: bool = False, strategy: Strategy | None = None
    ) -> NormalSkillOut:
        return NormalSkillOut(
            name=skill.name,
            bot_name=skill.name.rsplit("/", 1)[-1],
            symbol=skill.symbol,
            strategy=skill.strategy,
            risk_multiplier=skill.risk_multiplier,
            sessions=[
                SessionWindowOut(
                    start=window.start.strftime("%H:%M"), end=window.end.strftime("%H:%M")
                )
                for window in skill.sessions
            ],
            param_overrides=dict(skill.param_overrides),
            htf_veto_override=skill.htf_veto_override,
            strategy_default_params=_scalar_params(strategy.spec.params) if strategy else {},
            strategy_default_htf_veto=strategy.spec.htf_veto if strategy else True,
            newly_activated=newly_activated,
        )


class AddBotIn(BaseModel):
    strategy_name: str = Field(
        description="Strategy family this bot trades — must currently have an active, "
        "non-paused version (see GET /strategies/versions?status=active).",
        min_length=1,
    )
    bot_name: str | None = Field(
        default=None,
        description="Short id for this bot on the symbol, e.g. 'breakout'. Defaults to "
        "`strategy_name`, slugified. Must be unique among the symbol's currently active bots.",
    )
    risk_multiplier: float = Field(
        default=1.0,
        description="Position-size multiplier applied while this bot is active.",
        gt=0,
    )


class UpdateBotIn(BaseModel):
    strategy_name: str = Field(
        description="Strategy family to reassign this bot to — must currently have an active, "
        "non-paused version (see GET /strategies/versions?status=active).",
        min_length=1,
    )


class UpdateBotConfigIn(BaseModel):
    risk_multiplier: float = Field(
        description="Position-size multiplier applied while this bot is active.", gt=0
    )
    sessions: list[SessionWindowIn] = Field(
        description="Full replacement set of trading session windows in which this bot is "
        "active; empty means always active."
    )
    param_overrides: dict[str, float | int | str | bool] = Field(
        default_factory=dict,
        description="Full replacement set of per-bot param overrides — keys not present here "
        "revert to the strategy's own default; send {} to clear all overrides. Every key must "
        "already exist in this bot's strategy's own StrategySpec.params (see "
        "strategy_default_params on GET /skills/normal), and its value's type (bool, "
        "int/float, or str) must match that default's type.",
    )
    htf_veto_override: bool | None = Field(
        default=None,
        description="Per-bot override of the engine's HTF veto. true/false forces it on or "
        "off for this bot regardless of the strategy's own default; null inherits the "
        "strategy's own StrategySpec.htf_veto.",
    )
