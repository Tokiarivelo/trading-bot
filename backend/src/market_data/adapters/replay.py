"""MarketDataPort adapter that replays stored candle history (Phase 5:
backtesting). No network, no gateway — the whole point is to drive the exact
same engine/strategy pipeline live trading uses, deterministically, over
`CandleRepository` history.

Visibility is gated on each bar's **close** time, not its open time: at
simulated instant `t`, a timeframe's still-forming bar (opened before `t` but
closing after it) must not be visible, or higher-timeframe confirmation would
see that bar's final OHLC before it actually happened — lookahead bias. The
M5 bar that has just closed at exactly `t` is visible (its close time == t).

Bid/ask are derived from the current M5 bar's close using that bar's own
recorded `spread_points` (real historical spread, not a live quote); every
other `SymbolInfo` field is the symbol's static broker-facts config, since
there's no gateway to ask offline.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from datetime import datetime

from src.market_data.domain.models import Candle, SymbolInfo, Tick, Timeframe


@dataclass(frozen=True, kw_only=True)
class SymbolSpec:
    """Static broker facts for a symbol — sourced dynamically from the
    `symbol_specs` DB table (see `market_data/adapters/symbol_spec_repository.py`,
    populated at backfill time from the gateway's MT5 `symbol_info`), with a
    legacy `configs/symbols/<symbol>.yaml` fallback for symbols backfilled
    before that table existed."""

    point: float
    digits: int
    stops_level: int
    contract_size: float
    volume_min: float
    volume_max: float
    volume_step: float


class ReplayMarketDataPort:
    def __init__(
        self,
        symbol: str,
        candles: dict[Timeframe, list[Candle]],
        spec: SymbolSpec,
    ) -> None:
        """`candles` must be sorted oldest-first per timeframe (as returned by
        `CandleRepository.get_range`)."""
        self._symbol = symbol
        self._candles = candles
        self._spec = spec
        self._close_times = {tf: [c.close_time for c in bars] for tf, bars in candles.items()}
        self._cursor: datetime | None = None

    def advance_to(self, now: datetime) -> None:
        """Move the replay clock to `now` (the M5 bar's close time). Only
        bars whose close time is at or before `now` are visible."""
        self._cursor = now

    @property
    def current_m5_candle(self) -> Candle:
        """The M5 bar that just closed at the cursor (must call `advance_to` first)."""
        if self._cursor is None:
            raise RuntimeError("advance_to() must be called before reading the replay clock")
        bars = self._candles.get(Timeframe.M5, [])
        idx = bisect.bisect_right(self._close_times[Timeframe.M5], self._cursor) - 1
        if idx < 0:
            raise RuntimeError(f"no M5 bar closed at or before {self._cursor}")
        return bars[idx]

    async def get_candles(
        self, symbol: str, timeframe: Timeframe, count: int, before: datetime | None = None
    ) -> list[Candle]:
        if self._cursor is None:
            raise RuntimeError("advance_to() must be called before get_candles()")
        bars = self._candles.get(timeframe, [])
        close_times = self._close_times.get(timeframe, [])
        idx = bisect.bisect_right(close_times, self._cursor)
        if before is not None:
            open_times = [c.time for c in bars[:idx]]
            idx = bisect.bisect_left(open_times, before)
        return bars[max(0, idx - count) : idx]

    async def get_tick(self, symbol: str) -> Tick:
        info = await self.get_symbol_info(symbol)
        return Tick(symbol=symbol, time=self.current_m5_candle.time, bid=info.bid, ask=info.ask)

    async def get_symbol_info(self, symbol: str) -> SymbolInfo:
        candle = self.current_m5_candle
        half_spread = candle.spread_points * self._spec.point / 2
        return SymbolInfo(
            symbol=self._symbol,
            bid=candle.close - half_spread,
            ask=candle.close + half_spread,
            spread_points=candle.spread_points,
            point=self._spec.point,
            digits=self._spec.digits,
            stops_level=self._spec.stops_level,
            contract_size=self._spec.contract_size,
            volume_min=self._spec.volume_min,
            volume_max=self._spec.volume_max,
            volume_step=self._spec.volume_step,
        )
