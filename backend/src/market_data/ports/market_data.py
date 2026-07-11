"""Port: where candles/ticks/specs come from (live gateway, or replay in backtests)."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from src.market_data.domain.models import Candle, SymbolInfo, Tick, Timeframe


class MarketDataPort(Protocol):
    async def get_candles(
        self, symbol: str, timeframe: Timeframe, count: int, before: datetime | None = None
    ) -> list[Candle]:
        """Most recent `count` bars, oldest first; the last one may still be
        forming. When `before` is given, returns `count` bars with open time
        strictly before it instead — for paging further back in history."""
        ...

    async def get_tick(self, symbol: str) -> Tick: ...

    async def get_symbol_info(self, symbol: str) -> SymbolInfo: ...
