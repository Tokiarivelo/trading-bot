"""Streams the currently-forming bar to chart clients on every poll tick, so
the rightmost candle updates continuously like MT5 instead of sitting frozen
until the whole bar closes.

Complements `CandleStreamService`, which handles the much coarser
persisted/event-bus close detection — this service never persists, never
publishes to the event bus, and only polls `symbol:timeframe` rooms someone
is actually watching right now (see `market_data.api.ws`).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from src.market_data.application.candle_stream import candle_message
from src.market_data.domain.models import MarketDataUnavailable, Timeframe
from src.market_data.ports.broadcast import MarketBroadcastPort
from src.market_data.ports.market_data import MarketDataPort

logger = logging.getLogger(__name__)

_POLL_INTERVAL_S = 1.5


class LiveCandleService:
    def __init__(
        self,
        market_data: MarketDataPort,
        broadcaster: MarketBroadcastPort,
        poll_interval: float = _POLL_INTERVAL_S,
    ) -> None:
        self._market_data = market_data
        self._broadcaster = broadcaster
        self._poll_interval = poll_interval
        # Ref-counted: the same room can be open in more than one browser tab.
        self._refcounts: dict[tuple[str, Timeframe], int] = {}
        # Dedupe fingerprint per room so we only broadcast when the forming
        # bar actually changed, not on every poll.
        self._last_sent: dict[tuple[str, Timeframe], tuple[int, float, float, float, int]] = {}
        self._task: asyncio.Task[None] | None = None

    def watch(self, symbol: str, timeframe: Timeframe) -> None:
        key = (symbol, timeframe)
        self._refcounts[key] = self._refcounts.get(key, 0) + 1

    def unwatch(self, symbol: str, timeframe: Timeframe) -> None:
        key = (symbol, timeframe)
        if key not in self._refcounts:
            return
        self._refcounts[key] -= 1
        if self._refcounts[key] <= 0:
            del self._refcounts[key]
            self._last_sent.pop(key, None)

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="live-candle-preview")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while True:
            for symbol, timeframe in list(self._refcounts):
                try:
                    await self.poll_one(symbol, timeframe)
                except MarketDataUnavailable:
                    pass
                except Exception:
                    logger.exception("live candle preview poll failed for %s %s", symbol, timeframe)
            await asyncio.sleep(self._poll_interval)

    async def poll_one(self, symbol: str, timeframe: Timeframe) -> None:
        """Fetch the latest (possibly still-forming) bar and broadcast it if
        it changed since the last poll. Public for tests."""
        candles = await self._market_data.get_candles(symbol, timeframe, 1)
        if not candles:
            return
        latest = candles[-1]
        key = (symbol, timeframe)
        fingerprint = (
            int(latest.time.timestamp()),
            latest.high,
            latest.low,
            latest.close,
            latest.tick_volume,
        )
        if self._last_sent.get(key) == fingerprint:
            return
        self._last_sent[key] = fingerprint
        await self._broadcaster.broadcast(
            {"type": "candle_update", "candle": candle_message(latest)}
        )
