"""Wire schema for the `/activity` HTTP API. Mirrors `activity/domain/models.py`."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LogEntryOut(BaseModel):
    """One persisted activity-log line — a bot decision, fill, veto, or
    status change, in the order it happened."""

    id: int = Field(description="Autoincrement row id, also the natural newest-first sort key.")
    created_at: int = Field(description="Epoch seconds UTC when the log line was emitted.")
    level: str = Field(description="Python logging level name, e.g. 'INFO', 'WARNING', 'ERROR'.")
    logger: str = Field(
        description="Originating logger name, e.g. 'src.engine.application.trade_loop' — "
        "identifies which module made the decision."
    )
    message: str = Field(description="The formatted log message, e.g. why a signal was vetoed.")


class LogHistoryPage(BaseModel):
    """One page of the filtered activity log history (`GET /activity/history`)."""

    items: list[LogEntryOut] = Field(description="Log entries matching the filters, one page.")
    total: int = Field(description="Total entries matching the filters, across all pages.")


class LogDeleteByIdsRequest(BaseModel):
    """Request body for deleting specific activity log rows — backs single-row
    delete and multi-select bulk delete in the activity log UI."""

    ids: list[int] = Field(
        description="Row ids to delete, as returned by `GET /activity/history`.", min_length=1
    )


class LogDeleteByFilterRequest(BaseModel):
    """Request body for deleting every activity log row matching a filter —
    backs "delete all matching" in the activity log UI. Mirrors the query
    filters of `GET /activity/history`; omitting all fields deletes every row."""

    level: str | None = Field(
        default=None, description="Exact level match, e.g. 'INFO', 'WARNING', 'ERROR'."
    )
    logger_contains: str | None = Field(
        default=None,
        description="Substring match on the logger name, e.g. 'trade_loop' or 'broker'.",
    )
    q: str | None = Field(
        default=None, description="Substring match on the message text, e.g. a symbol or reason."
    )
    created_from: int | None = Field(
        default=None, description="Only entries at/after this epoch-seconds UTC."
    )
    created_to: int | None = Field(
        default=None, description="Only entries at/before this epoch-seconds UTC."
    )


class LogDeleteResult(BaseModel):
    """Result of a bulk or single activity-log delete."""

    deleted: int = Field(description="Number of log entries removed.")
