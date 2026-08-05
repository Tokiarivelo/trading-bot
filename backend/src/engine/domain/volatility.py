"""Volatility-regime classification for engine-level SL/TP and exit adaptation.

Ranks the current ATR reading against its own trailing history (percentile
rank) to bucket the market into a `VolatilityRegime`. A later phase (Phase B)
uses that regime to scale SL/TP distance and drive position-management rules
(chandelier exits, profit locking) in `RiskManager`/`PositionManager` — this
module only classifies, it never touches trade state.

No I/O — pure functions over OHLC/ATR arrays, matching this module's
hexagonal `domain/` placement. `VolatilityConfig` mirrors
`configs/volatility.yaml` (see `shared.config.loaders.load_volatility_config`).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import pandas as pd

from src.engine.domain.zone_detection import atr

DEFAULT_ATR_PERIOD = 14
DEFAULT_REGIME_LOOKBACK_BARS = 100
DEFAULT_LOW_PERCENTILE = 20.0
DEFAULT_HIGH_PERCENTILE = 70.0
DEFAULT_EXTREME_PERCENTILE = 90.0


class VolatilityRegime(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    EXTREME = "extreme"


@dataclass(frozen=True, kw_only=True)
class VolatilityConfig:
    """Mirrors `configs/volatility.yaml`. Classifier fields (`atr_period`
    through `extreme_percentile`) are consumed by this module; the
    SL/TP-multiplier and position-management fields are read-only here — a
    later phase wires them into `RiskManager`/`PositionManager`."""

    atr_period: int = DEFAULT_ATR_PERIOD
    regime_lookback_bars: int = DEFAULT_REGIME_LOOKBACK_BARS
    low_percentile: float = DEFAULT_LOW_PERCENTILE
    high_percentile: float = DEFAULT_HIGH_PERCENTILE
    extreme_percentile: float = DEFAULT_EXTREME_PERCENTILE
    sl_multiplier_low: float = 0.85
    sl_multiplier_normal: float = 1.0
    sl_multiplier_high: float = 1.3
    tp_multiplier_low: float = 0.85
    tp_multiplier_normal: float = 1.0
    tp_multiplier_high: float = 1.3
    extreme_close_if_losing: bool = True
    extreme_profit_lock_r_mult: float = 0.5
    chandelier_atr_mult: float = 2.0
    chandelier_min_profit_r: float = 1.0


def _percentile_rank(window: np.ndarray, value: float) -> float:
    """Percentile rank of `value` against `window` (0-100) using the
    tie-aware "average rank" convention: ties count as half a step rather
    than a full step. This matters a lot here — a naive "fraction at or
    below `value`" definition pins a perfectly flat/calm window (a common,
    unremarkable market state) to the 100th percentile purely because every
    trailing reading ties the current one, which would misclassify ordinary
    calm markets as EXTREME. Averaging ties instead puts a flat window at
    ~50 (NORMAL), which is the sane answer."""
    if window.size == 0:
        return np.nan
    below = float(np.sum(window < value))
    tied = float(np.sum(window == value))
    return (below + 0.5 * tied) / window.size * 100.0


def _classify(
    percentile: float,
    *,
    low_percentile: float,
    high_percentile: float,
    extreme_percentile: float,
) -> VolatilityRegime:
    if np.isnan(percentile):
        return VolatilityRegime.NORMAL
    if percentile > extreme_percentile:
        return VolatilityRegime.EXTREME
    if percentile > high_percentile:
        return VolatilityRegime.HIGH
    if percentile < low_percentile:
        return VolatilityRegime.LOW
    return VolatilityRegime.NORMAL


def classify_volatility_regime(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    *,
    atr_period: int = DEFAULT_ATR_PERIOD,
    regime_lookback_bars: int = DEFAULT_REGIME_LOOKBACK_BARS,
    low_percentile: float = DEFAULT_LOW_PERCENTILE,
    high_percentile: float = DEFAULT_HIGH_PERCENTILE,
    extreme_percentile: float = DEFAULT_EXTREME_PERCENTILE,
) -> pd.Series:
    """Vectorized regime classification aligned to the OHLC arrays, for
    backtest use. For each bar, ranks that bar's ATR against the trailing
    `regime_lookback_bars` ATR readings (excluding the current bar) and
    buckets the percentile into LOW/NORMAL/HIGH/EXTREME. Bars without enough
    ATR or lookback history (warm-up window) default to NORMAL rather than
    raising, matching the "insufficient history" guard used by
    `zone_detection.detect_bases`."""
    atr_values = atr(highs, lows, closes, atr_period)
    n = len(atr_values)
    regimes = [VolatilityRegime.NORMAL] * n
    atr_arr = atr_values.to_numpy()

    for i in range(n):
        current = atr_arr[i]
        if np.isnan(current):
            continue
        window_start = max(0, i - regime_lookback_bars)
        window = atr_arr[window_start:i]
        window = window[~np.isnan(window)]
        if window.size == 0:
            continue
        percentile = _percentile_rank(window, current)
        regimes[i] = _classify(
            percentile,
            low_percentile=low_percentile,
            high_percentile=high_percentile,
            extreme_percentile=extreme_percentile,
        )

    return pd.Series(regimes, index=atr_values.index)


def latest_volatility_regime(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    *,
    atr_period: int = DEFAULT_ATR_PERIOD,
    regime_lookback_bars: int = DEFAULT_REGIME_LOOKBACK_BARS,
    low_percentile: float = DEFAULT_LOW_PERCENTILE,
    high_percentile: float = DEFAULT_HIGH_PERCENTILE,
    extreme_percentile: float = DEFAULT_EXTREME_PERCENTILE,
) -> tuple[VolatilityRegime, float, float]:
    """Convenience "latest regime" read for live use (`RiskManager` /
    `PositionManager` in a later phase): classifies only the most recent bar
    and also returns its percentile rank and raw ATR value. Returns
    `(VolatilityRegime.NORMAL, nan, nan)` when there isn't enough history yet
    instead of raising."""
    atr_values = atr(highs, lows, closes, atr_period)
    valid_atr = atr_values.dropna()
    if valid_atr.empty:
        return VolatilityRegime.NORMAL, float("nan"), float("nan")

    atr_arr = atr_values.to_numpy()
    current = float(atr_arr[-1])
    if np.isnan(current):
        return VolatilityRegime.NORMAL, float("nan"), float("nan")

    window_start = max(0, len(atr_arr) - 1 - regime_lookback_bars)
    window = atr_arr[window_start : len(atr_arr) - 1]
    window = window[~np.isnan(window)]
    if window.size == 0:
        return VolatilityRegime.NORMAL, float("nan"), current

    percentile = _percentile_rank(window, current)
    regime = _classify(
        percentile,
        low_percentile=low_percentile,
        high_percentile=high_percentile,
        extreme_percentile=extreme_percentile,
    )
    return regime, percentile, current
