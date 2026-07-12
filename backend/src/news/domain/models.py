"""News/economic-calendar domain (§6.7, §8, Phase 8) — pure values, no I/O.

Deciding *what to do* around a news window (flatten, block entries, override
strategy) is the news skill's job (`skills.domain.models.NewsSkill`); this
module only knows calendar facts and the window a skill's before/after
minutes carve out of them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ImpactLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, kw_only=True)
class NewsEvent:
    name: str
    time: datetime  # UTC, scheduled release time
    impact: ImpactLevel
    currency: str = ""
    forecast: str | None = None
    """Consensus estimate, as the source formats it (e.g. "8.5%", "1950B").
    `None` when the source doesn't publish one for this event."""
    previous: str | None = None
    """Prior period's reading, same formatting caveat as `forecast`."""
    actual: str | None = None
    """Released value, if the event has already happened and the source
    reports it — ForexFactory's weekly feed never populates this; Finnhub
    does once released."""


@dataclass(frozen=True, kw_only=True)
class TrackedEvent:
    """One `configs/news.yaml: tracked_events` entry. `name == "*"` is a
    wildcard matching any calendar event of `impact` not already claimed by
    an earlier, more specific entry."""

    name: str
    impact: ImpactLevel
    skill: str


@dataclass(frozen=True, kw_only=True)
class NewsConfig:
    """Mirrors `configs/news.yaml`. User-owned like `RiskCaps`: the news
    module reads it to know which calendar source to poll and how to map
    calendar events to news skills; nothing writes it back."""

    calendar_source: str
    refresh_minutes: int
    tracked_events: tuple[TrackedEvent, ...]
    default_before_min: int
    default_after_min: int


@dataclass(frozen=True, kw_only=True)
class WindowSpec:
    """Window sizing + affected symbols for one news skill, as seen by
    `NewsWindowService`. Assembled in `container.py` from the loaded
    `skills.domain.models.NewsSkill` so this module never needs to import
    `skills.domain` — the dependency only ever runs the other way
    (`skills.ports.news_window_source` imports `NewsWindow` from here)."""

    skill_name: str
    before_min: int
    after_min: int
    symbols: tuple[str, ...]
    close_all: bool = False
    """Pre-event flatten flag, mirrored from the skill's `pre_event.close_all`
    so `NewsWindowService` can populate `NewsWindowEntered.close_all` without
    importing `skills.domain`."""


@dataclass(frozen=True, kw_only=True)
class NewsWindow:
    """The resolved before/after window around one calendar event, sized by
    the matched news skill's `activation.window` (§6.6)."""

    event: NewsEvent
    skill: str
    window_start: datetime
    window_end: datetime

    def contains(self, now: datetime) -> bool:
        return self.window_start <= now <= self.window_end

    def is_pre(self, now: datetime) -> bool:
        return self.window_start <= now < self.event.time

    def is_post(self, now: datetime) -> bool:
        return self.event.time <= now <= self.window_end


class NewsCalendarUnavailable(Exception):
    """The calendar source is unreachable or returned an unparseable response."""
