"""MarketContextPort adapter over market_data's CandleRepository.

Wired at the composition root (container.py) — journal's domain/application
never import market_data directly; only this adapter does.
"""

from __future__ import annotations

import asyncio

from src.journal.domain.models import CandleSnapshot, MarketSnapshot
from src.market_data.adapters.candle_repository import CandleRepository
from src.market_data.domain.models import Candle, Timeframe

_M5_COUNT = 50
_H1_COUNT = 20


class CandleRepositoryMarketContext:
    def __init__(self, repository: CandleRepository) -> None:
        self._repository = repository

    async def capture(self, symbol: str) -> MarketSnapshot:
        m5, h1 = await asyncio.gather(
            asyncio.to_thread(self._repository.get_latest, symbol, Timeframe.M5, _M5_COUNT),
            asyncio.to_thread(self._repository.get_latest, symbol, Timeframe.H1, _H1_COUNT),
        )
        return MarketSnapshot(
            m5=tuple(_to_snapshot(c) for c in m5), h1=tuple(_to_snapshot(c) for c in h1)
        )


def _to_snapshot(candle: Candle) -> CandleSnapshot:
    return CandleSnapshot(
        time=candle.time,
        open=candle.open,
        high=candle.high,
        low=candle.low,
        close=candle.close,
        tick_volume=candle.tick_volume,
    )
