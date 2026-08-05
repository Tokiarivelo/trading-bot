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
class SignalDecision:
    """One strategy signal and what the engine decided to do with it, recorded
    as a first-class row at the moment it happens — the typed replacement for
    regex-scraping `SIGNAL:`/`ENTRY *` log lines back out of `LogEntry`
    (`application/bot_signals.py`, now legacy/backfill-only).

    The engine writes one of these when a signal fires (`outcome="skipped"`,
    i.e. no terminal outcome yet) and updates `outcome` once the entry is
    filled, vetoed, or rejected. Human-readable log lines are still emitted —
    they are just no longer the source of truth.
    """

    signal_id: str
    """UUID4 hex assigned by the engine when the signal fires — the join key
    every later outcome update targets."""
    account_id: str
    bot: str  # full skill id, e.g. "normal/xauusd/breakout_v1"
    strategy: str  # StrategySpec.name
    symbol: str
    timeframe: str  # the bot's own entry timeframe, e.g. "M5"
    direction: str  # "buy" | "sell"
    price: float | None
    """Reference price the engine saw when the signal fired — ask for a buy,
    bid for a sell."""
    created_at: datetime
    outcome: str
    """Same CLOSED vocabulary as `BotSignal.outcome` (Phase 1 deliberately
    keeps it unchanged; splitting `risk_rejected` is Phase 2's job)."""
    reason: str
    confidence: float | None = None


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
    price: float | None = None
    """Reference price the engine saw when the signal fired — ask for a buy,
    bid for a sell. `None` for legacy log lines logged before the price was
    added to the `SIGNAL:` line, so the chart must treat it as optional."""
