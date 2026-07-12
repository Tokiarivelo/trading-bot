"""BrokerPort adapter that simulates fills — including spread — against live
market data, without touching a real account. Default in paper mode (§10.2)."""

from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from src.broker.domain.trading import (
    ClosedPositionInfo,
    ExecutionResult,
    OrderRejected,
    OrderRequest,
    OrderType,
    PendingOrder,
    PendingOrderRequest,
    Position,
    Side,
)
from src.market_data.ports.market_data import MarketDataPort

logger = logging.getLogger(__name__)


@dataclass
class _OpenPosition:
    ticket: int
    symbol: str
    side: Side
    volume: float
    open_price: float
    sl: float | None
    tp: float | None
    open_time: datetime
    comment: str


class PaperBroker:
    def __init__(self, market_data: MarketDataPort) -> None:
        self._market_data = market_data
        self._positions: dict[int, _OpenPosition] = {}
        self._pending: dict[int, PendingOrder] = {}
        self._tickets = itertools.count(1)

    async def open_position(self, order: OrderRequest) -> ExecutionResult:
        info = await self._market_data.get_symbol_info(order.symbol)
        fill_price = info.ask if order.side is Side.BUY else info.bid
        ticket = next(self._tickets)
        now = datetime.now(UTC)
        self._positions[ticket] = _OpenPosition(
            ticket=ticket,
            symbol=order.symbol,
            side=order.side,
            volume=order.volume,
            open_price=fill_price,
            sl=order.sl,
            tp=order.tp,
            open_time=now,
            comment=order.comment,
        )
        logger.info(
            "paper fill: %s %s %.2f lots @ %.5f sl=%s tp=%s spread=%dpts",
            order.side.value,
            order.symbol,
            order.volume,
            fill_price,
            order.sl,
            order.tp,
            info.spread_points,
        )
        return ExecutionResult(
            ticket=ticket,
            symbol=order.symbol,
            side=order.side,
            volume=order.volume,
            price=fill_price,
            sl=order.sl,
            tp=order.tp,
            time=now,
            spread_points=info.spread_points,
            comment=order.comment,
        )

    async def close_position(self, ticket: int, volume: float | None = None) -> ExecutionResult:
        position = self._positions.get(ticket)
        if position is None:
            raise OrderRejected(f"no open paper position with ticket {ticket}")
        info = await self._market_data.get_symbol_info(position.symbol)
        # Opposite side of the entry fill: a long closes at bid, a short at ask.
        close_price = info.bid if position.side is Side.BUY else info.ask
        close_volume = volume if volume is not None else position.volume
        direction = 1 if position.side is Side.BUY else -1
        profit = (close_price - position.open_price) * direction * info.contract_size * close_volume
        now = datetime.now(UTC)
        if close_volume >= position.volume:
            del self._positions[ticket]
        else:
            self._positions[ticket] = replace(position, volume=position.volume - close_volume)
        logger.info(
            "paper close: ticket=%d %s @ %.5f volume=%.2f profit=%.2f",
            ticket,
            position.symbol,
            close_price,
            close_volume,
            profit,
        )
        return ExecutionResult(
            ticket=ticket,
            symbol=position.symbol,
            side=position.side,
            volume=close_volume,
            price=close_price,
            sl=position.sl,
            tp=position.tp,
            time=now,
            spread_points=info.spread_points,
            comment=position.comment,
            profit=profit,
        )

    async def close_at_price(self, ticket: int, price: float, time: datetime) -> ExecutionResult:
        """Backtest-only: close at an explicit price (an SL/TP touch within a
        bar), bypassing the current-market-price lookup `close_position`
        uses — live paper trading has no such signal, only the backtest
        replay loop does, derived from a bar's high/low."""
        position = self._positions.get(ticket)
        if position is None:
            raise OrderRejected(f"no open paper position with ticket {ticket}")
        info = await self._market_data.get_symbol_info(position.symbol)
        direction = 1 if position.side is Side.BUY else -1
        profit = (price - position.open_price) * direction * info.contract_size * position.volume
        del self._positions[ticket]
        logger.info(
            "paper close (explicit price): ticket=%d %s @ %.5f volume=%.2f profit=%.2f",
            ticket,
            position.symbol,
            price,
            position.volume,
            profit,
        )
        return ExecutionResult(
            ticket=ticket,
            symbol=position.symbol,
            side=position.side,
            volume=position.volume,
            price=price,
            sl=position.sl,
            tp=position.tp,
            time=time,
            spread_points=info.spread_points,
            comment=position.comment,
            profit=profit,
        )

    async def modify_position(self, ticket: int, sl: float | None, tp: float | None) -> None:
        position = self._positions.get(ticket)
        if position is None:
            raise OrderRejected(f"no open paper position with ticket {ticket}")
        self._positions[ticket] = replace(position, sl=sl, tp=tp)

    async def get_positions(self, symbol: str | None = None) -> list[Position]:
        positions = []
        for p in self._positions.values():
            if symbol is not None and p.symbol != symbol:
                continue
            info = await self._market_data.get_symbol_info(p.symbol)
            mark = info.bid if p.side is Side.BUY else info.ask
            direction = 1 if p.side is Side.BUY else -1
            floating_profit = (mark - p.open_price) * direction * info.contract_size * p.volume
            positions.append(
                Position(
                    ticket=p.ticket,
                    symbol=p.symbol,
                    side=p.side,
                    volume=p.volume,
                    open_price=p.open_price,
                    sl=p.sl,
                    tp=p.tp,
                    open_time=p.open_time,
                    profit=floating_profit,
                    comment=p.comment,
                )
            )
        return positions

    async def get_close_info(self, ticket: int) -> ClosedPositionInfo | None:
        # Paper positions only ever close when our own code calls
        # close_position()/close_at_price() — there's no simulated broker
        # closing them behind our back, so reconciliation never needs this
        # in paper mode (live GatewayBroker is the only adapter it matters for).
        return None

    async def place_pending_order(self, order: PendingOrderRequest) -> PendingOrder:
        info = await self._market_data.get_symbol_info(order.symbol)
        if not _valid_pending_side(order.side, order.order_type, order.price, info.bid, info.ask):
            raise OrderRejected(
                f"invalid stops: {order.side.value} {order.order_type.value} at {order.price} "
                f"is on the wrong side of the current market (bid={info.bid} ask={info.ask})"
            )
        ticket = next(self._tickets)
        pending = PendingOrder(
            ticket=ticket,
            symbol=order.symbol,
            side=order.side,
            order_type=order.order_type,
            volume=order.volume,
            price=order.price,
            sl=order.sl,
            tp=order.tp,
            placed_time=datetime.now(UTC),
            comment=order.comment,
        )
        self._pending[ticket] = pending
        logger.info(
            "paper pending order placed: ticket=%d %s %s %s %.2f lots @ %.5f sl=%s tp=%s",
            ticket,
            order.side.value,
            order.order_type.value,
            order.symbol,
            order.volume,
            order.price,
            order.sl,
            order.tp,
        )
        return pending

    async def cancel_pending_order(self, ticket: int) -> None:
        if ticket not in self._pending:
            raise OrderRejected(f"no pending paper order with ticket {ticket}")
        del self._pending[ticket]
        logger.info("paper pending order cancelled: ticket=%d", ticket)

    async def modify_pending_order(
        self, ticket: int, price: float | None, sl: float | None, tp: float | None
    ) -> None:
        pending = self._pending.get(ticket)
        if pending is None:
            raise OrderRejected(f"no pending paper order with ticket {ticket}")
        self._pending[ticket] = replace(
            pending,
            price=price if price is not None else pending.price,
            sl=sl if sl is not None else pending.sl,
            tp=tp if tp is not None else pending.tp,
        )

    async def get_pending_orders(self, symbol: str | None = None) -> list[PendingOrder]:
        return [p for p in self._pending.values() if symbol is None or p.symbol == symbol]

    @property
    def simulates_pending_fills(self) -> bool:
        return True


def _valid_pending_side(
    side: Side, order_type: OrderType, price: float, bid: float, ask: float
) -> bool:
    if side is Side.BUY and order_type is OrderType.LIMIT:
        return price < ask
    if side is Side.SELL and order_type is OrderType.LIMIT:
        return price > bid
    if side is Side.BUY and order_type is OrderType.STOP:
        return price > ask
    return price < bid  # SELL + STOP
