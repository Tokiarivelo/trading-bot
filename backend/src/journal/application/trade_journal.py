"""Trade journal use cases (§6.8): record entries/exits with market-context
snapshots, serve chart markers and trade history, trigger the 10-trade review.

Subscribes to PositionOpened/PositionClosed on the event bus rather than being
called directly by the broker module — see §4 "event-driven core".
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from typing import Literal

from src.journal.adapters.repository import JournalRepository, OrderField, Outcome
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
        account_id: str = "default",
    ) -> None:
        self._repository = repository
        self._market_context = market_context
        self._event_bus = event_bus
        self._review_every_n_trades = review_every_n_trades
        self._account_id = account_id

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
        await asyncio.to_thread(self._repository.save, record, self._account_id)
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
        await asyncio.to_thread(self._repository.save, closed, self._account_id)
        logger.info(
            "trade journaled (close): id=%s %s profit=%.2f", closed.id, closed.symbol, event.profit
        )

        if closed.skill is None:
            # No bot attributed this trade (manual/API-placed) — nothing to
            # review, and folding it into a shared per-symbol count would
            # misattribute it to whichever bot happens to run next.
            return
        closed_count = await asyncio.to_thread(
            self._repository.count_closed, event.symbol, closed.skill, self._account_id
        )
        if closed_count > 0 and closed_count % self._review_every_n_trades == 0:
            last_n = await asyncio.to_thread(
                self._repository.get_last_n_closed,
                event.symbol,
                self._review_every_n_trades,
                closed.skill,
                self._account_id,
            )
            logger.info(
                "%d trades completed for %s [%s] — triggering AI review",
                self._review_every_n_trades,
                event.symbol,
                closed.skill,
            )
            await self._event_bus.publish(
                TenTradesCompleted(
                    symbol=event.symbol,
                    skill=closed.skill,
                    trade_ids=tuple(t.id for t in reversed(last_n)),
                )
            )

    async def get_markers(
        self,
        symbol: str,
        frm: int | None = None,
        to: int | None = None,
        skill: str | None = None,
        limit: int = 1000,
    ) -> list[TradeRecord]:
        return await asyncio.to_thread(
            self._repository.get_markers, symbol, frm, to, skill, limit, self._account_id
        )

    async def get_last_n(self, symbol: str, count: int) -> list[TradeRecord]:
        return await asyncio.to_thread(
            self._repository.get_last_n, symbol, count, self._account_id
        )

    async def get_open_trades(self, symbol: str | None = None) -> list[TradeRecord]:
        return await asyncio.to_thread(self._repository.get_open, symbol, self._account_id)

    async def search_trades(
        self,
        *,
        symbol: str | None = None,
        side: str | None = None,
        strategy_version: str | None = None,
        skill: str | None = None,
        outcome: Outcome | None = None,
        open_from: int | None = None,
        open_to: int | None = None,
        close_from: int | None = None,
        close_to: int | None = None,
        order_by: OrderField = "open_time",
        order_dir: Literal["asc", "desc"] = "desc",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[TradeRecord], int]:
        return await asyncio.to_thread(
            self._repository.search,
            symbol=symbol,
            side=side,
            strategy_version=strategy_version,
            skill=skill,
            outcome=outcome,
            open_from=open_from,
            open_to=open_to,
            close_from=close_from,
            close_to=close_to,
            order_by=order_by,
            order_dir=order_dir,
            limit=limit,
            offset=offset,
            account_id=self._account_id,
        )
