"""Builds the `MarketContext` strategies and `mtf_confirm` read from raw
candles. Isolated here (not in `market_data/domain`) so that module can stay
import-light — pandas is an engine/strategy concern, not a market-data one.
"""

from __future__ import annotations

import pandas as pd

from src.market_data.domain.models import Candle
from src.strategies.domain.models import MarketContext


def build_market_context(
    symbol: str, candles_by_timeframe: dict[str, list[Candle]], spread_points: float
) -> MarketContext:
    frames = {tf: candles_to_dataframe(candles) for tf, candles in candles_by_timeframe.items()}
    return MarketContext(symbol=symbol, candles=frames, spread_points=spread_points)


def candles_to_dataframe(candles: list[Candle]) -> pd.DataFrame:
    """The one canonical Candle-list -> OHLCV-frame conversion. Public because
    the backtest's cached context builder must produce frames through the
    exact same constructor live trading uses — "what you backtest is what
    runs live" extends to DataFrame dtypes."""
    return pd.DataFrame(
        {
            "time": [c.time for c in candles],
            "open": [c.open for c in candles],
            "high": [c.high for c in candles],
            "low": [c.low for c in candles],
            "close": [c.close for c in candles],
            "tick_volume": [c.tick_volume for c in candles],
        }
    )
