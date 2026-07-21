"""Bot trading skills domain (§6.6) — not Claude Code skills.

`NormalSkill` is one bot's default behavior on a symbol: which strategy to
run and during which sessions. A symbol may route to several `NormalSkill`s
at once (several bots trading it concurrently, each independently) —
`name` (`normal/<symbol>/<bot_slug>`) is what tells them apart. News skills
(Phase 8) add activation-window overrides on top via the same
`SkillSelectorPort`.
"""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass, field
from datetime import time

_SLUG_INVALID = re.compile(r"[^a-z0-9_-]+")


def slugify(value: str) -> str:
    """Normalizes a bot/strategy name into the `[a-z0-9_-]+` form used as a
    `NormalSkill.name` path segment and YAML filename — e.g. a strategy
    name doubling as the default bot name when none is given explicitly."""
    return _SLUG_INVALID.sub("_", value.strip().lower()).strip("_")


def magic_number(symbol: str, skill_name: str) -> int:
    """Stable positive int derived from (symbol, skill_name) — sent to the
    broker as the MT5 "magic number" so multiple bots trading the same
    symbol can be told apart on open positions. Recomputed on demand rather
    than persisted, since it's a pure function of identity that already
    must be unique (two bots on one symbol can never share a `skill_name`)."""
    return zlib.crc32(f"{symbol}:{skill_name}".encode()) & 0x7FFFFFFF


def parse_time(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


@dataclass(frozen=True, kw_only=True)
class SessionWindow:
    start: time
    end: time

    def contains(self, moment: time) -> bool:
        return self.start <= moment <= self.end

    @classmethod
    def parse(cls, start: str, end: str) -> SessionWindow:
        return cls(start=parse_time(start), end=parse_time(end))


@dataclass(frozen=True, kw_only=True)
class NormalSkill:
    name: str
    symbol: str
    strategy: str
    risk_multiplier: float = 1.0
    sessions: tuple[SessionWindow, ...] = ()
    # Per-bot overrides layered onto this bot's strategy at evaluation time
    # (see engine.application.trade_loop._effective_strategy) — never mutate
    # the shared StrategyRegistry instance other bots on the same strategy
    # also use. Keys must already exist in the strategy's own
    # StrategySpec.params; unknown/mistyped keys are rejected at the
    # application layer (SkillAssignmentService.update_config), not here.
    param_overrides: dict[str, float | int | str | bool] = field(default_factory=dict)
    # None = inherit the strategy's own StrategySpec.htf_veto.
    htf_veto_override: bool | None = None

    def is_active(self, moment: time) -> bool:
        if not self.sessions:
            return True
        return any(window.contains(moment) for window in self.sessions)


@dataclass(frozen=True, kw_only=True)
class NewsActivationWindow:
    before_min: int
    after_min: int


@dataclass(frozen=True, kw_only=True)
class NewsActivation:
    calendar_events: tuple[str, ...]
    window: NewsActivationWindow
    symbols: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class PreEventRules:
    close_all: bool = False
    block_new_entries: bool = True


@dataclass(frozen=True, kw_only=True)
class PostEventRules:
    wait_candles_m5: int = 0
    strategy_override: str = ""
    max_spread_points: int = 0  # 0 = no override, use the symbol's configured cap
    risk_multiplier: float = 1.0


@dataclass(frozen=True, kw_only=True)
class NewsSkill:
    """A high-volatility playbook (§6.6, §8): activates within a window
    around specific calendar events, taking priority over the symbol's
    `NormalSkill`. `activation.calendar_events` and `window` are informational
    for this skill's own docs — the actual event -> skill match happens via
    `configs/news.yaml: tracked_events`, resolved by `NewsWindowService`."""

    name: str
    activation: NewsActivation
    pre_event: PreEventRules
    post_event: PostEventRules
