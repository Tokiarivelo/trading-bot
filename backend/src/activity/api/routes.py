"""Activity log endpoints — filterable, paginated history of what the bot did
and why (every `src.*` INFO+ log line, persisted)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request

from src.activity.api.schemas import (
    LogDeleteByFilterRequest,
    LogDeleteByIdsRequest,
    LogDeleteResult,
    LogEntryOut,
    LogHistoryPage,
)
from src.activity.domain.models import LogEntry

router = APIRouter(prefix="/activity", tags=["activity"])


def _service(request: Request) -> Any:
    return request.app.state.container.activity_log


def _log_out(entry: LogEntry) -> LogEntryOut:
    return LogEntryOut(
        id=entry.id or 0,
        created_at=int(entry.created_at.timestamp()),
        level=entry.level,
        logger=entry.logger,
        message=entry.message,
    )


@router.get(
    "/history",
    response_model=LogHistoryPage,
    summary="Search and paginate the bot's activity log",
    description=(
        "Returns a filtered, paginated page of persisted log lines from every backend "
        "module (engine decisions, broker fills, skill routing, risk vetoes, spread gate, "
        "circuit breaker) — the durable answer to 'what is the bot doing and why', beyond "
        "what scrolls past in stdout. Newest first by default."
    ),
)
async def get_history(
    request: Request,
    level: str | None = Query(
        default=None, description="Exact level match, e.g. 'INFO', 'WARNING', 'ERROR'."
    ),
    logger_contains: str | None = Query(
        default=None,
        description="Substring match on the logger name, e.g. 'trade_loop' or 'broker'.",
    ),
    q: str | None = Query(
        default=None, description="Substring match on the message text, e.g. a symbol or reason."
    ),
    created_from: int | None = Query(
        default=None, description="Only entries at/after this epoch-seconds UTC."
    ),
    created_to: int | None = Query(
        default=None, description="Only entries at/before this epoch-seconds UTC."
    ),
    limit: int = Query(default=100, ge=1, le=1000, description="Page size."),
    offset: int = Query(default=0, ge=0, description="Number of matching entries to skip."),
) -> LogHistoryPage:
    entries, total = await _service(request).search(
        level=level,
        logger_contains=logger_contains,
        q=q,
        created_from=created_from,
        created_to=created_to,
        limit=limit,
        offset=offset,
    )
    return LogHistoryPage(items=[_log_out(e) for e in entries], total=total)


@router.post(
    "/history/delete-by-ids",
    response_model=LogDeleteResult,
    summary="Delete specific activity log entries",
    description=(
        "Hard-deletes the given log rows by id. Backs both single-row delete and "
        "multi-select bulk delete in the activity log UI. This cannot be undone."
    ),
)
async def delete_by_ids(request: Request, body: LogDeleteByIdsRequest) -> LogDeleteResult:
    deleted = await _service(request).delete_by_ids(body.ids)
    return LogDeleteResult(deleted=deleted)


@router.post(
    "/history/delete-by-filter",
    response_model=LogDeleteResult,
    summary="Delete every activity log entry matching a filter",
    description=(
        "Hard-deletes every log row matching the given filters, using the same filter "
        "semantics as `GET /activity/history` (omitting all fields deletes every row). "
        "Backs 'delete all matching' in the activity log UI. This cannot be undone."
    ),
)
async def delete_by_filter(request: Request, body: LogDeleteByFilterRequest) -> LogDeleteResult:
    deleted = await _service(request).delete_by_filter(
        level=body.level,
        logger_contains=body.logger_contains,
        q=body.q,
        created_from=body.created_from,
        created_to=body.created_to,
    )
    return LogDeleteResult(deleted=deleted)
