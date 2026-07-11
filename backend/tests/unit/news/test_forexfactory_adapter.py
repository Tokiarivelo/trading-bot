"""ForexFactoryCalendar against a mocked weekly-feed response."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from src.news.adapters.forexfactory import ForexFactoryCalendar
from src.news.domain.models import ImpactLevel, NewsCalendarUnavailable

NOW = datetime.now(UTC)


def _row(offset_days: float, impact: str = "High", title: str = "Non-Farm Payrolls") -> dict:
    return {
        "title": title,
        "country": "USD",
        "date": (NOW + timedelta(days=offset_days)).isoformat(),
        "impact": impact,
    }


def adapter_with(handler) -> ForexFactoryCalendar:
    transport = httpx.MockTransport(handler)
    return ForexFactoryCalendar(httpx.AsyncClient(transport=transport, base_url="http://ff"))


async def test_fetch_upcoming_parses_wire_format():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/ff_calendar_thisweek.json"
        return httpx.Response(200, json=[_row(1)])

    events = await adapter_with(handler).fetch_upcoming(7)
    (event,) = events
    assert event.name == "Non-Farm Payrolls"
    assert event.impact == ImpactLevel.HIGH
    assert event.currency == "USD"
    assert event.time.tzinfo is UTC


async def test_fetch_upcoming_filters_events_outside_days_ahead():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[_row(1), _row(30), _row(-1)])

    events = await adapter_with(handler).fetch_upcoming(7)
    assert len(events) == 1


async def test_fetch_upcoming_skips_rows_with_unknown_impact():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[_row(1, impact="Holiday")])

    events = await adapter_with(handler).fetch_upcoming(7)
    assert events == []


async def test_fetch_upcoming_skips_unparseable_rows():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"title": "broken"}])

    events = await adapter_with(handler).fetch_upcoming(7)
    assert events == []


async def test_gateway_error_becomes_calendar_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="bad gateway")

    with pytest.raises(NewsCalendarUnavailable, match="502"):
        await adapter_with(handler).fetch_upcoming(7)


async def test_connection_failure_becomes_calendar_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(NewsCalendarUnavailable, match="unreachable"):
        await adapter_with(handler).fetch_upcoming(7)


async def test_invalid_json_becomes_calendar_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    with pytest.raises(NewsCalendarUnavailable, match="invalid JSON"):
        await adapter_with(handler).fetch_upcoming(7)
