from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
from fastapi import FastAPI

from src.news.api.routes import router
from src.news.application.news_window_service import NewsWindowService
from src.news.domain.models import ImpactLevel, NewsConfig, NewsEvent, TrackedEvent, WindowSpec
from src.shared.events.bus import EventBus

NOW = datetime.now(UTC)  # the route always resolves "now" live, so tests must match


class FakeCalendar:
    def __init__(self, events: list[NewsEvent]) -> None:
        self.events = events

    async def fetch_upcoming(self, days_ahead: int) -> list[NewsEvent]:
        return self.events


def _api(events: list[NewsEvent], tracked, specs) -> httpx.AsyncClient:
    service = NewsWindowService(
        calendar=FakeCalendar(events),
        config=NewsConfig(
            calendar_source="forexfactory",
            refresh_minutes=60,
            tracked_events=tracked,
            default_before_min=30,
            default_after_min=60,
        ),
        window_specs=specs,
        event_bus=EventBus(),
    )
    service._events = events  # populate cache without hitting the refresh loop
    app = FastAPI()
    app.include_router(router)
    app.state.container = SimpleNamespace(news_window_service=service)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://backend")


async def test_upcoming_lists_events_with_resolved_skill():
    event = NewsEvent(
        name="Non-Farm Payrolls", time=NOW + timedelta(hours=1), impact=ImpactLevel.HIGH
    )
    tracked = (TrackedEvent(name="Non-Farm Payrolls", impact=ImpactLevel.HIGH, skill="nfp"),)
    specs = {"nfp": WindowSpec(skill_name="nfp", before_min=30, after_min=60, symbols=("XAUUSD",))}

    async with _api([event], tracked, specs) as client:
        response = await client.get("/news/upcoming", params={"days_ahead": 7})

    assert response.status_code == 200
    (body,) = response.json()
    assert body["name"] == "Non-Farm Payrolls"
    assert body["skill"] == "nfp"


async def test_upcoming_skill_is_null_when_unmatched():
    event = NewsEvent(name="Retail Sales", time=NOW + timedelta(hours=1), impact=ImpactLevel.LOW)

    async with _api([event], (), {}) as client:
        response = await client.get("/news/upcoming")

    (body,) = response.json()
    assert body["skill"] is None


async def test_active_windows_empty_when_nothing_active():
    async with _api([], (), {}) as client:
        response = await client.get("/news/active-windows")

    assert response.status_code == 200
    assert response.json() == []
