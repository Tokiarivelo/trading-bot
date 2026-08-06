"""Tags log records with the account (and, for the signal correlation ID
below, the in-flight signal) whose task produced them.

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

`current_signal_id` (OBSERVABILITY_PLAN.md Phase 5) reuses the exact same
mechanism for the *other* axis a log line needs to join up on: one signal's
whole life, signal -> sizing -> order -> fill -> journal. Unlike the account
id, which is set once for a background task's entire lifetime, the signal id
changes on every candidate a candle close evaluates — `TradeEngine._try_enter`
mints a fresh one per candidate and wraps only that candidate's
`_enter_for_bot` call in `bind_signal_id`, so the `SIGNAL:`/`ENTRY *` log
lines it emits, the `OrderService.open_position` call it makes (same task,
no new `asyncio.Task`, so the same context), and — via `EventBus.publish`'s
`asyncio.gather` — the journal's `on_position_opened` handler all see the
same id, and the context manager resets it the moment that candidate's
processing ends so it can never leak onto the next candidate or the next
candle's position-management pass.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from contextvars import ContextVar

current_account_id: ContextVar[str] = ContextVar("current_account_id", default="default")

current_signal_id: ContextVar[str | None] = ContextVar("current_signal_id", default=None)


@contextlib.contextmanager
def bind_account_id(account_id: str) -> Iterator[None]:
    token = current_account_id.set(account_id)
    try:
        yield
    finally:
        current_account_id.reset(token)


@contextlib.contextmanager
def bind_signal_id(signal_id: str) -> Iterator[None]:
    """Scopes `current_signal_id` to one signal's processing — see the
    module docstring for why this resets (unlike `bind_account_id`'s
    production call sites, which set-and-forget for a whole task's life)."""
    token = current_signal_id.set(signal_id)
    try:
        yield
    finally:
        current_signal_id.reset(token)
