"""Port: fetch upcoming economic calendar events (§6.7, §8, Phase 8).

Implemented by one adapter per `configs/news.yaml: calendar.source` (see
`news.adapters`); `news.application.news_window_service.NewsWindowService`
is the only consumer.
"""

from __future__ import annotations

from typing import Protocol

from src.news.domain.models import NewsEvent


class NewsCalendarPort(Protocol):
    async def fetch_upcoming(self, days_ahead: int) -> list[NewsEvent]: ...
