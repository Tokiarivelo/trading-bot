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

    @property
    def is_open(self) -> bool:
        return self.close_time is None
