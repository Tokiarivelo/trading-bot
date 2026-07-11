"""Bot trading skills domain (§6.6) — not Claude Code skills.

`NormalSkill` is the default per-symbol behavior: which strategy to run and
during which sessions. News skills (Phase 8) add activation-window overrides
on top via the same `SkillSelectorPort`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time


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
