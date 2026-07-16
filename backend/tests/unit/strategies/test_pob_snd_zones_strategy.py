"""Unit tests for `pob_snd_zones_vix75_v1.py` — the S&D zone-retest strategy
whose zone detection mirrors the frontend `snd` chart indicator. Loaded via
`importlib` from its path, same convention as `test_vix75_strategy.py`."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pandas as pd

from src.strategies.domain.models import Direction, MarketContext, ZoneKind

_STRATEGY_PATH = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "strategies"
    / "generated"
    / "pob_snd_zones_vix75_v1.py"
)

START = datetime(2026, 1, 1, tzinfo=UTC)
STEP = timedelta(minutes=5)


def _load_strategy_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("pob_snd_zones_under_test", _STRATEGY_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = _load_strategy_module()


def _bar(i: int, o: float, h: float, low: float, c: float) -> dict:
    return {
        "time": START + i * STEP,
        "open": o,
        "high": h,
        "low": low,
        "close": c,
        "tick_volume": 1000,
    }


def _warmup(n: int = 34) -> list[dict]:
    """Flat bars with range 1.2 / body 0.4 → ATR(14) ≈ 1.2, so base-class
    means body ≤ ~0.6 and a leg needs ≥ ~1.2 net travel (drifts upward as
    the pattern's own big bars enter the ATR window)."""
    return [_bar(i, 100.0, 100.6, 99.4, 100.4) for i in range(n)]


def _mtf_bullish() -> pd.DataFrame:
    """Confirmation frame whose last bars contain a bullish engulfing."""
    bars = [_bar(i, 100.0, 100.6, 99.4, 100.4) for i in range(8)]
    bars.append(_bar(8, 100.4, 100.5, 99.8, 99.9))  # bearish
    bars.append(_bar(9, 99.8, 101.2, 99.7, 101.0))  # engulfs it
    return pd.DataFrame(bars)


def _mtf_bearish() -> pd.DataFrame:
    bars = [_bar(i, 100.0, 100.6, 99.4, 100.4) for i in range(8)]
    bars.append(_bar(8, 100.0, 100.6, 99.9, 100.5))  # bullish
    bars.append(_bar(9, 100.6, 100.7, 99.2, 99.4))  # engulfs it
    return pd.DataFrame(bars)


# ---- _detect_zones ----------------------------------------------------------


def test_detect_zones_finds_rbr_with_retest():
    params = mod.PobSndZonesVix75().spec.params
    bars = _warmup()
    i = len(bars)
    bars.append(_bar(i, 100.0, 104.2, 100.0, 104.0))  # rally in
    bars.append(_bar(i + 1, 104.0, 104.4, 103.6, 104.1))  # base
    bars.append(_bar(i + 2, 104.1, 108.3, 104.0, 108.0))  # rally out
    bars.append(_bar(i + 3, 108.0, 108.5, 107.5, 108.2))  # drift
    bars.append(_bar(i + 4, 108.2, 108.4, 104.3, 107.9))  # retest (low ≤ 104.4)
    df = pd.DataFrame(bars)
    opens, highs, lows, closes = (df[col].to_numpy() for col in ("open", "high", "low", "close"))
    atr = mod._atr(highs, lows, closes, int(params["atr_period"]))

    zones = mod._detect_zones(opens, highs, lows, closes, atr, params)
    rbr = [z for z in zones if z["pattern"] == "RBR"]
    assert len(rbr) == 1
    zone = rbr[0]
    assert zone["kind"] == ZoneKind.DEMAND
    assert zone["price_high"] == 104.4
    assert zone["price_low"] == 103.6
    assert zone["retest_idx"] == i + 4
    assert zone["broken_idx"] is None


def test_detect_zones_marks_broken_zone():
    params = mod.PobSndZonesVix75().spec.params
    bars = _warmup()
    i = len(bars)
    bars.append(_bar(i, 100.0, 104.2, 100.0, 104.0))  # rally in
    bars.append(_bar(i + 1, 104.0, 104.4, 103.6, 104.1))  # base
    bars.append(_bar(i + 2, 104.1, 108.3, 104.0, 108.0))  # rally out
    bars.append(_bar(i + 3, 108.0, 108.1, 102.9, 103.1))  # closes through the band
    df = pd.DataFrame(bars)
    opens, highs, lows, closes = (df[col].to_numpy() for col in ("open", "high", "low", "close"))
    atr = mod._atr(highs, lows, closes, int(params["atr_period"]))

    zones = mod._detect_zones(opens, highs, lows, closes, atr, params)
    rbr = [z for z in zones if z["pattern"] == "RBR"]
    assert len(rbr) == 1
    assert rbr[0]["broken_idx"] == i + 3


def test_detect_zones_finds_dbd_supply():
    params = mod.PobSndZonesVix75().spec.params
    bars = _warmup()
    i = len(bars)
    bars.append(_bar(i, 100.0, 100.0, 95.8, 96.0))  # drop in
    bars.append(_bar(i + 1, 96.0, 96.4, 95.6, 95.9))  # base
    bars.append(_bar(i + 2, 95.9, 95.9, 91.7, 92.0))  # drop out
    df = pd.DataFrame(bars)
    opens, highs, lows, closes = (df[col].to_numpy() for col in ("open", "high", "low", "close"))
    atr = mod._atr(highs, lows, closes, int(params["atr_period"]))

    zones = mod._detect_zones(opens, highs, lows, closes, atr, params)
    dbd = [z for z in zones if z["pattern"] == "DBD"]
    assert len(dbd) == 1
    assert dbd[0]["kind"] == ZoneKind.SUPPLY
    assert dbd[0]["price_high"] == 96.4
    assert dbd[0]["price_low"] == 95.6


# ---- evaluate ---------------------------------------------------------------


def _demand_retest_bars() -> list[dict]:
    """RBR demand zone at [103.6, 104.4], price drifts away, then the last
    bar dips into the band and prints a bullish engulfing close."""
    bars = _warmup()
    i = len(bars)
    bars.append(_bar(i, 100.0, 104.2, 100.0, 104.0))  # rally in
    bars.append(_bar(i + 1, 104.0, 104.4, 103.6, 104.1))  # base
    bars.append(_bar(i + 2, 104.1, 108.3, 104.0, 108.0))  # rally out
    # Drift down in base-class bars (bodies 0.5 ≤ ~0.6·ATR) — 4 of them, one
    # more than max_base_candles, so no accidental zone forms in the drift.
    bars.append(_bar(i + 3, 108.2, 108.3, 107.4, 107.7))
    bars.append(_bar(i + 4, 107.7, 107.8, 106.9, 107.2))
    bars.append(_bar(i + 5, 107.2, 107.3, 106.4, 106.7))
    bars.append(_bar(i + 6, 106.7, 106.8, 106.0, 106.2))
    # Retest bar: wick tags the band (low 104.2 ≤ 104.4) and closes as a
    # bullish engulfing of the prior bearish drift bar.
    bars.append(_bar(i + 7, 106.1, 107.0, 104.2, 106.9))
    return bars


def test_evaluate_buys_demand_zone_retest():
    strategy = mod.PobSndZonesVix75()
    ctx = MarketContext(
        symbol="Volatility 75 Index",
        candles={
            "M5": pd.DataFrame(_demand_retest_bars()),
            "M15": _mtf_bullish(),
            "M30": _mtf_bullish(),
        },
        spread_points=1.0,
    )
    signal = strategy.evaluate(ctx)
    assert signal is not None
    assert signal.direction == Direction.BUY
    assert signal.zone is not None
    assert signal.zone.kind == ZoneKind.DEMAND
    assert signal.zone.price_high == 104.4
    assert signal.zone.price_low == 103.6
    assert "RBR-retest" in signal.reason
    assert signal.sl_points > 0
    assert signal.tp_points > signal.sl_points  # RR 1.8


def test_evaluate_sells_supply_zone_retest():
    bars = _warmup()
    i = len(bars)
    bars.append(_bar(i, 100.8, 100.8, 96.6, 96.8))  # drop in
    bars.append(_bar(i + 1, 96.8, 97.2, 96.4, 96.7))  # base
    bars.append(_bar(i + 2, 96.7, 96.8, 92.5, 92.8))  # drop out
    bars.append(_bar(i + 3, 92.6, 93.4, 92.5, 93.1))  # drift up, base-class
    bars.append(_bar(i + 4, 93.1, 93.9, 93.0, 93.6))
    bars.append(_bar(i + 5, 93.6, 94.4, 93.5, 94.1))
    bars.append(_bar(i + 6, 94.1, 94.9, 94.0, 94.6))
    # Retest: wick tags the band (high 96.6 ≥ 96.4), bearish engulfing close.
    bars.append(_bar(i + 7, 94.7, 96.6, 93.8, 94.0))
    ctx = MarketContext(
        symbol="Volatility 75 Index",
        candles={
            "M5": pd.DataFrame(bars),
            "M15": _mtf_bearish(),
            "M30": _mtf_bearish(),
        },
        spread_points=1.0,
    )
    signal = mod.PobSndZonesVix75().evaluate(ctx)
    assert signal is not None
    assert signal.direction == Direction.SELL
    assert signal.zone is not None
    assert signal.zone.kind == ZoneKind.SUPPLY
    assert "DBD-retest" in signal.reason


def test_evaluate_none_without_retest():
    """Same demand-zone history but the last bar never comes back to the
    band — no retest, no trade."""
    bars = _demand_retest_bars()[:-1]
    bars.append(_bar(len(bars), 106.1, 107.0, 105.9, 106.9))  # stays away
    ctx = MarketContext(
        symbol="Volatility 75 Index",
        candles={
            "M5": pd.DataFrame(bars),
            "M15": _mtf_bullish(),
            "M30": _mtf_bullish(),
        },
        spread_points=1.0,
    )
    assert mod.PobSndZonesVix75().evaluate(ctx) is None


def test_evaluate_none_without_mtf_confirmation():
    """Valid retest + entry candle, but no higher-TF confirmation frames —
    the SNRC 'switch to higher TF' gate must veto."""
    ctx = MarketContext(
        symbol="Volatility 75 Index",
        candles={"M5": pd.DataFrame(_demand_retest_bars())},
        spread_points=1.0,
    )
    assert mod.PobSndZonesVix75().evaluate(ctx) is None


def test_evaluate_none_on_short_history():
    ctx = MarketContext(
        symbol="Volatility 75 Index",
        candles={"M5": pd.DataFrame(_warmup(10))},
        spread_points=1.0,
    )
    assert mod.PobSndZonesVix75().evaluate(ctx) is None
