"""Order execution domain: sides, orders, positions, fills. Pure values, no I/O."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    LIMIT = "limit"
    STOP = "stop"


@dataclass(frozen=True, kw_only=True)
class OrderRequest:
    symbol: str
    side: Side
    volume: float
    sl: float | None = None
    tp: float | None = None
    comment: str = ""


@dataclass(frozen=True, kw_only=True)
class PendingOrderRequest:
    symbol: str
    side: Side
    order_type: OrderType
    volume: float
    price: float
    sl: float | None = None
    tp: float | None = None
    comment: str = ""


@dataclass(frozen=True, kw_only=True)
class PendingOrder:
    ticket: int
    symbol: str
    side: Side
    order_type: OrderType
    volume: float
    price: float
    sl: float | None
    tp: float | None
    placed_time: datetime
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


@dataclass(frozen=True, kw_only=True)
class ClosedPositionInfo:
    """How a position that's no longer open actually closed, from the
    broker's deal history rather than the (transient) open-positions list —
    used to reconcile a broker-side SL/TP fill the backend didn't initiate
    (Phase 9 §12, reconnect/resume)."""

    symbol: str
    price: float
    time: datetime
    profit: float


class OrderRejected(Exception):
    """The broker (or a pre-trade rule) refused the order."""


def pending_order_triggered(order: PendingOrder, bid: float, ask: float) -> bool:
    """Whether the current market has crossed a resting limit/stop order's
    trigger price — a limit fills when price moves *toward* it from the far
    side (buying below market, selling above), a stop fills when price moves
    *through* it in the breakout direction (buying above market, selling
    below), mirroring MT5's own semantics for each order type."""
    if order.side is Side.BUY and order.order_type is OrderType.LIMIT:
        return ask <= order.price
    if order.side is Side.SELL and order.order_type is OrderType.LIMIT:
        return bid >= order.price
    if order.side is Side.BUY and order.order_type is OrderType.STOP:
        return ask >= order.price
    return bid <= order.price  # SELL + STOP
