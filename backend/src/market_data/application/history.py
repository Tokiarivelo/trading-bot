"""History use cases: serve chart/backtest reads, backfill the DB from the gateway."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from src.market_data.adapters.candle_repository import CandleRepository
from src.market_data.domain.models import Candle, MarketDataUnavailable, Timeframe
from src.market_data.ports.market_data import MarketDataPort

logger = logging.getLogger(__name__)


class CandleHistoryService:
    def __init__(self, market_data: MarketDataPort, repository: CandleRepository) -> None:
        self._market_data = market_data
        self._repository = repository

    async def get_candles(
        self, symbol: str, timeframe: Timeframe, count: int, before: datetime | None = None
    ) -> list[Candle]:
        """Live bars from the gateway; stored history when it's unreachable.
        `before` pages further back than the most recent `count` bars —
        see `MarketDataPort.get_candles`."""
        try:
            return await self._market_data.get_candles(symbol, timeframe, count, before)
        except MarketDataUnavailable:
            logger.info("gateway unavailable — serving %s %s from DB", symbol, timeframe.value)
            if before is None:
                return await asyncio.to_thread(
                    self._repository.get_latest, symbol, timeframe, count
                )
            return await asyncio.to_thread(
                self._repository.get_before, symbol, timeframe, before, count
            )

    async def backfill(self, symbol: str, timeframe: Timeframe, count: int) -> int:
        """Download `count` bars and persist them (forming bar included; it gets
        overwritten on the next poll). Returns bars stored."""
        candles = await self._market_data.get_candles(symbol, timeframe, count)
        stored = await asyncio.to_thread(self._repository.upsert_many, candles)
        logger.info("backfilled %s bars for %s %s", stored, symbol, timeframe.value)
        return stored
