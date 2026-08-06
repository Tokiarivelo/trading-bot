"""Logging setup.

Money-touching decisions (signals, vetoes, spread checks, lot calculations)
are logged at INFO by their modules — this configures where they go: stdout,
plus (when `database_url` is given) a persisted activity log queryable via
`GET /activity/history` (see `src.activity`).

`log_format` (OBSERVABILITY_PLAN.md Phase 5) selects the stdout line shape:
`"human"` (default) is the original single-line printf format meant for a
terminal; `"json"` is one JSON object per line — the same fields plus the
`account_id`/`signal_id` correlation ids from `shared/logging/account_context.py`
— meant for a log aggregator. This is a selectable *alternative*, not a
replacement: nothing about the persisted activity-log path changes either
way, and "human" stays the default so `make dev-backend` output is unaffected.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
from typing import Literal

from src.activity.adapters.log_handler import attach_activity_log_handler
from src.activity.adapters.repository import ActivityLogRepository
from src.shared.db.base import make_session_factory
from src.shared.logging.context_filter import ContextFilter

LogFormat = Literal["human", "json"]

_HUMAN_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


class _JSONFormatter(logging.Formatter):
    """One JSON object per line: `timestamp`, `level`, `logger`, `message`,
    `account_id`, `signal_id`, plus `exception` when the record carries one.
    Deliberately flat (no nested objects) so a log shipper's default
    field-per-key mapping needs no configuration."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "account_id": getattr(record, "account_id", None),
            "signal_id": getattr(record, "signal_id", None),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def _configure_stdout_handler(level: str, log_format: LogFormat) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(ContextFilter())
    handler.setFormatter(
        _JSONFormatter() if log_format == "json" else logging.Formatter(_HUMAN_FORMAT)
    )
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = [handler]


def configure_logging(
    level: str = "INFO",
    database_url: str | None = None,
    log_format: LogFormat = "human",
) -> logging.handlers.QueueListener | None:
    _configure_stdout_handler(level, log_format)
    if database_url is None:
        return None
    repository = ActivityLogRepository(make_session_factory(database_url))
    return attach_activity_log_handler(repository, level=logging.getLevelName(level))
