"""Unit tests for `trend_structure_v4.py` — v2's fresh-swing entry trigger
and fixed TP_RR=2.2, but SL anchored to the RBR/DBD/RBD/DBR base that
launched the current leg instead of v1/v2's raw opposite-kind swing pivot.
Same fixtures as `test_trend_structure_v3.py` since the SL geometry is
identical; only the TP side (fixed RR here, structural nearest-old-extreme
in v3) differs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

import src.strategies.generated.trend_structure_v4_v1 as mod
from src.strategies.domain.models import Direction, MarketContext, ZoneKind

START = datetime(2026, 1, 1, tzinfo=UTC)
STEP = timedelta(minutes=5)

WARMUP_N = 126  # zone_lookback_bars(200) - skeleton(61) - hand-built leg(13)


def _bar(i: int, o: float, h: float, low: float, c: float) -> dict:
    return {
        "time": START + i * STEP,
        "open": o,
        "high": h,
        "low": low,
        "close": c,
        "tick_volume": 1000,
    }


def _skeleton(control: list[tuple[int, float]], warmup_price: float, n_warmup: int) -> list[dict]:
    """Flat warmup at `warmup_price`, then a zigzag path through `control`
    points with open==close (body 0) so `_detect_zones` classifies every bar
    here as a "base" candle — no spurious RBR/DBD legs from the smooth ramp
    itself, only real swing pivots at each control point."""
    bars = [
        _bar(i, warmup_price, warmup_price + 1.0, warmup_price - 1.0, warmup_price)
        for i in range(n_warmup)
    ]
    path: list[float] = []
    for (i0, p0), (i1, p1) in zip(control, control[1:], strict=False):
        steps = i1 - i0
        for step in range(steps):
            path.append(p0 + (p1 - p0) * step / steps)
    path.append(control[-1][1])
    for offset, price in enumerate(path):
        bars.append(_bar(n_warmup + offset, price, price + 1.0, price - 1.0, price))
    return bars


def _rally_leg(
    bars: list[dict],
    g: int,
    prices_in: list[float],
    base: tuple[float, float],
    prices_out: list[float],
) -> int:
    """Appends a genuine RBR (rally-in / base / rally-out) zone starting at
    global index `g`; returns the next free index."""
    for k in range(len(prices_in) - 1):
        o, c = prices_in[k], prices_in[k + 1]
        bars.append(_bar(g, o, max(o, c) + 0.2, min(o, c) - 0.2, c))
        g += 1
    o, c = base
    bars.append(_bar(g, o, max(o, c) + 0.3, min(o, c) - 0.2, c))
    g += 1
    for k in range(len(prices_out) - 1):
        o, c = prices_out[k], prices_out[k + 1]
        bars.append(_bar(g, o, max(o, c) + 0.2, min(o, c) - 0.2, c))
        g += 1
    return g


def _drop_leg(
    bars: list[dict],
    g: int,
    prices_in: list[float],
    base: tuple[float, float],
    prices_out: list[float],
) -> int:
    """Appends a genuine DBD (drop-in / base / drop-out) zone."""
    return _rally_leg(bars, g, prices_in, base, prices_out)


def _buy_case() -> pd.DataFrame:
    """Aligned uptrend zigzag (s1 high 90 / s2 low 80 / s3 high 96 / s4 low
    85, a genuine higher low vs s2) whose final leg (s4 -> fresh HH) is a
    hand-built RBR zone: rally-in, a one-bar base [93.6, 94.4], rally-out to
    a fresh HH at 105.3, then a 3-bar pullback so the pivot confirms exactly
    on the last bar (pivot_wing=3)."""
    control = [(0, 85.0), (15, 90.0), (30, 80.0), (45, 96.0), (60, 85.0)]
    bars = _skeleton(control, 85.0, WARMUP_N)
    g = WARMUP_N + 61
    g = _rally_leg(
        bars, g,
        prices_in=[85.0, 87.2, 89.4, 91.6, 93.8],
        base=(93.8, 94.1),
        prices_out=[94.1, 96.3, 98.5, 100.7, 102.9, 105.1],
    )
    for p in (102.0, 99.0, 96.0):
        bars.append(_bar(g, p, p + 1.0, p - 1.0, p))
        g += 1
    return pd.DataFrame(bars)


def _sell_case() -> pd.DataFrame:
    """Mirror of `_buy_case`: aligned downtrend (s1 low 110 / s2 high 120 /
    s3 low 104 / s4 high 115, a genuine lower high vs s2), final leg a
    hand-built DBD zone dropping to a fresh LL."""
    control = [(0, 115.0), (15, 110.0), (30, 120.0), (45, 104.0), (60, 115.0)]
    bars = _skeleton(control, 115.0, WARMUP_N)
    g = WARMUP_N + 61
    g = _drop_leg(
        bars, g,
        prices_in=[115.0, 112.8, 110.6, 108.4, 106.2],
        base=(106.2, 105.9),
        prices_out=[105.9, 103.7, 101.5, 99.3, 97.1, 94.9],
    )
    for p in (98.0, 101.0, 104.0):
        bars.append(_bar(g, p, p + 1.0, p - 1.0, p))
        g += 1
    return pd.DataFrame(bars)


def _no_zone_case() -> pd.DataFrame:
    """Same aligned/above-amplitude-floor uptrend shape as `_buy_case`, but
    the final leg is smooth skeleton (open==close) instead of a real RBR
    base — no zone exists for the entry to anchor SL to."""
    control = [(0, 85.0), (15, 90.0), (30, 80.0), (45, 96.0), (60, 85.0), (75, 105.0), (90, 95.0)]
    return pd.DataFrame(_skeleton(control, 85.0, 106))


# ---- evaluate: positive paths ------------------------------------------------


def test_evaluate_buys_on_fresh_hh_with_rbr_base_sl():
    strategy = mod.TrendStructureV4()
    ctx = MarketContext(symbol="XAUUSD", candles={"M5": _buy_case()}, spread_points=1.0)
    signal = strategy.evaluate(ctx)
    assert signal is not None
    assert signal.direction == Direction.BUY
    assert signal.zone is not None
    assert signal.zone.kind == ZoneKind.DEMAND
    assert signal.pattern == "RBR"
    assert signal.sl_points > 0.8
    assert signal.sl_points == pytest.approx(0.8207142857142865, rel=1e-6)
    assert signal.tp_points == pytest.approx(signal.sl_points * 2.2, rel=1e-6)
    assert "sl_zone=RBR" in signal.reason
    assert "tp=2.2xRR" in signal.reason


def test_evaluate_sells_on_fresh_ll_with_dbd_base_sl():
    strategy = mod.TrendStructureV4()
    ctx = MarketContext(symbol="XAUUSD", candles={"M5": _sell_case()}, spread_points=1.0)
    signal = strategy.evaluate(ctx)
    assert signal is not None
    assert signal.direction == Direction.SELL
    assert signal.zone is not None
    assert signal.zone.kind == ZoneKind.SUPPLY
    assert signal.pattern == "DBD"
    assert signal.tp_points == pytest.approx(signal.sl_points * 2.2, rel=1e-6)
    assert "sl_zone=DBD" in signal.reason


def test_fixed_tp_rr_matches_v1_v2():
    """The whole point of v4 vs. v3: keep v2's proven fixed TP_RR=2.2."""
    params = mod.TrendStructureV4().spec.params
    assert params["tp_rr"] == 2.2


def test_covers_all_three_symbols_matching_v1_v2():
    spec = mod.TrendStructureV4().spec
    assert set(spec.symbols) == {"XAUUSD", "XAGUSD", "BTCUSD"}
    assert spec.entry_timeframe == "M5"
    assert spec.version == 4


# ---- evaluate: negative paths -------------------------------------------------


def test_evaluate_none_without_a_launching_zone():
    """Structurally valid fresh HH, but no RBR/DBD/RBD/DBR base under the
    final leg to anchor SL to — must skip, not fall back to the raw
    swing-pivot SL v1/v2 used."""
    strategy = mod.TrendStructureV4()
    ctx = MarketContext(symbol="XAUUSD", candles={"M5": _no_zone_case()}, spread_points=1.0)
    assert strategy.evaluate(ctx) is None


def test_evaluate_none_on_short_history():
    strategy = mod.TrendStructureV4()
    ctx = MarketContext(symbol="XAUUSD", candles={"M5": _buy_case().iloc[:50]}, spread_points=1.0)
    assert strategy.evaluate(ctx) is None
