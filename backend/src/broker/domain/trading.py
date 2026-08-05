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
    magic: int = 0
    """MT5 magic number identifying which bot placed this order — 0 for
    manually/API-placed orders with no bot attribution."""


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
    magic: int = 0
    """Which bot opened this position, per `OrderRequest.magic` — 0 for
    manually/API-placed positions."""


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
    magic: int = 0
    profit: float | None = None  # populated on close fills; None on open fills
    retcode: int | None = None
    """Broker return code for this deal — MT5's `OrderSendResult.retcode`
    (10009 `TRADE_RETCODE_DONE` on a successful fill). `None` for brokers
    that have no such concept (the paper broker) or a gateway too old to
    report it. Recorded on the trade so execution-quality analytics can tell
    a clean fill from one the broker only partly honoured
    (OBSERVABILITY_PLAN.md Phase 3)."""


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
    """The broker (or a pre-trade rule) refused the order.

    `retcode` is the broker's own numeric refusal code when the rejection came
    from the broker itself — MT5 `10016` (invalid stops) once silently killed
    an entire VIX75 fleet, and only the code identifies that unambiguously.
    `None` when the refusal came from a backend-side pre-trade rule (spread/RR
    gate, paper broker) or the gateway didn't report one."""

    def __init__(self, message: str, retcode: int | None = None) -> None:
        super().__init__(message)
        self.retcode = retcode


def execution_slippage(side: Side, requested_price: float, fill_price: float) -> float:
    """Signed slippage on a fill, in price units, oriented so a POSITIVE
    number always means the fill *cost* the trader.

    A buy fills badly when it pays more than the ask it asked for, a sell when
    it receives less than the bid it asked for — so the raw difference is
    negated for sells. Keeping the sign convention in one pure function (and
    not at each call site) is what makes "average slippage" comparable across
    long and short bots at all."""
    direction = 1.0 if side is Side.BUY else -1.0
    return (fill_price - requested_price) * direction


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
