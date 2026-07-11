"""Core event types exchanged between modules.

Phase 0 defines the shapes the whole system is built around; later phases
fill in richer payloads as the domain models land.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True, kw_only=True)
class Event:
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, kw_only=True)
class CandleClosed(Event):
    symbol: str
    timeframe: str  # "M5" | "H1" | "H4" | "D1"


@dataclass(frozen=True, kw_only=True)
class PositionOpened(Event):
    symbol: str
    position_id: str
    side: str  # "buy" | "sell"
    volume: float
    price: float
    sl: float | None
    tp: float | None
    spread_points: int
    comment: str = ""
    strategy_version: str | None = None
    skill: str | None = None


@dataclass(frozen=True, kw_only=True)
class PositionClosed(Event):
    symbol: str
    position_id: str
    close_price: float
    profit: float


@dataclass(frozen=True, kw_only=True)
class TenTradesCompleted(Event):
    """Emitted by the journal every 10 closed trades → triggers AI review."""

    symbol: str
    trade_ids: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class NewsWindowEntered(Event):
    event_name: str
    symbols: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class NewsWindowExited(Event):
    event_name: str
    symbols: tuple[str, ...]
