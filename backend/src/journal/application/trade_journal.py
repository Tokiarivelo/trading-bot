"""Trade journal use cases (§6.8): record entries/exits with market-context
snapshots, serve chart markers and trade history, trigger the 10-trade review.

Subscribes to PositionOpened/PositionClosed on the event bus rather than being
called directly by the broker module — see §4 "event-driven core".
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace

from src.journal.adapters.repository import JournalRepository
from src.journal.domain.models import TradeRecord
from src.journal.ports.market_context import MarketContextPort
from src.shared.events.bus import EventBus
from src.shared.events.definitions import PositionClosed, PositionOpened, TenTradesCompleted

logger = logging.getLogger(__name__)


class TradeJournalService:
    def __init__(
        self,
        repository: JournalRepository,
        market_context: MarketContextPort,
        event_bus: EventBus,
        review_every_n_trades: int = 10,
    ) -> None:
        self._repository = repository
        self._market_context = market_context
        self._event_bus = event_bus
        self._review_every_n_trades = review_every_n_trades

    async def on_position_opened(self, event: PositionOpened) -> None:
        snapshot = await self._market_context.capture(event.symbol)
        record = TradeRecord(
            id=event.position_id,
            symbol=event.symbol,
            side=event.side,
            volume=event.volume,
            open_price=event.price,
            open_time=event.occurred_at,
            sl=event.sl,
            tp=event.tp,
            spread_points_at_entry=event.spread_points,
            comment=event.comment,
            strategy_version=event.strategy_version,
            skill=event.skill,
            m5_entry_snapshot=snapshot.m5,
            h1_entry_snapshot=snapshot.h1,
        )
        await asyncio.to_thread(self._repository.save, record)
        logger.info(
            "trade journaled (open): id=%s %s %s %.2f lots @ %.5f",
            record.id,
            event.side,
            event.symbol,
            event.volume,
            event.price,
        )

    async def on_position_closed(self, event: PositionClosed) -> None:
        existing = await asyncio.to_thread(self._repository.get, event.position_id)
        if existing is None:
            logger.warning(
                "position closed but no journaled trade found: id=%s symbol=%s",
                event.position_id,
                event.symbol,
            )
            return
        snapshot = await self._market_context.capture(event.symbol)
        closed = replace(
            existing,
            close_price=event.close_price,
            close_time=event.occurred_at,
            profit=event.profit,
            m5_exit_snapshot=snapshot.m5,
            h1_exit_snapshot=snapshot.h1,
        )
        await asyncio.to_thread(self._repository.save, closed)
        logger.info(
            "trade journaled (close): id=%s %s profit=%.2f", closed.id, closed.symbol, event.profit
        )

        closed_count = await asyncio.to_thread(self._repository.count_closed, event.symbol)
        if closed_count > 0 and closed_count % self._review_every_n_trades == 0:
            last_n = await asyncio.to_thread(
                self._repository.get_last_n_closed, event.symbol, self._review_every_n_trades
            )
            logger.info(
                "%d trades completed for %s — triggering AI review",
                self._review_every_n_trades,
                event.symbol,
            )
            await self._event_bus.publish(
                TenTradesCompleted(
                    symbol=event.symbol, trade_ids=tuple(t.id for t in reversed(last_n))
                )
            )

    async def get_markers(
        self, symbol: str, frm: int | None = None, to: int | None = None
    ) -> list[TradeRecord]:
        return await asyncio.to_thread(self._repository.get_markers, symbol, frm, to)

    async def get_last_n(self, symbol: str, count: int) -> list[TradeRecord]:
        return await asyncio.to_thread(self._repository.get_last_n, symbol, count)

    async def get_open_trades(self, symbol: str | None = None) -> list[TradeRecord]:
        return await asyncio.to_thread(self._repository.get_open, symbol)
