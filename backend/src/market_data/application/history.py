"""History use cases: serve chart/backtest reads, backfill the DB from the gateway."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from src.market_data.adapters.candle_repository import CandleRepository
from src.market_data.adapters.replay import SymbolSpec
from src.market_data.adapters.symbol_spec_repository import SymbolSpecRepository
from src.market_data.domain.models import Candle, MarketDataUnavailable, Timeframe
from src.market_data.ports.market_data import MarketDataPort

logger = logging.getLogger(__name__)


class CandleHistoryService:
    def __init__(
        self,
        market_data: MarketDataPort,
        repository: CandleRepository,
        symbol_spec_repository: SymbolSpecRepository | None = None,
    ) -> None:
        self._market_data = market_data
        self._repository = repository
        self._symbol_spec_repository = symbol_spec_repository

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

    async def backfill(
        self, symbol: str, timeframe: Timeframe, count: int, start: datetime | None = None
    ) -> int:
        """Download bars and persist them. Without `start`, fetches the most
        recent `count` bars (forming bar included; it gets overwritten on the
        next poll) — this is what seeds `GET /candles`'s DB fallback. With
        `start`, pages backward from now in `count`-sized chunks via the
        `before` cursor (see `GatewayMarketData.get_candles`) until the oldest
        bar fetched reaches `start` or the broker's history runs out — a
        single gateway call is capped at `count` (<=5000) bars, so this is
        what lets `POST /backtest/run` replay a multi-month/year range.
        Returns total bars stored."""
        if start is None:
            candles = await self._market_data.get_candles(symbol, timeframe, count)
            stored = await asyncio.to_thread(self._repository.upsert_many, candles)
            logger.info("backfilled %s bars for %s %s", stored, symbol, timeframe.value)
            return stored

        total = 0
        before: datetime | None = None
        # Bounds the loop even if the gateway ever misbehaves (e.g. returns a
        # full page without moving `before` backward) — 2000 pages covers
        # decades of M1 history, far beyond any real request.
        for _ in range(2000):
            page = await self._market_data.get_candles(symbol, timeframe, count, before)
            if not page:
                break
            total += await asyncio.to_thread(self._repository.upsert_many, page)
            oldest = page[0].time
            if oldest <= start or len(page) < count:
                break
            before = oldest
        logger.info(
            "backfilled %s bars for %s %s back to %s", total, symbol, timeframe.value, start
        )
        return total

    async def sync_symbol_spec(self, symbol: str) -> None:
        """Fetches `symbol`'s static broker facts (point, digits, stops_level,
        contract_size, volume min/max/step) from the live gateway and persists
        them, so `run_backtest` can replay this symbol offline afterward
        without a hand-authored `configs/symbols/<symbol>.yaml` — see
        `SymbolSpecRepository`. No-ops with a warning if this service wasn't
        wired with a `symbol_spec_repository` (e.g. a lightweight test
        container that never calls it)."""
        if self._symbol_spec_repository is None:
            logger.warning(
                "sync_symbol_spec(%s): no symbol_spec_repository wired — skipping", symbol
            )
            return
        info = await self._market_data.get_symbol_info(symbol)
        spec = SymbolSpec(
            point=info.point,
            digits=info.digits,
            stops_level=info.stops_level,
            contract_size=info.contract_size,
            volume_min=info.volume_min,
            volume_max=info.volume_max,
            volume_step=info.volume_step,
        )
        await asyncio.to_thread(self._symbol_spec_repository.upsert, symbol, spec)
        logger.info("synced symbol spec for %s", symbol)
