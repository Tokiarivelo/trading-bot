"""Position manager (§6.4, §7.2): breakeven moves and time-stops on open
positions, driven by the engine's M5 clock. Also manages resting limit/stop
orders placed manually from the chart (F-manual-trading): in paper mode it
triggers them itself once price crosses, gated by the same `RiskManager` as
automated entries; in live mode MT5 triggers them server-side and this only
detects and reconciles the fill afterward.

Runs after every M5 `CandleClosed`, once per symbol, over that symbol's open
positions (from `BrokerPort.get_positions`) rather than the journal, since a
manually-opened position (via the broker API) must be managed too.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from src.broker.application.order_service import OrderService
from src.broker.application.reconciliation import ReconciliationService
from src.broker.domain.trading import (
    OrderRejected,
    PendingOrder,
    Position,
    Side,
    pending_order_triggered,
)
from src.engine.application.risk_manager import RiskManager
from src.market_data.ports.market_data import MarketDataPort

logger = logging.getLogger(__name__)

DEFAULT_TIME_STOP_CANDLES = 48  # 4 hours of M5 bars with no progress


class PositionManager:
    def __init__(
        self,
        order_service: OrderService,
        market_data: MarketDataPort,
        reconciliation: ReconciliationService | None = None,
        risk_manager: RiskManager | None = None,
        time_stop_candles: int = DEFAULT_TIME_STOP_CANDLES,
    ) -> None:
        self._order_service = order_service
        self._market_data = market_data
        self._reconciliation = reconciliation
        self._risk_manager = risk_manager
        self._time_stop_candles = time_stop_candles
        self._candles_since_open: dict[int, int] = {}
        # symbol -> {ticket: order}, as of the last candle close — kept so a
        # vanished ticket's side/volume is still known when reconciling.
        self._pending_seen: dict[str, dict[int, PendingOrder]] = {}

    async def on_candle_closed(self, symbol: str) -> None:
        positions = await self._order_service.get_positions(symbol)
        open_tickets = {p.ticket for p in positions}
        vanished = [t for t in self._candles_since_open if t not in open_tickets]
        for ticket in vanished:
            del self._candles_since_open[ticket]
        # A ticket we were tracking that's no longer in the broker's open
        # list closed server-side (SL/TP fill) — nothing else in the system
        # would ever find out otherwise (§12 Phase 9).
        if vanished and self._reconciliation is not None:
            await self._reconciliation.reconcile_vanished(symbol, set(vanished))

        for position in positions:
            self._candles_since_open[position.ticket] = (
                self._candles_since_open.get(position.ticket, 0) + 1
            )
            await self._manage(position)

        if self._risk_manager is not None:
            await self._manage_pending_orders(symbol)

    async def _manage_pending_orders(self, symbol: str) -> None:
        pending = await self._order_service.get_pending_orders(symbol)
        if self._order_service.simulates_pending_fills:
            await self._fill_triggered_paper_orders(symbol, pending)
        else:
            await self._reconcile_live_pending_fills(symbol, pending)

    async def _fill_triggered_paper_orders(self, symbol: str, pending: list[PendingOrder]) -> None:
        if not pending:
            return
        info = await self._market_data.get_symbol_info(symbol)
        risk_manager = self._risk_manager
        assert risk_manager is not None
        for order in pending:
            if not pending_order_triggered(order, info.bid, info.ask):
                continue
            open_count = len(await self._order_service.get_positions())
            decision = risk_manager.check_pretrade(open_count, datetime.now(UTC))
            if not decision.approved:
                logger.info(
                    "pending order ticket=%d not filled this candle: %s",
                    order.ticket,
                    decision.reason,
                )
                continue
            try:
                await self._order_service.open_position(
                    order.symbol, order.side, order.volume, order.sl, order.tp, order.comment
                )
            except OrderRejected as exc:
                logger.info("pending order ticket=%d not filled this candle: %s", order.ticket, exc)
                continue
            await self._order_service.cancel_pending_order(order.ticket)
            risk_manager.record_trade_opened(datetime.now(UTC))

    async def _reconcile_live_pending_fills(self, symbol: str, pending: list[PendingOrder]) -> None:
        current = {o.ticket: o for o in pending}
        previous = self._pending_seen.get(symbol, {})
        vanished_tickets = set(previous) - set(current)
        self._pending_seen[symbol] = current
        if not vanished_tickets or self._reconciliation is None:
            return
        risk_manager = self._risk_manager
        assert risk_manager is not None
        for ticket in vanished_tickets:
            order = previous[ticket]
            filled = await self._reconciliation.reconcile_pending_fill(
                symbol, ticket, order.side, order.volume
            )
            if filled:
                risk_manager.record_trade_opened(datetime.now(UTC))

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
