"""Unit tests for the engine-side volatility-regime classifier used (in a
later phase) to adapt scalp bots' SL/TP and exits during volatile markets."""

from __future__ import annotations

import numpy as np

from src.engine.domain.volatility import (
    VolatilityRegime,
    _classify,
    _percentile_rank,
    classify_volatility_regime,
    latest_volatility_regime,
)


def _flat_bars(n: int, *, width: float, base: float = 100.0):
    """`n` bars each with a fixed high-low range `width`, flat close, so the
    resulting true range (and therefore ATR) is a constant `width`."""
    highs = np.full(n, base + width / 2)
    lows = np.full(n, base - width / 2)
    closes = np.full(n, base)
    return highs, lows, closes


def _concat(*parts):
    highs = np.concatenate([p[0] for p in parts])
    lows = np.concatenate([p[1] for p in parts])
    closes = np.concatenate([p[2] for p in parts])
    return highs, lows, closes


def test_classify_boundaries_match_spec():
    # <20th percentile -> LOW, 20-70 -> NORMAL, 70-90 -> HIGH, >90 -> EXTREME
    kwargs = dict(low_percentile=20.0, high_percentile=70.0, extreme_percentile=90.0)
    assert _classify(19.9, **kwargs) == VolatilityRegime.LOW
    assert _classify(20.0, **kwargs) == VolatilityRegime.NORMAL
    assert _classify(69.9, **kwargs) == VolatilityRegime.NORMAL
    assert _classify(70.1, **kwargs) == VolatilityRegime.HIGH
    assert _classify(90.0, **kwargs) == VolatilityRegime.HIGH
    assert _classify(90.1, **kwargs) == VolatilityRegime.EXTREME
    assert _classify(float("nan"), **kwargs) == VolatilityRegime.NORMAL


def test_percentile_rank_of_max_and_min_of_window():
    window = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    assert _percentile_rank(window, 5.0) == 90.0  # tied with itself -> half step
    assert _percentile_rank(window, 0.5) == 0.0
    assert _percentile_rank(window, 3.0) == 50.0  # 2 below, tied with itself
    assert np.isnan(_percentile_rank(np.array([]), 1.0))


def test_percentile_rank_of_flat_window_is_not_pinned_to_extreme():
    # A window entirely tied with the current value (a calm, unremarkable
    # market) must land near the middle (NORMAL), not the 100th percentile.
    window = np.full(50, 0.4)
    assert _percentile_rank(window, 0.4) == 50.0


def test_regime_flips_to_extreme_during_volatility_burst_and_reverts():
    # 150 tight bars to build a stable baseline ATR history, a 20-bar burst
    # of 10x-wider candles, then a long tight patch again.
    baseline = _flat_bars(150, width=0.4)
    burst = _flat_bars(20, width=5.0, base=100.0)
    calm_after = _flat_bars(130, width=0.4)
    highs, lows, closes = _concat(baseline, burst, calm_after)

    regimes = classify_volatility_regime(highs, lows, closes)

    # Well into the burst (ATR has had a full 14-period window of wide
    # candles to ramp up), the regime must be HIGH or EXTREME.
    burst_confirmed_idx = 150 + 19  # last burst bar
    assert regimes.iloc[burst_confirmed_idx] in (VolatilityRegime.HIGH, VolatilityRegime.EXTREME)

    # Deep into the calm patch after the burst has fully rolled out of the
    # ATR window, the regime must have come back down off EXTREME/HIGH.
    reverted_idx = len(regimes) - 1
    assert regimes.iloc[reverted_idx] not in (VolatilityRegime.HIGH, VolatilityRegime.EXTREME)


def test_regime_is_low_when_calm_relative_to_volatile_history():
    # A long volatile baseline followed by a much calmer patch: the calm
    # patch should rank low against the volatile trailing history.
    volatile = _flat_bars(150, width=3.0)
    calm = _flat_bars(30, width=0.05)
    highs, lows, closes = _concat(volatile, calm)

    regimes = classify_volatility_regime(highs, lows, closes)

    assert regimes.iloc[-1] == VolatilityRegime.LOW


def test_insufficient_history_returns_normal_not_raise():
    highs, lows, closes = _flat_bars(5, width=0.4)

    regimes = classify_volatility_regime(highs, lows, closes, atr_period=14)

    assert len(regimes) == 5
    assert all(r == VolatilityRegime.NORMAL for r in regimes)

    regime, percentile, atr_value = latest_volatility_regime(highs, lows, closes, atr_period=14)
    assert regime == VolatilityRegime.NORMAL
    assert np.isnan(percentile)
    assert np.isnan(atr_value)


def test_latest_regime_matches_last_element_of_vectorized_series():
    baseline = _flat_bars(150, width=0.4)
    burst = _flat_bars(20, width=5.0)
    highs, lows, closes = _concat(baseline, burst)

    regimes = classify_volatility_regime(highs, lows, closes)
    regime, percentile, atr_value = latest_volatility_regime(highs, lows, closes)

    assert regime == regimes.iloc[-1]
    assert not np.isnan(percentile)
    assert not np.isnan(atr_value)
    assert atr_value > 0.4  # wide burst pulled the trailing ATR up
