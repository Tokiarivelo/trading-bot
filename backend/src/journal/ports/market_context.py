"""Port: where the M5/H1 candle windows around a trade come from."""

from __future__ import annotations

from typing import Protocol

from src.journal.domain.models import CandleSnapshot, MarketSnapshot


class MarketContextPort(Protocol):
    async def capture(self, symbol: str) -> MarketSnapshot:
        """M5 ±50 / H1 ±20 candles around "now" (§6.8) — approximated as the
        most recent bars, since trades are journaled at fill time."""
        ...

    async def latest_candle(self, symbol: str, timeframe: str) -> CandleSnapshot | None:
        """The most recently closed candle on `timeframe` — one bar, not a
        window. Feeds the MFE/MAE accumulator (Phase 3), which runs on every
        `CandleClosed` and only needs that bar's high/low. `None` when the
        symbol has no stored candles yet."""
        ...
