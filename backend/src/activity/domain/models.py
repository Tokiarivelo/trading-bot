"""Activity log domain: one persisted line of what the bot did and why.

Every `logging.getLogger("src.*")` call at INFO+ ends up here too (see
`shared/logging/adapters/handler.py`) — this is what backs the "why did/didn't
it take a position" question after the fact, not just live stdout.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, kw_only=True)
class LogEntry:
    id: int | None
    created_at: datetime
    level: str
    logger: str
    message: str


@dataclass(frozen=True, kw_only=True)
class BotSignal:
    """One strategy signal a live bot emitted — including ones that never
    became a trade (vetoed or rejected). Reconstructed from this bot's own
    `LogEntry` decision-trail lines (see `application/bot_signals.py`), the
    live analog of `backtest.domain.models.BacktestSignal` — kept as a
    separate type rather than importing that one so `activity` doesn't reach
    into the `backtest` module's internals (see CLAUDE.md)."""

    time: datetime
    direction: str  # "buy" | "sell"
    outcome: str
    """"opened" | "htf_veto" | "risk_rejected" | "spread_veto" | "broker_rejected"
    | "skipped" (no outcome line followed within the queried window)."""
    reason: str  # the strategy's own Signal.reason (pattern, zone, entry/sl/tp lines)
