"""Order use cases: pre-trade spread/RR gate, fill, publish position events.

The engine (Phase 4) will call `open_position`/`close_position` from the trade
loop; for now these are also reachable manually via the broker API so the
plumbing can be exercised end-to-end before the engine exists.
"""

from __future__ import annotations

import logging
from datetime import datetime

from src.broker.application.spread_gate import SpreadGate
from src.broker.domain.trading import (
    ExecutionResult,
    OrderRejected,
    OrderRequest,
    OrderType,
    PendingOrder,
    PendingOrderRequest,
    Position,
    Side,
)
from src.broker.ports.trading import BrokerPort
from src.market_data.ports.market_data import MarketDataPort
from src.shared.events.bus import EventBus
from src.shared.events.definitions import PositionClosed, PositionOpened

logger = logging.getLogger(__name__)


class OrderService:
    def __init__(
        self,
        broker: BrokerPort,
        market_data: MarketDataPort,
        spread_gate: SpreadGate,
        event_bus: EventBus,
    ) -> None:
        self._broker = broker
        self._market_data = market_data
        self._spread_gate = spread_gate
        self._event_bus = event_bus

    async def open_position(
        self,
        symbol: str,
        side: Side,
        volume: float,
        sl: float | None = None,
        tp: float | None = None,
        comment: str = "",
        strategy_version: str | None = None,
        skill: str | None = None,
        magic: int = 0,
        max_spread_points: int | None = None,
        zone_kind: str | None = None,
        zone_price_low: float | None = None,
        zone_price_high: float | None = None,
        zone_time_start: datetime | None = None,
        zone_time_end: datetime | None = None,
        pattern: str | None = None,
        structure: tuple[tuple[str, float, datetime], ...] = (),
    ) -> ExecutionResult:
        """`max_spread_points`, when set, overrides the symbol's configured
        cap for this order only — used by news skills to widen (or, in
        principle, tighten) the allowance during a post-event window
        (`SkillDecision.max_spread_points`, §6.6). `magic`, when set, is the
        MT5 magic number identifying which bot placed the order — lets
        several bots trading the same symbol be told apart on open
        positions (`SkillDecision.magic`, §6.6); 0 for manual/API orders.
        `zone_*`/`pattern`/`structure` are optional chart-annotation
        passthrough from the strategy's Signal (see strategies/domain/models.py)
        — kept as flat primitives here rather than importing that module's
        domain types, so the broker layer stays independent of the
        strategies module; they flow straight into the published
        `PositionOpened` event unused by order placement itself."""
        info = await self._market_data.get_symbol_info(symbol)
        reference_price = info.ask if side is Side.BUY else info.bid
        sl_distance = abs(reference_price - sl) if sl is not None else None
        tp_distance = abs(tp - reference_price) if tp is not None else None

        veto = self._spread_gate.check(
            symbol,
            info.spread_points,
            info.point,
            sl_distance,
            tp_distance,
            max_spread_override=max_spread_points,
        )
        if veto is not None:
            logger.info(
                "ENTRY REJECTED (spread/RR gate): %s %s spread=%dpts sl=%s tp=%s "
                "strategy=%s skill=%s — %s",
                side.value,
                symbol,
                info.spread_points,
                sl,
                tp,
                strategy_version,
                skill,
                veto.reason,
            )
            raise OrderRejected(veto.reason)

        order = OrderRequest(
            symbol=symbol, side=side, volume=volume, sl=sl, tp=tp, comment=comment, magic=magic
        )
        try:
            result = await self._broker.open_position(order)
        except OrderRejected as exc:
            # Unlike the spread/RR veto above, this is the broker/MT5 itself
            # refusing the order (stops too close, market closed, filling
            # mode, price moved, ...) — without this log the rejection was
            # previously invisible: the caller only sees `OrderRejected`
            # propagate and silently gives up on the candle.
            logger.info(
                "ENTRY REJECTED (broker): %s %s %.2f lots sl=%s tp=%s strategy=%s skill=%s — %s",
                side.value,
                symbol,
                volume,
                sl,
                tp,
                strategy_version,
                skill,
                exc,
            )
            raise
        logger.info(
            "ENTRY OPENED: ticket=%d %s %s %.2f lots @ %.5f sl=%s tp=%s spread=%dpts "
            "strategy=%s skill=%s magic=%d reason=%s",
            result.ticket,
            side.value,
            symbol,
            volume,
            result.price,
            sl,
            tp,
            result.spread_points,
            strategy_version,
            skill,
            magic,
            comment or "manual",
        )
        await self._event_bus.publish(
            PositionOpened(
                symbol=symbol,
                position_id=str(result.ticket),
                side=result.side.value,
                volume=result.volume,
                price=result.price,
                sl=result.sl,
                tp=result.tp,
                spread_points=result.spread_points,
                comment=result.comment,
                strategy_version=strategy_version,
                skill=skill,
                zone_kind=zone_kind,
                zone_price_low=zone_price_low,
                zone_price_high=zone_price_high,
                zone_time_start=zone_time_start,
                zone_time_end=zone_time_end,
                pattern=pattern,
                structure=structure,
            )
        )
        return result

    async def close_position(self, ticket: int, volume: float | None = None) -> ExecutionResult:
        result = await self._broker.close_position(ticket, volume)
        logger.info(
            "position closed: ticket=%d %s %.2f lots @ %.5f profit=%.2f",
            result.ticket,
            result.symbol,
            result.volume,
            result.price,
            result.profit or 0.0,
        )
        await self._event_bus.publish(
            PositionClosed(
                symbol=result.symbol,
                position_id=str(result.ticket),
                close_price=result.price,
                profit=result.profit or 0.0,
            )
        )
        return result

    async def close_at_price(self, ticket: int, price: float, at: datetime) -> ExecutionResult:
        """Backtest-only: close at an explicit price (e.g. an SL/TP touch
        detected from a historical bar's high/low). Requires a broker
        adapter that supports it (`PaperBroker`); raises `AttributeError`
        against the live gateway broker, which has no such concept."""
        result = await self._broker.close_at_price(ticket, price, at)
        logger.info(
            "position closed (explicit price): ticket=%d %s %.2f lots @ %.5f profit=%.2f",
            result.ticket,
            result.symbol,
            result.volume,
            result.price,
            result.profit or 0.0,
        )
        await self._event_bus.publish(
            PositionClosed(
                symbol=result.symbol,
                position_id=str(result.ticket),
                close_price=result.price,
                profit=result.profit or 0.0,
                occurred_at=at,
            )
        )
        return result

    async def close_all_positions(self, symbol: str) -> list[ExecutionResult]:
        """Closes every currently open position on `symbol`, one broker call
        per ticket via `close_position` (so each still logs and publishes its
        own `PositionClosed`). A single ticket's `OrderRejected` (e.g. broker
        refuses that specific close) is logged and skipped rather than
        aborting the rest of the batch — the caller sees which tickets
        actually closed via the returned list's length against the symbol's
        position count."""
        positions = await self._broker.get_positions(symbol)
        results: list[ExecutionResult] = []
        for position in positions:
            try:
                results.append(await self.close_position(position.ticket))
            except OrderRejected as exc:
                logger.info(
                    "close-all skipped ticket=%d %s — %s", position.ticket, symbol, exc
                )
        return results

    async def modify_position(self, ticket: int, sl: float | None, tp: float | None) -> None:
        await self._broker.modify_position(ticket, sl, tp)
        logger.info("position modified: ticket=%d sl=%s tp=%s", ticket, sl, tp)

    async def get_positions(self, symbol: str | None = None) -> list[Position]:
        return await self._broker.get_positions(symbol)

    async def place_pending_order(
        self,
        symbol: str,
        side: Side,
        order_type: OrderType,
        volume: float,
        price: float,
        sl: float | None = None,
        tp: float | None = None,
        comment: str = "",
    ) -> PendingOrder:
        order = PendingOrderRequest(
            symbol=symbol,
            side=side,
            order_type=order_type,
            volume=volume,
            price=price,
            sl=sl,
            tp=tp,
            comment=comment,
        )
        result = await self._broker.place_pending_order(order)
        logger.info(
            "pending order placed: ticket=%d %s %s %s %.2f lots @ %.5f sl=%s tp=%s",
            result.ticket,
            side.value,
            order_type.value,
            symbol,
            volume,
            price,
            sl,
            tp,
        )
        return result

    async def cancel_pending_order(self, ticket: int) -> None:
        await self._broker.cancel_pending_order(ticket)
        logger.info("pending order cancelled: ticket=%d", ticket)

    async def modify_pending_order(
        self, ticket: int, price: float | None, sl: float | None, tp: float | None
    ) -> None:
        await self._broker.modify_pending_order(ticket, price, sl, tp)
        logger.info("pending order modified: ticket=%d price=%s sl=%s tp=%s", ticket, price, sl, tp)

    async def get_pending_orders(self, symbol: str | None = None) -> list[PendingOrder]:
        return await self._broker.get_pending_orders(symbol)

    @property
    def simulates_pending_fills(self) -> bool:
        return self._broker.simulates_pending_fills
