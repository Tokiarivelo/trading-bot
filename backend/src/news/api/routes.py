"""Economic calendar REST endpoints (§6.7, §8). Read-only status for the UI —
the engine reacts to news windows internally via `NewsSkillSelector` and the
`NewsWindowEntered`/`NewsWindowExited` events; nothing here can trigger a
flatten or change trading behavior.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request

from src.news.api.schemas import NewsEventOut, NewsWindowOut

router = APIRouter(prefix="/news", tags=["news"])


def _container(request: Request) -> Any:
    return request.app.state.container


def _event_out(event: Any, skill: str | None) -> NewsEventOut:
    return NewsEventOut(
        name=event.name,
        time=int(event.time.timestamp()),
        impact=event.impact.value,
        currency=event.currency,
        skill=skill,
        forecast=event.forecast,
        previous=event.previous,
        actual=event.actual,
    )


@router.get(
    "/upcoming",
    response_model=list[NewsEventOut],
    summary="List upcoming calendar events",
    description=(
        "Events from the configured calendar source (`configs/news.yaml: "
        "calendar.source`) within `days_ahead`, from the last background "
        "refresh — this never fetches the calendar live, so it returns "
        "instantly. Each event's `skill` field shows which news skill (if "
        "any) will activate a trading window around it, resolved from "
        "`configs/news.yaml: tracked_events`."
    ),
)
async def get_upcoming(
    request: Request,
    days_ahead: Annotated[
        int, Query(ge=1, le=30, description="How many days ahead to include.")
    ] = 7,
) -> list[NewsEventOut]:
    service = _container(request).news_window_service
    return [_event_out(event, service.skill_for(event)) for event in service.upcoming(days_ahead)]


@router.get(
    "/active-windows",
    response_model=list[NewsWindowOut],
    summary="List currently active news windows",
    description=(
        "News windows active right now — i.e. `configs/app.yaml`-configured "
        "symbols currently trading under a news skill instead of their "
        "normal one, per `NewsSkillSelector`'s priority "
        "'news skill > symbol normal skill > global default' (§6.6). Empty "
        "outside any tracked event's before/after window."
    ),
)
async def get_active_windows(request: Request) -> list[NewsWindowOut]:
    service = _container(request).news_window_service
    now = datetime.now(UTC)
    out = []
    for window in service.active_windows(now):
        out.append(
            NewsWindowOut(
                event=_event_out(window.event, window.skill),
                skill=window.skill,
                window_start=int(window.window_start.timestamp()),
                window_end=int(window.window_end.timestamp()),
                phase="pre" if window.is_pre(now) else "post",
                symbols=list(service.symbols_for(window.skill)),
            )
        )
    return out
