"""Candle streaming: poll the gateway on bar boundaries, emit CandleClosed.

This is the engine's clock (M5 entries, H1/H4/D1 confirmations) plus any
finer timeframe configured for charting (e.g. M1). Every configured
timeframe closes on the finest one's boundaries, so one wake-up shortly
after each such close covers everything — see `_seconds_until_next_poll`.
Every closed bar is also persisted, so history accumulates for backtests and
AI snapshots as a side effect of streaming.

Polling always covers `configs/app.yaml: symbols` (the engine's traded
universe); `watch`/`unwatch` extend that set for symbols a chart is
browsing on demand (see `market_data.api.ws`), so any symbol currently
open on a chart gets live `candle_closed` updates too, not just the three
the bot actually trades.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime

from src.market_data.adapters.candle_repository import CandleRepository
from src.market_data.domain.models import Candle, MarketDataUnavailable, Timeframe
from src.market_data.ports.broadcast import MarketBroadcastPort
from src.market_data.ports.market_data import MarketDataPort
from src.shared.events.bus import EventBus
from src.shared.events.definitions import CandleClosed

logger = logging.getLogger(__name__)

# Bars fetched per poll: enough to bridge short gateway outages without
# re-downloading history (backfill handles that).
_POLL_LOOKBACK = 20
_BOUNDARY_GRACE_S = 2.0


class CandleStreamService:
    def __init__(
        self,
        market_data: MarketDataPort,
        repository: CandleRepository,
        event_bus: EventBus,
        broadcaster: MarketBroadcastPort,
        symbols: list[str],
        timeframes: list[Timeframe],
    ) -> None:
        self._market_data = market_data
        self._repository = repository
        self._event_bus = event_bus
        self._broadcaster = broadcaster
        self._symbols = symbols
        self._timeframes = timeframes
        self._last_emitted: dict[tuple[str, Timeframe], datetime] = {}
        self._task: asyncio.Task[None] | None = None
        self._gateway_ok = True
        # Ref-counted: several chart subscribers can watch the same ad-hoc
        # symbol at once (e.g. two browser tabs), so it stays active until
        # all of them unwatch it. Configured symbols are always active and
        # never go through this map.
        self._extra_refcounts: dict[str, int] = {}

    @property
    def active_symbols(self) -> list[str]:
        """Configured symbols plus any ad-hoc symbols currently watched."""
        return [*self._symbols, *self._extra_refcounts]

    def watch(self, symbol: str) -> None:
        """Start streaming `symbol` on demand (chart browsing a non-configured
        symbol). No-op for symbols already in `configs/app.yaml: symbols` —
        those are always active."""
        if symbol in self._symbols:
            return
        if self._extra_refcounts.get(symbol, 0) == 0:
            logger.info("candle stream: now watching ad-hoc symbol %s", symbol)
        self._extra_refcounts[symbol] = self._extra_refcounts.get(symbol, 0) + 1

    def unwatch(self, symbol: str) -> None:
        """Stop streaming `symbol` once nothing is watching it anymore."""
        if symbol not in self._extra_refcounts:
            return
        self._extra_refcounts[symbol] -= 1
        if self._extra_refcounts[symbol] > 0:
            return
        del self._extra_refcounts[symbol]
        logger.info("candle stream: no longer watching ad-hoc symbol %s", symbol)
        for timeframe in self._timeframes:
            self._last_emitted.pop((symbol, timeframe), None)

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="candle-stream")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while True:
            try:
                await self.poll_once()
                if not self._gateway_ok:
                    self._gateway_ok = True
                    logger.info("gateway reachable again — candle stream resumed")
            except MarketDataUnavailable as exc:
                if self._gateway_ok:
                    self._gateway_ok = False
                    logger.warning("candle stream paused, gateway unavailable: %s", exc)
            except Exception:
                logger.exception("candle stream poll failed")
            await asyncio.sleep(self._seconds_until_next_poll())

    async def poll_once(self, now: datetime | None = None) -> list[Candle]:
        """Fetch, persist, and emit newly closed bars. Returns what was emitted."""
        now = now or datetime.now(UTC)
        emitted: list[Candle] = []
        for symbol in self.active_symbols:
            for timeframe in self._timeframes:
                key = (symbol, timeframe)
                if self._last_emitted.get(key) == timeframe.last_closed_open(now):
                    continue  # already saw the latest closed bar of this timeframe
                candles = await self._market_data.get_candles(symbol, timeframe, _POLL_LOOKBACK)
                closed = [c for c in candles if c.is_closed(now)]
                if not closed:
                    continue
                await asyncio.to_thread(self._repository.upsert_many, closed)
                previous = self._last_emitted.get(key)
                self._last_emitted[key] = closed[-1].time
                if previous is None:
                    continue  # startup baseline
                # Emit every bar that closed since the last poll, not just the
                # newest — with a finer timeframe like M1 in the mix, more than
                # one bar can close between two polls and none should be lost.
                new_bars = [c for c in closed if c.time > previous]
                for candle in new_bars:
                    logger.info(
                        "candle closed %s %s @ %s close=%s spread=%s",
                        symbol,
                        timeframe.value,
                        candle.time.isoformat(),
                        candle.close,
                        candle.spread_points,
                    )
                    await self._event_bus.publish(
                        CandleClosed(symbol=symbol, timeframe=timeframe.value)
                    )
                    await self._broadcaster.broadcast(
                        {"type": "candle_closed", "candle": candle_message(candle)}
                    )
                    emitted.append(candle)
        return emitted

    def _seconds_until_next_poll(self, now: datetime | None = None) -> float:
        now = now or datetime.now(UTC)
        finest = min(tf.seconds for tf in self._timeframes)
        until_boundary = finest - (now.timestamp() % finest)
        return max(until_boundary + _BOUNDARY_GRACE_S, 5.0)


def candle_message(candle: Candle) -> dict[str, float | int | str]:
    """Wire shape for WS/REST — `time` in epoch seconds (lightweight-charts native)."""
    return {
        "symbol": candle.symbol,
        "timeframe": candle.timeframe.value,
        "time": int(candle.time.timestamp()),
        "open": candle.open,
        "high": candle.high,
        "low": candle.low,
        "close": candle.close,
        "tick_volume": candle.tick_volume,
        "spread_points": candle.spread_points,
    }
