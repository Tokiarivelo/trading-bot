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
