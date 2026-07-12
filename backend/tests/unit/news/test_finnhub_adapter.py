"""FinnhubCalendar against a mocked `/calendar/economic` response."""

from datetime import UTC

import httpx
import pytest

from src.news.adapters.finnhub import FinnhubCalendar
from src.news.domain.models import ImpactLevel, NewsCalendarUnavailable

PAYLOAD = {
    "economicCalendar": [
        {
            "event": "CPI",
            "impact": "high",
            "time": "2026-07-14 12:30:00",
            "country": "US",
            "estimate": 3.2,
            "prev": 3.1,
            "actual": 3.4,
        },
    ]
}


def adapter_with(handler, api_key="secret") -> FinnhubCalendar:
    transport = httpx.MockTransport(handler)
    return FinnhubCalendar(
        httpx.AsyncClient(transport=transport, base_url="http://finnhub"), api_key
    )


async def test_fetch_upcoming_parses_wire_format_and_forwards_token():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/calendar/economic"
        assert request.url.params["token"] == "secret"
        return httpx.Response(200, json=PAYLOAD)

    events = await adapter_with(handler).fetch_upcoming(7)
    (event,) = events
    assert event.name == "CPI"
    assert event.impact == ImpactLevel.HIGH
    assert event.currency == "US"
    assert event.time.tzinfo is UTC
    assert event.forecast == "3.2"
    assert event.previous == "3.1"
    assert event.actual == "3.4"


async def test_fetch_upcoming_skips_rows_with_unknown_impact():
    def handler(request: httpx.Request) -> httpx.Response:
        row = {"event": "x", "impact": "none", "time": "2026-07-14 00:00:00"}
        return httpx.Response(200, json={"economicCalendar": [row]})

    events = await adapter_with(handler).fetch_upcoming(7)
    assert events == []


async def test_fetch_upcoming_leaves_unreleased_fields_null():
    def handler(request: httpx.Request) -> httpx.Response:
        row = {"event": "NFP", "impact": "high", "time": "2026-07-14 12:30:00"}
        return httpx.Response(200, json={"economicCalendar": [row]})

    (event,) = await adapter_with(handler).fetch_upcoming(7)
    assert event.forecast is None
    assert event.previous is None
    assert event.actual is None


async def test_gateway_error_becomes_calendar_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    with pytest.raises(NewsCalendarUnavailable, match="401"):
        await adapter_with(handler).fetch_upcoming(7)


async def test_connection_failure_becomes_calendar_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(NewsCalendarUnavailable, match="unreachable"):
        await adapter_with(handler).fetch_upcoming(7)
