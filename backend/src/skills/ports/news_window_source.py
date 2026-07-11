"""Port: which news window (if any) is active for a symbol right now.

Implemented by `news.application.news_window_service.NewsWindowService`.
Kept synchronous and side-effect-free — `NewsSkillSelector.select()` is
called from the engine's hot path on every M5 close and must never block on
calendar-fetch I/O to answer, so the news module does all fetching in a
background refresh loop and this only ever reads its last-fetched cache.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from src.news.domain.models import NewsWindow


class NewsWindowSourcePort(Protocol):
    def active_window_for(self, symbol: str, now: datetime) -> NewsWindow | None: ...
