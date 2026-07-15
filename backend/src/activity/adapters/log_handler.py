"""Bridges stdlib `logging` records into the activity log table.

Attached to the `"src"` logger (see `shared/logging/setup.py`) so every
module's `logging.getLogger(__name__)` call — engine decisions, broker fills,
skill routing, risk vetoes — propagates here without each call site knowing
persistence exists. Writes run on a background `QueueListener` thread so a
DB insert never blocks the asyncio event loop that emitted the log line.
"""

from __future__ import annotations

import logging
import logging.handlers
import queue

from src.activity.adapters.repository import ActivityLogRepository


class _DBLogHandler(logging.Handler):
    def __init__(self, repository: ActivityLogRepository) -> None:
        super().__init__()
        self._repository = repository

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._repository.save(
                created_at=int(record.created),
                level=record.levelname,
                logger=record.name,
                message=self.format(record),
            )
        except Exception:
            self.handleError(record)


def attach_activity_log_handler(
    repository: ActivityLogRepository, level: int = logging.INFO
) -> logging.handlers.QueueListener:
    """Attaches a queued DB-backed handler to the `"src"` logger and starts its
    listener thread. Returns the listener so the caller can `.stop()` it on
    shutdown."""
    log_queue: queue.SimpleQueue = queue.SimpleQueue()
    queue_handler = logging.handlers.QueueHandler(log_queue)
    queue_handler.setLevel(level)

    db_handler = _DBLogHandler(repository)
    db_handler.setLevel(level)
    db_handler.setFormatter(logging.Formatter("%(message)s"))

    listener = logging.handlers.QueueListener(log_queue, db_handler, respect_handler_level=True)
    logging.getLogger("src").addHandler(queue_handler)
    listener.start()
    return listener
