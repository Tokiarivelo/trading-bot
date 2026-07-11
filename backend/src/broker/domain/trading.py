"""Order execution domain: sides, orders, positions, fills. Pure values, no I/O."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True, kw_only=True)
class OrderRequest:
    symbol: str
    side: Side
    volume: float
    sl: float | None = None
    tp: float | None = None
    comment: str = ""


@dataclass(frozen=True, kw_only=True)
class Position:
    ticket: int
    symbol: str
    side: Side
    volume: float
    open_price: float
    sl: float | None
    tp: float | None
    open_time: datetime
    profit: float
    comment: str = ""


@dataclass(frozen=True, kw_only=True)
class ExecutionResult:
    ticket: int
    symbol: str
    side: Side
    volume: float
    price: float
    sl: float | None
    tp: float | None
    time: datetime
    spread_points: int
    comment: str = ""
    profit: float | None = None  # populated on close fills; None on open fills


class OrderRejected(Exception):
    """The broker (or a pre-trade rule) refused the order."""
