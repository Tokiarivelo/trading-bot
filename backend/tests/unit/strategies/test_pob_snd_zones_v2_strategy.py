"""Unit tests for the refined `pob_snd_zones_vix75_v2.py` and the FX flavor
`pob_snd_zones_fx_v1.py` — the v2 refinement toggles (continuation-only,
stricter MTF, trend alignment, rejection close) on top of the zone logic
already covered by `test_pob_snd_zones_strategy.py` (v1)."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pandas as pd

from src.strategies.domain.models import Direction, MarketContext, ZoneKind

_GENERATED = Path(__file__).resolve().parents[3] / "src" / "strategies" / "generated"

START = datetime(2026, 1, 1, tzinfo=UTC)
STEP = timedelta(minutes=5)


def _load(file_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        file_name.removesuffix(".py") + "_under_test", _GENERATED / file_name
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v2 = _load("pob_snd_zones_vix75_v2.py")
fx = _load("pob_snd_zones_fx_v1.py")


def _bar(i: int, o: float, h: float, low: float, c: float) -> dict:
    return {
        "time": START + i * STEP,
        "open": o,
        "high": h,
        "low": low,
        "close": c,
        "tick_volume": 1000,
    }


def _demand_retest_bars() -> list[dict]:
    """RBR demand zone at [103.6, 104.4] with a first retest + bullish
    engulfing on the last bar — same scenario as the v1 tests."""
    bars = [_bar(i, 100.0, 100.6, 99.4, 100.4) for i in range(34)]
    i = len(bars)
    bars.append(_bar(i, 100.0, 104.2, 100.0, 104.0))
    bars.append(_bar(i + 1, 104.0, 104.4, 103.6, 104.1))
    bars.append(_bar(i + 2, 104.1, 108.3, 104.0, 108.0))
    bars.append(_bar(i + 3, 108.2, 108.3, 107.4, 107.7))
    bars.append(_bar(i + 4, 107.7, 107.8, 106.9, 107.2))
    bars.append(_bar(i + 5, 107.2, 107.3, 106.4, 106.7))
    bars.append(_bar(i + 6, 106.7, 106.8, 106.0, 106.2))
    bars.append(_bar(i + 7, 106.1, 107.0, 104.2, 106.9))
    return bars


def _dbr_retest_bars() -> list[dict]:
    """DBR (drop-base-rally) demand zone — a reversal-turn entry point, which
    continuation_only must skip. Zone band [95.6, 96.4]."""
    bars = [_bar(i, 100.0, 100.6, 99.4, 100.4) for i in range(34)]
    i = len(bars)
    bars.append(_bar(i, 100.4, 100.4, 96.2, 96.4))  # drop in
    bars.append(_bar(i + 1, 96.4, 96.4, 95.6, 96.0))  # base
    bars.append(_bar(i + 2, 96.0, 100.3, 95.9, 100.1))  # rally out
    bars.append(_bar(i + 3, 100.1, 100.4, 99.6, 99.9))  # drift, base-class
    bars.append(_bar(i + 4, 99.9, 100.0, 99.2, 99.5))
    bars.append(_bar(i + 5, 99.5, 99.6, 98.8, 99.1))
    bars.append(_bar(i + 6, 99.1, 99.2, 98.4, 98.7))
    # Retest: wick tags the band (low 96.3 ≤ 96.4), bullish engulfing close.
    bars.append(_bar(i + 7, 98.6, 99.5, 96.3, 99.4))
    return bars


def _mtf_bullish(step: timedelta = timedelta(minutes=15)) -> pd.DataFrame:
    bars = []
    for i in range(8):
        b = _bar(i, 100.0, 100.6, 99.4, 100.4)
        b["time"] = START + i * step
        bars.append(b)
    b1 = _bar(8, 100.4, 100.5, 99.8, 99.9)
    b2 = _bar(9, 99.8, 101.2, 99.7, 101.0)
    b1["time"] = START + 8 * step
    b2["time"] = START + 9 * step
    return pd.DataFrame(bars + [b1, b2])


def _htf_uptrend(n: int = 60, step: timedelta = timedelta(hours=1)) -> pd.DataFrame:
    """H1 frame trending up so close > EMA(50) — passes the trend gate, and
    its last bars are strong up-bodies so the MTF confirmation passes too."""
    bars = []
    for i in range(n):
        o = 100.0 + i * 0.5
        b = {"time": START + i * step, "open": o, "high": o + 0.6, "low": o - 0.1,
             "close": o + 0.5, "tick_volume": 1000}
        bars.append(b)
    return pd.DataFrame(bars)


def _htf_downtrend(n: int = 60, step: timedelta = timedelta(hours=1)) -> pd.DataFrame:
    bars = []
    for i in range(n):
        o = 200.0 - i * 0.5
        b = {"time": START + i * step, "open": o, "high": o + 0.1, "low": o - 0.6,
             "close": o - 0.5, "tick_volume": 1000}
        bars.append(b)
    return pd.DataFrame(bars)


# ---- v2 (VIX75): continuation-only + min_confirmations=2 defaults ----------


def test_v2_defaults_are_the_refined_ones():
    params = v2.PobSndZonesVix75().spec.params
    assert params["continuation_only"] is True
    assert params["min_confirmations"] == 2
    assert params["require_engulfing_entry"] is False
    assert params["htf_trend_ema_period"] == 0


def test_v2_still_buys_rbr_retest_with_both_confirmations():
    ctx = MarketContext(
        symbol="Volatility 75 Index",
        candles={
            "M5": pd.DataFrame(_demand_retest_bars()),
            "M15": _mtf_bullish(),
            "M30": _mtf_bullish(timedelta(minutes=30)),
        },
        spread_points=1.0,
    )
    signal = v2.PobSndZonesVix75().evaluate(ctx)
    assert signal is not None
    assert signal.direction == Direction.BUY
    assert "RBR-retest" in signal.reason


def test_v2_vetoes_with_single_confirmation():
    """min_confirmations=2: one confirming TF is no longer enough."""
    ctx = MarketContext(
        symbol="Volatility 75 Index",
        candles={
            "M5": pd.DataFrame(_demand_retest_bars()),
            "M15": _mtf_bullish(),
        },
        spread_points=1.0,
    )
    assert v2.PobSndZonesVix75().evaluate(ctx) is None


def test_v2_skips_reversal_turn_zones():
    """continuation_only: a valid DBR retest must NOT trade on v2..."""
    ctx = MarketContext(
        symbol="Volatility 75 Index",
        candles={
            "M5": pd.DataFrame(_dbr_retest_bars()),
            "M15": _mtf_bullish(),
            "M30": _mtf_bullish(timedelta(minutes=30)),
        },
        spread_points=1.0,
    )
    assert v2.PobSndZonesVix75().evaluate(ctx) is None

    # ...but the same scenario trades when the toggle is off, proving the
    # veto came from continuation_only and not something else.
    strategy = v2.PobSndZonesVix75()
    strategy.spec.params["continuation_only"] = False
    signal = strategy.evaluate(ctx)
    assert signal is not None
    assert "DBR-retest" in signal.reason


# ---- fx (XAUUSD/XAGUSD): H1/H4 confirmation + trend alignment --------------


def test_fx_spec_targets_metals_with_htf_confirmation():
    instance = fx.PobSndZonesFx()
    assert instance.spec.name == "pob_snd_zones_fx"
    assert instance.spec.symbols == ("XAUUSD", "XAGUSD")
    assert instance.spec.confirmation_timeframes == ("H1", "H4")
    assert instance.spec.params["htf_trend_ema_period"] == 50
    assert instance.spec.params["continuation_only"] is True


def test_fx_buys_rbr_retest_in_h1_uptrend():
    ctx = MarketContext(
        symbol="XAUUSD",
        candles={
            "M5": pd.DataFrame(_demand_retest_bars()),
            "H1": _htf_uptrend(),
            "H4": _htf_uptrend(step=timedelta(hours=4)),
        },
        spread_points=1.0,
    )
    signal = fx.PobSndZonesFx().evaluate(ctx)
    assert signal is not None
    assert signal.direction == Direction.BUY
    assert signal.zone is not None
    assert signal.zone.kind == ZoneKind.DEMAND
    assert signal.tp_points == signal.sl_points * 2.5


def test_fx_vetoes_demand_retest_against_h1_downtrend():
    """Trend gate: same RBR retest, but H1 closes below its EMA(50) — the
    counter-trend buy must be vetoed even though H4 still confirms."""
    ctx = MarketContext(
        symbol="XAUUSD",
        candles={
            "M5": pd.DataFrame(_demand_retest_bars()),
            "H1": _htf_downtrend(),
            "H4": _htf_uptrend(step=timedelta(hours=4)),
        },
        spread_points=1.0,
    )
    assert fx.PobSndZonesFx().evaluate(ctx) is None
