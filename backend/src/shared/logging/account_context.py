"""Tags log records with the account whose background task produced them.

`logging.getLogger(__name__)` is one shared logger object per module, reused
by every account's `TradeEngine`/`OrderService`/etc. instance (Phase 5 of
MULTI_ACCOUNT_PLAN.md) — there's no per-instance place to stamp which account
a log line belongs to. A `ContextVar` fills that gap: each account's own
background task (`CandleStreamService._run`, `LiveCandleService._run`,
`GatewayHealthMonitor._run`) sets it once at startup, and everything awaited
within that task afterward — including `EventBus.publish` -> subscriber
handlers -> `logger.info(...)` — sees the right value, since `asyncio.gather`
copies the current context into each handler's child task at creation time.
`activity/adapters/log_handler.py` reads it to stamp `account_id` on the row
it persists.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from contextvars import ContextVar

current_account_id: ContextVar[str] = ContextVar("current_account_id", default="default")


@contextlib.contextmanager
def bind_account_id(account_id: str) -> Iterator[None]:
    token = current_account_id.set(account_id)
    try:
        yield
    finally:
        current_account_id.reset(token)
