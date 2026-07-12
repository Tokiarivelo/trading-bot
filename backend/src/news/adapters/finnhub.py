"""Finnhub economic calendar adapter (https://finnhub.io/docs/api/economic-calendar),
selected via `configs/news.yaml: calendar.source: finnhub`. Requires an API
key (`TB_FINNHUB_API_KEY`); same error-translation contract as
`ForexFactoryCalendar` — transport/parse failures become
`NewsCalendarUnavailable`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from src.news.domain.models import ImpactLevel, NewsCalendarUnavailable, NewsEvent

_IMPACT_MAP = {"high": ImpactLevel.HIGH, "medium": ImpactLevel.MEDIUM, "low": ImpactLevel.LOW}


class FinnhubCalendar:
    def __init__(self, client: httpx.AsyncClient, api_key: str) -> None:
        self._client = client
        self._api_key = api_key

    async def fetch_upcoming(self, days_ahead: int) -> list[NewsEvent]:
        now = datetime.now(UTC)
        params = {
            "from": now.date().isoformat(),
            "to": (now + timedelta(days=days_ahead)).date().isoformat(),
            "token": self._api_key,
        }
        try:
            response = await self._client.get("/calendar/economic", params=params)
        except httpx.HTTPError as exc:
            raise NewsCalendarUnavailable(f"finnhub unreachable: {exc}") from exc
        if response.status_code != 200:
            raise NewsCalendarUnavailable(f"finnhub -> {response.status_code}: {response.text}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise NewsCalendarUnavailable(f"finnhub returned invalid JSON: {exc}") from exc

        return [
            event
            for row in payload.get("economicCalendar", [])
            if (event := _parse_row(row)) is not None
        ]


def _parse_row(row: dict) -> NewsEvent | None:
    try:
        impact = _IMPACT_MAP.get(str(row["impact"]).lower())
        if impact is None:
            return None
        return NewsEvent(
            name=row["event"],
            time=datetime.fromisoformat(row["time"].replace(" ", "T")).replace(tzinfo=UTC),
            impact=impact,
            currency=row.get("country", ""),
            forecast=_stringify(row.get("estimate")),
            previous=_stringify(row.get("prev")),
            actual=_stringify(row.get("actual")),
        )
    except (KeyError, ValueError):
        return None


def _stringify(value: object) -> str | None:
    """Finnhub reports `estimate`/`prev`/`actual` as bare numbers (or
    omits/nulls them pre-release) — normalize to the same string-or-None
    shape `NewsEvent` uses for ForexFactory's pre-formatted strings."""
    return None if value is None else str(value)
