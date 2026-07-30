"""Journal domain: the trade record and its market-context snapshots (§6.8).

Pure values — no I/O. `id` is the broker position ticket (as a string), the
natural unique key shared with the broker/engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, kw_only=True)
class CandleSnapshot:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    tick_volume: int


@dataclass(frozen=True, kw_only=True)
class MarketSnapshot:
    m5: tuple[CandleSnapshot, ...] = ()
    h1: tuple[CandleSnapshot, ...] = ()


@dataclass(frozen=True, kw_only=True)
class TradeRecord:
    id: str
    symbol: str
    side: str  # "buy" | "sell"
    volume: float
    open_price: float
    open_time: datetime
    sl: float | None
    tp: float | None
    spread_points_at_entry: int
    comment: str = ""
    # Filled in by later phases (strategies/skills don't exist yet in Phase 3).
    strategy_version: str | None = None
    skill: str | None = None
    close_price: float | None = None
    close_time: datetime | None = None
    profit: float | None = None
    m5_entry_snapshot: tuple[CandleSnapshot, ...] = ()
    h1_entry_snapshot: tuple[CandleSnapshot, ...] = ()
    m5_exit_snapshot: tuple[CandleSnapshot, ...] = ()
    h1_exit_snapshot: tuple[CandleSnapshot, ...] = ()
    # "Why" the bot took this trade — the strategy's Signal.reason/confidence
    # and chart-annotation data (see strategies/domain/models.py), passed
    # through PositionOpened. Empty/None for manually- or API-placed trades.
    reason: str = ""
    confidence: float | None = None
    zone_kind: str | None = None  # "demand" | "supply"
    zone_price_low: float | None = None
    zone_price_high: float | None = None
    zone_time_start: datetime | None = None
    zone_time_end: datetime | None = None
    pattern: str | None = None
    structure: tuple[tuple[str, float, datetime], ...] = ()
    """Swing points as (label, price, time), label one of HH/HL/LH/LL."""

    @property
    def is_open(self) -> bool:
        return self.close_time is None


@dataclass(frozen=True, kw_only=True)
class TradeAnalyticsRecord:
    """Slim projection of `TradeRecord` carrying only the fields
    `domain/analytics.py`'s aggregation actually reads (id, symbol, volume,
    open/close time, profit, skill, strategy_version). Backs
    `JournalRepository.get_all_for_analytics`, which selects just these
    columns so SQLAlchemy never deserializes the four JSON snapshot/structure
    columns (`m5/h1_entry/exit_snapshot`, `structure`) that analytics never
    touches. `compute_symbol_analytics`/`compute_bot_analytics` accept either
    this or a full `TradeRecord` — they only use attributes both share."""

    id: str
    symbol: str
    volume: float
    open_time: datetime
    close_time: datetime | None
    profit: float | None
    skill: str | None
    strategy_version: str | None

    @property
    def is_open(self) -> bool:
        return self.close_time is None
