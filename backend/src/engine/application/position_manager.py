"""Position manager (§6.4, §7.2): breakeven moves and time-stops on open
positions, driven by the engine's M5 clock.

Runs after every M5 `CandleClosed`, once per symbol, over that symbol's open
positions (from `BrokerPort.get_positions`) rather than the journal, since a
manually-opened position (via the broker API) must be managed too.
"""

from __future__ import annotations

import logging

from src.broker.application.order_service import OrderService
from src.broker.domain.trading import Position, Side
from src.market_data.ports.market_data import MarketDataPort

logger = logging.getLogger(__name__)

DEFAULT_TIME_STOP_CANDLES = 48  # 4 hours of M5 bars with no progress


class PositionManager:
    def __init__(
        self,
        order_service: OrderService,
        market_data: MarketDataPort,
        time_stop_candles: int = DEFAULT_TIME_STOP_CANDLES,
    ) -> None:
        self._order_service = order_service
        self._market_data = market_data
        self._time_stop_candles = time_stop_candles
        self._candles_since_open: dict[int, int] = {}

    async def on_candle_closed(self, symbol: str) -> None:
        positions = await self._order_service.get_positions(symbol)
        open_tickets = {p.ticket for p in positions}
        for ticket in [t for t in self._candles_since_open if t not in open_tickets]:
            del self._candles_since_open[ticket]

        for position in positions:
            self._candles_since_open[position.ticket] = (
                self._candles_since_open.get(position.ticket, 0) + 1
            )
            await self._manage(position)

    async def _manage(self, position: Position) -> None:
        if position.sl is None:
            return
        info = await self._market_data.get_symbol_info(position.symbol)
        mark = info.bid if position.side is Side.BUY else info.ask
        direction = 1 if position.side is Side.BUY else -1
        risk = abs(position.open_price - position.sl)
        progress = (mark - position.open_price) * direction

        already_at_breakeven = position.sl == position.open_price
        if not already_at_breakeven and risk > 0 and progress >= risk:
            await self._order_service.modify_position(
                position.ticket, sl=position.open_price, tp=position.tp
            )
            logger.info(
                "breakeven: ticket=%d %s sl moved to entry %.5f",
                position.ticket,
                position.symbol,
                position.open_price,
            )
            return

        candles_open = self._candles_since_open.get(position.ticket, 0)
        if candles_open >= self._time_stop_candles and progress <= 0:
            await self._order_service.close_position(position.ticket)
            logger.info(
                "time-stop: ticket=%d %s closed after %d candles without progress",
                position.ticket,
                position.symbol,
                candles_open,
            )
            del self._candles_since_open[position.ticket]
