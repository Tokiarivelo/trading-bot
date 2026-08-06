"""Stamps `account_id`/`signal_id` onto `LogRecord`s from the ContextVars in
`account_context.py`, at the moment the log call happens.

This has to run as a `logging.Filter` attached upstream of anything
queue-based (`activity/adapters/log_handler.py`'s `QueueHandler`), not read
directly by whatever eventually handles the record. `logging.handlers.
QueueListener` dispatches queued records on its own dedicated
`threading.Thread` (see its `_monitor` loop) — and a plain `threading.Thread`
does **not** inherit the spawning thread/task's `contextvars.Context` (unlike
`asyncio.to_thread`/`ThreadPoolExecutor`, which explicitly copy it). A
`ContextVar.get()` called on that listener thread therefore always sees its
`default=`, never whatever the asyncio task that produced the record had
`.set()`. Concretely: reading the ContextVars *inside* `_DBLogHandler.emit`
(which runs on the listener thread) silently stamped every persisted
activity-log row's `account_id` as `"default"` regardless of which account
produced it — this filter fixes that by capturing the values on the
producing thread, before the record is enqueued, and letting them ride along
on the record itself (a plain attribute survives the queue hop fine).
"""

from __future__ import annotations

import logging

from src.shared.logging.account_context import current_account_id, current_signal_id


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.account_id = current_account_id.get()  # type: ignore[attr-defined]
        record.signal_id = current_signal_id.get()  # type: ignore[attr-defined]
        return True
