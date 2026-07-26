from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from src.strategies.domain.models import Direction, MarketContext
from src.strategies.generated.trend_structure_v7_v1 import (
    PIVOT_WING,
    TP_RR_BASE,
    TP_RR_TIER2,
    TP_RR_TIER3,
    TrendStructureV7,
    _adx,
    _confluence_votes,
    _rsi,
    _true_range_values,
)

# Same control points as trend_structure_v2's test fixture, since v7 reuses
# v2's entry trigger byte-for-byte -- these must behave identically.
ALIGNED_BUY = [
    (0, 85.0),
    (15, 90.0),
    (30, 80.0),
    (45, 96.0),
    (60, 85.0),
    (75, 105.0),
    (90, 95.0),
]

UNALIGNED_BUY = [
    (0, 85.0),
    (15, 90.0),
    (30, 80.0),
    (45, 96.0),
    (60, 75.0),
    (75, 105.0),
    (90, 95.0),
]

SMALL_AMPLITUDE_BUY = [
    (0, 85.0),
    (15, 90.0),
    (30, 80.0),
    (45, 96.0),
    (60, 85.0),
    (75, 96.3),
    (90, 95.0),
]

ALIGNED_SELL = [
    (0, 115.0),
    (15, 110.0),
    (30, 120.0),
    (45, 104.0),
    (60, 115.0),
    (75, 95.0),
    (90, 105.0),
]


def _make_path(control_points: list[tuple[int, float]]) -> list[float]:
    path: list[float] = []
    for (i0, p0), (i1, p1) in zip(control_points, control_points[1:], strict=False):
        steps = i1 - i0
        for step in range(steps):
            path.append(p0 + (p1 - p0) * step / steps)
    path.append(control_points[-1][1])
    return path


def _make_ctx(control_points: list[tuple[int, float]], bars: int) -> MarketContext:
    prices = _make_path(control_points)[:bars]
    start = datetime(2026, 1, 1)
    df = pd.DataFrame(
        {
            "time": [start + timedelta(minutes=5 * i) for i in range(len(prices))],
            "open": prices,
            "high": [p + 1.0 for p in prices],
            "low": [p - 1.0 for p in prices],
            "close": prices,
            "tick_volume": [100] * len(prices),
        }
    )
    return MarketContext(symbol="XAUUSD", candles={"M5": df}, spread_points=25.0)


def _confirm_length(pivot_index: int) -> int:
    return pivot_index + PIVOT_WING + 1


def test_buy_signal_when_aligned_and_above_amplitude_floor():
    ctx = _make_ctx(ALIGNED_BUY, _confirm_length(75))
    signal = TrendStructureV7().evaluate(ctx)

    assert signal is not None
    assert signal.direction is Direction.BUY
    assert signal.sl_points > 0
    # tp_rr is tiered by confluence but never drops below v2's own base
    assert signal.tp_points >= signal.sl_points * TP_RR_BASE
    assert 0.6 <= signal.confidence <= 0.9


def test_no_signal_when_prior_low_is_not_higher():
    ctx = _make_ctx(UNALIGNED_BUY, _confirm_length(75))
    assert TrendStructureV7().evaluate(ctx) is None


def test_no_signal_when_swing_amplitude_below_atr_floor():
    ctx = _make_ctx(SMALL_AMPLITUDE_BUY, _confirm_length(75))
    assert TrendStructureV7().evaluate(ctx) is None


def test_sell_signal_when_aligned_and_above_amplitude_floor():
    ctx = _make_ctx(ALIGNED_SELL, _confirm_length(75))
    signal = TrendStructureV7().evaluate(ctx)

    assert signal is not None
    assert signal.direction is Direction.SELL
    assert signal.tp_points >= signal.sl_points * TP_RR_BASE


def test_no_signal_with_insufficient_history():
    ctx = _make_ctx(ALIGNED_BUY, 20)
    assert TrendStructureV7().evaluate(ctx) is None


def test_spec_covers_all_three_symbols():
    spec = TrendStructureV7().spec
    assert set(spec.symbols) == {"XAUUSD", "XAGUSD", "BTCUSD"}
    assert spec.entry_timeframe == "M5"
    assert spec.version == 7


def test_confluence_tp_rr_matches_vote_count():
    # every entry v2 would take, v7 also takes -- and the reason string
    # records exactly which tier was applied and why. tp_points includes a
    # spread term (same formula as the DB-active trend_structure_v2), so
    # divide it back out before checking against the tier constants.
    ctx = _make_ctx(ALIGNED_BUY, _confirm_length(75))
    signal = TrendStructureV7().evaluate(ctx)
    assert signal is not None
    spread_price = ctx.spread_points * 0.01
    rr = signal.tp_points / (signal.sl_points + spread_price)
    assert rr in (TP_RR_BASE, TP_RR_TIER2, TP_RR_TIER3)
    assert f"tp_rr={rr}" in signal.reason


def test_confluence_votes_all_true_on_strong_uptrend():
    n = 80
    closes = pd.Series(np.linspace(100.0, 200.0, n))
    highs = closes + 1.0
    lows = closes - 1.0
    tr = pd.Series(_true_range_values(highs.to_numpy(), lows.to_numpy(), closes.to_numpy()))

    rsi_ok, adx_ok, ema_ok = _confluence_votes(closes, highs, lows, tr, Direction.BUY)

    assert rsi_ok is True
    assert ema_ok is True
    assert adx_ok is True


def test_confluence_votes_default_false_on_flat_series():
    n = 80
    closes = pd.Series([100.0] * n)
    highs = closes + 1.0
    lows = closes - 1.0
    tr = pd.Series(_true_range_values(highs.to_numpy(), lows.to_numpy(), closes.to_numpy()))

    rsi_ok, adx_ok, ema_ok = _confluence_votes(closes, highs, lows, tr, Direction.BUY)

    assert rsi_ok is False
    assert adx_ok is False
    assert ema_ok is False


def test_rsi_and_adx_return_nan_before_warmup():
    closes = pd.Series(np.linspace(100.0, 110.0, 5))
    assert _rsi(closes, 14).iloc[-1] != _rsi(closes, 14).iloc[-1]  # NaN != NaN

    highs = closes + 1.0
    lows = closes - 1.0
    tr = pd.Series(_true_range_values(highs.to_numpy(), lows.to_numpy(), closes.to_numpy()))
    adx_val = _adx(highs, lows, tr, 14).iloc[-1]
    assert adx_val != adx_val  # NaN
