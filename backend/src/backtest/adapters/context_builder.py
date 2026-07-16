"""Backtest-only `MarketContext` builder that slices pre-built DataFrames.

`TradeEngine._try_enter` builds a fresh `MarketContext` on every entry
evaluation. Live that happens once per M5 close and the cost is irrelevant;
in a backtest it happens tens of thousands of times, and rebuilding three
~200-row DataFrames from `Candle` lists dominated the whole replay loop
(~3ms of the ~6ms per-bar budget in profiling).

Replay history is immutable, so this builder constructs ONE master frame per
timeframe (lazily, via the exact same `candles_to_dataframe` constructor the
live `build_market_context` uses — same columns, same dtypes) and then serves
each request as a positional slice of it. With pandas copy-on-write a slice
shares the master's column buffers, so per-request cost is O(1) bookkeeping
instead of O(bars) construction, and a strategy mutating its slice can never
corrupt the master.

Correctness invariant: for any candle list the engine fetched from
`ReplayMarketDataPort.get_candles`, `slice.reset_index(drop=True)` is
value-identical to `candles_to_dataframe(list)` — the list is itself a
contiguous slice of the same replay history the master frame was built from.
A list whose first candle isn't found in the master (defensive: shouldn't
happen inside a backtest) falls back to plain construction.
"""

from __future__ import annotations

import pandas as pd

from src.engine.application.context import candles_to_dataframe
from src.market_data.domain.models import Candle, Timeframe
from src.strategies.domain.models import MarketContext


class CachedContextBuilder:
    def __init__(self, candles: dict[Timeframe, list[Candle]]) -> None:
        """`candles` is the replay's full per-timeframe history (sorted
        oldest-first), exactly what `ReplayMarketDataPort` serves slices of."""
        self._history: dict[str, list[Candle]] = {
            tf.value: bars for tf, bars in candles.items()
        }
        self._frames: dict[str, pd.DataFrame] = {}
        self._positions: dict[str, dict[object, int]] = {}

    def __call__(
        self, symbol: str, candles_by_timeframe: dict[str, list[Candle]], spread_points: float
    ) -> MarketContext:
        frames = {
            tf: self._frame_for(tf, candles) for tf, candles in candles_by_timeframe.items()
        }
        return MarketContext(symbol=symbol, candles=frames, spread_points=spread_points)

    def _frame_for(self, timeframe: str, candles: list[Candle]) -> pd.DataFrame:
        if not candles or timeframe not in self._history:
            return candles_to_dataframe(candles)
        positions = self._positions.get(timeframe)
        if positions is None:
            positions = {c.time: i for i, c in enumerate(self._history[timeframe])}
            self._positions[timeframe] = positions
        start = positions.get(candles[0].time)
        if start is None:
            return candles_to_dataframe(candles)
        master = self._frames.get(timeframe)
        if master is None:
            master = candles_to_dataframe(self._history[timeframe])
            self._frames[timeframe] = master
        return master.iloc[start : start + len(candles)].reset_index(drop=True)
