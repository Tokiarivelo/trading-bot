"""Unit tests for `trend_structure_v5.py` — v4's fresh-swing trigger and
zone-anchored SL, plus an RSI(14) momentum-confirmation gate (RSI>50 for a
buy, RSI<50 for a sell). Same fixtures as `test_trend_structure_v4.py`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

import src.strategies.generated.trend_structure_v5_v1 as mod
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
    return _rally_leg(bars, g, prices_in, base, prices_out)


def _buy_case() -> pd.DataFrame:
    """Aligned uptrend zigzag whose final leg is a hand-built RBR zone with
    a strong rally-out — RSI(14) reads well above 50 at the entry bar."""
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
    """Mirror of `_buy_case`: aligned downtrend, final leg a hand-built DBD
    zone with a strong drop-out — RSI(14) reads well below 50 at entry."""
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
    control = [(0, 85.0), (15, 90.0), (30, 80.0), (45, 96.0), (60, 85.0), (75, 105.0), (90, 95.0)]
    return pd.DataFrame(_skeleton(control, 85.0, 106))


def _weak_momentum_buy_case() -> pd.DataFrame:
    """Same structurally-valid fresh-HH/RBR setup as `_buy_case`, but a much
    steeper 3-bar pullback after the rally-out (-15 per bar instead of -3)
    pulls RSI(14) at the entry bar down to ~23, well below the 50 floor —
    must be skipped even though structure and zone are both otherwise
    valid."""
    control = [(0, 85.0), (15, 90.0), (30, 80.0), (45, 96.0), (60, 85.0)]
    bars = _skeleton(control, 85.0, WARMUP_N)
    g = WARMUP_N + 61
    g = _rally_leg(
        bars, g,
        prices_in=[85.0, 87.2, 89.4, 91.6, 93.8],
        base=(93.8, 94.1),
        prices_out=[94.1, 96.3, 98.5, 100.7, 102.9, 105.1],
    )
    price = 105.1
    for _ in range(3):
        price -= 15.0
        bars.append(_bar(g, price + 15.0, price + 15.0, price, price))
        g += 1
    return pd.DataFrame(bars)


# ---- evaluate: positive paths ------------------------------------------------


def test_evaluate_buys_on_fresh_hh_with_rsi_confirmed():
    strategy = mod.TrendStructureV5()
    ctx = MarketContext(symbol="XAUUSD", candles={"M5": _buy_case()}, spread_points=1.0)
    signal = strategy.evaluate(ctx)
    assert signal is not None
    assert signal.direction == Direction.BUY
    assert signal.zone is not None
    assert signal.zone.kind == ZoneKind.DEMAND
    assert signal.pattern == "RBR"
    assert signal.tp_points == pytest.approx(signal.sl_points * 2.2, rel=1e-6)
    assert "rsi14=" in signal.reason
    assert "confirmed" in signal.reason


def test_evaluate_sells_on_fresh_ll_with_rsi_confirmed():
    strategy = mod.TrendStructureV5()
    ctx = MarketContext(symbol="XAUUSD", candles={"M5": _sell_case()}, spread_points=1.0)
    signal = strategy.evaluate(ctx)
    assert signal is not None
    assert signal.direction == Direction.SELL
    assert signal.zone is not None
    assert signal.zone.kind == ZoneKind.SUPPLY
    assert signal.pattern == "DBD"


def test_rsi_gate_params_present():
    params = mod.TrendStructureV5().spec.params
    assert params["rsi_period"] == 14
    assert params["rsi_buy_min"] == 50.0
    assert params["rsi_sell_max"] == 50.0
    assert params["tp_rr"] == 2.2


def test_covers_all_three_symbols_matching_v4():
    spec = mod.TrendStructureV5().spec
    assert set(spec.symbols) == {"XAUUSD", "XAGUSD", "BTCUSD"}
    assert spec.entry_timeframe == "M5"
    assert spec.version == 5


# ---- evaluate: negative paths -------------------------------------------------


def test_evaluate_none_without_a_launching_zone():
    strategy = mod.TrendStructureV5()
    ctx = MarketContext(symbol="XAUUSD", candles={"M5": _no_zone_case()}, spread_points=1.0)
    assert strategy.evaluate(ctx) is None


def test_evaluate_none_on_short_history():
    strategy = mod.TrendStructureV5()
    ctx = MarketContext(symbol="XAUUSD", candles={"M5": _buy_case().iloc[:50]}, spread_points=1.0)
    assert strategy.evaluate(ctx) is None


def test_evaluate_none_when_rsi_not_confirmed():
    """Structurally valid fresh HH with a real RBR base, but RSI(14) at the
    entry bar isn't above 50 — the whole point of v5 vs v4."""
    strategy = mod.TrendStructureV5()
    ctx = MarketContext(
        symbol="XAUUSD", candles={"M5": _weak_momentum_buy_case()}, spread_points=1.0
    )
    assert strategy.evaluate(ctx) is None
