"""Logging setup.

Money-touching decisions (signals, vetoes, spread checks, lot calculations)
are logged at INFO by their modules — this configures where they go: stdout,
plus (when `database_url` is given) a persisted activity log queryable via
`GET /activity/history` (see `src.activity`).
"""

from __future__ import annotations

import logging
import logging.handlers

from src.activity.adapters.log_handler import attach_activity_log_handler
from src.activity.adapters.repository import ActivityLogRepository
from src.shared.db.base import make_session_factory


def configure_logging(
    level: str = "INFO", database_url: str | None = None
) -> logging.handlers.QueueListener | None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    if database_url is None:
        return None
    repository = ActivityLogRepository(make_session_factory(database_url))
    return attach_activity_log_handler(repository, level=logging.getLevelName(level))
