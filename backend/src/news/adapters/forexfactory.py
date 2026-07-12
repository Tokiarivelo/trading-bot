"""ForexFactory calendar adapter — the free weekly JSON feed that mirrors the
forexfactory.com calendar widget (no official ForexFactory API exists; this
is the same feed several open-source trading tools consume). Only ever
called through `NewsCalendarPort`; transport and parse failures both become
`NewsCalendarUnavailable` so the refresh loop can log and retry next cycle
instead of crashing.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from src.news.domain.models import ImpactLevel, NewsCalendarUnavailable, NewsEvent

_IMPACT_MAP = {"high": ImpactLevel.HIGH, "medium": ImpactLevel.MEDIUM, "low": ImpactLevel.LOW}


class ForexFactoryCalendar:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def fetch_upcoming(self, days_ahead: int) -> list[NewsEvent]:
        payload = await self._get("/ff_calendar_thisweek.json")
        now = datetime.now(UTC)
        cutoff = now.timestamp() + days_ahead * 86400
        events: list[NewsEvent] = []
        for row in payload:
            event = _parse_row(row)
            if event is not None and now.timestamp() <= event.time.timestamp() <= cutoff:
                events.append(event)
        return events

    async def _get(self, path: str) -> list[dict]:
        try:
            response = await self._client.get(path)
        except httpx.HTTPError as exc:
            raise NewsCalendarUnavailable(f"forexfactory unreachable: {exc}") from exc
        if response.status_code != 200:
            raise NewsCalendarUnavailable(
                f"forexfactory {path} -> {response.status_code}: {response.text}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise NewsCalendarUnavailable(f"forexfactory returned invalid JSON: {exc}") from exc


def _parse_row(row: dict) -> NewsEvent | None:
    try:
        impact = _IMPACT_MAP.get(str(row["impact"]).lower())
        if impact is None:
            return None
        return NewsEvent(
            name=row["title"],
            time=datetime.fromisoformat(row["date"]).astimezone(UTC),
            impact=impact,
            currency=row.get("country", ""),
            forecast=row.get("forecast") or None,
            previous=row.get("previous") or None,
            # the weekly feed never carries a released "actual" value
        )
    except (KeyError, ValueError):
        return None
