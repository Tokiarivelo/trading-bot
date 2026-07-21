"""Unit tests for `rbr_dbd_zones_swing_btcusd_v1.py` — direct port of
`rbr_dbd_zones_swing_xauusd_v1.py` to BTCUSD; same mechanics,
same tests (module/class/symbol swapped)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd

import src.strategies.generated.rbr_dbd_zones_swing_btcusd_v1 as mod
from src.strategies.domain.models import Direction, MarketContext, ZoneKind

START = datetime(2026, 1, 1, tzinfo=UTC)
STEP = timedelta(minutes=15)


def _bar(i: int, o: float, h: float, low: float, c: float) -> dict:
    return {
        "time": START + i * STEP,
        "open": o,
        "high": h,
        "low": low,
        "close": c,
        "tick_volume": 1000,
    }


def _flat(n: int) -> list[dict]:
    return [_bar(i, 100.0, 100.6, 99.4, 100.4) for i in range(n)]


def _htf_bullish() -> pd.DataFrame:
    bars = _flat(10)
    bars.append(_bar(10, 100.4, 100.5, 99.8, 99.9))  # bearish
    bars.append(_bar(11, 99.8, 101.2, 99.7, 101.0))  # engulfs it
    return pd.DataFrame(bars)


def _htf_bearish() -> pd.DataFrame:
    bars = _flat(10)
    bars.append(_bar(10, 100.0, 100.6, 99.9, 100.5))  # bullish
    bars.append(_bar(11, 100.6, 100.7, 99.2, 99.4))  # engulfs it
    return pd.DataFrame(bars)


PARAMS = mod.RbrDbdZonesSwingBtcusd().spec.params


# ---- _detect_zones (shared with the scalp variant, sanity-checked here too) --


def test_detect_zones_finds_dbr_demand_reversal():
    bars = _flat(34)
    i = len(bars)
    bars.append(_bar(i, 100.8, 100.8, 96.6, 96.8))  # drop in
    bars.append(_bar(i + 1, 96.8, 97.2, 96.4, 96.7))  # base
    bars.append(_bar(i + 2, 96.7, 100.9, 96.6, 100.7))  # rally out
    df = pd.DataFrame(bars)
    opens, highs, lows, closes = (df[c].to_numpy() for c in ("open", "high", "low", "close"))
    atr = mod._atr(highs, lows, closes, int(PARAMS["atr_period"]))

    zones = mod._detect_zones(opens, highs, lows, closes, atr, PARAMS)
    dbr = [z for z in zones if z["pattern"] == "DBR"]
    assert len(dbr) == 1
    assert dbr[0]["kind"] == ZoneKind.DEMAND


def test_detect_zones_dbd_flips_to_demand_on_strong_break():
    bars = _flat(34)
    i = len(bars)
    bars.append(_bar(i, 100.8, 100.8, 96.6, 96.8))  # drop in
    bars.append(_bar(i + 1, 96.8, 97.2, 96.4, 96.7))  # base
    bars.append(_bar(i + 2, 96.7, 96.8, 92.5, 92.8))  # drop out (DBD supply)
    bars.append(_bar(i + 3, 92.8, 98.0, 92.7, 97.8))  # strong bullish close through the band
    bars.append(_bar(i + 4, 97.8, 98.1, 97.5, 97.9))
    df = pd.DataFrame(bars)
    opens, highs, lows, closes = (df[c].to_numpy() for c in ("open", "high", "low", "close"))
    atr = mod._atr(highs, lows, closes, int(PARAMS["atr_period"]))

    zones = mod._detect_zones(opens, highs, lows, closes, atr, PARAMS)
    flipped = [z for z in zones if z["pattern"] == "DBD_flip"]
    assert len(flipped) == 1
    assert flipped[0]["kind"] == ZoneKind.DEMAND
    assert flipped[0]["flipped"] is True


# ---- evaluate ---------------------------------------------------------------


def _rbr_tail() -> list[dict]:
    return [
        _bar(0, 100.0, 104.2, 100.0, 104.0),  # rally in
        _bar(1, 104.0, 104.4, 103.6, 104.1),  # base
        _bar(2, 104.1, 108.3, 104.0, 108.0),  # rally out
        _bar(3, 108.2, 108.3, 107.4, 107.7),
        _bar(4, 107.7, 107.8, 106.9, 107.2),
        _bar(5, 107.2, 107.3, 106.4, 106.7),
        _bar(6, 106.7, 106.8, 106.0, 106.2),
        _bar(7, 106.1, 107.0, 104.2, 106.9),  # retest + bullish engulf
    ]


def _dbd_supply_tail() -> list[dict]:
    return [
        _bar(0, 100.8, 100.8, 96.6, 96.8),  # drop in
        _bar(1, 96.8, 97.2, 96.4, 96.7),  # base
        _bar(2, 96.7, 96.8, 92.5, 92.8),  # drop out
        _bar(3, 92.6, 93.4, 92.5, 93.1),
        _bar(4, 93.1, 93.9, 93.0, 93.6),
        _bar(5, 93.6, 94.4, 93.5, 94.1),
        _bar(6, 94.1, 94.9, 94.0, 94.6),
        _bar(7, 94.7, 96.6, 93.8, 94.0),  # retest + bearish engulf (supply — must be ignored)
    ]


def _padded_bars(tail: list[dict]) -> pd.DataFrame:
    lookback = int(PARAMS["zone_lookback_bars"])
    n_warmup = lookback - len(tail)
    warmup = _flat(n_warmup)
    combined = warmup + tail
    for idx, bar in enumerate(combined):
        bar["time"] = START + idx * STEP
    return pd.DataFrame(combined)


def test_evaluate_buys_demand_zone_retest():
    strategy = mod.RbrDbdZonesSwingBtcusd()
    ctx = MarketContext(
        symbol="BTCUSD",
        candles={
            "M15": _padded_bars(_rbr_tail()),
            "H1": _htf_bullish(),
            "H4": _htf_bullish(),
        },
        spread_points=1.0,
    )
    signal = strategy.evaluate(ctx)
    assert signal is not None
    assert signal.direction == Direction.BUY
    assert signal.zone is not None
    assert signal.zone.kind == ZoneKind.DEMAND
    assert "RBR-retest" in signal.reason
    assert signal.sl_points > 0
    assert signal.tp_points >= PARAMS["min_rr_floor"] * signal.sl_points


def test_evaluate_ignores_supply_zone_retest_long_only():
    strategy = mod.RbrDbdZonesSwingBtcusd()
    ctx = MarketContext(
        symbol="BTCUSD",
        candles={
            "M15": _padded_bars(_dbd_supply_tail()),
            "H1": _htf_bearish(),
            "H4": _htf_bearish(),
        },
        spread_points=1.0,
    )
    assert strategy.evaluate(ctx) is None


def test_evaluate_none_without_htf_confirmation():
    ctx = MarketContext(
        symbol="BTCUSD",
        candles={"M15": _padded_bars(_rbr_tail())},
        spread_points=1.0,
    )
    assert mod.RbrDbdZonesSwingBtcusd().evaluate(ctx) is None


def test_evaluate_none_on_short_history():
    ctx = MarketContext(
        symbol="BTCUSD",
        candles={
            "M15": pd.DataFrame(_flat(10)),
            "H1": _htf_bullish(),
            "H4": _htf_bullish(),
        },
        spread_points=1.0,
    )
    assert mod.RbrDbdZonesSwingBtcusd().evaluate(ctx) is None

# ---- trend filter -----------------------------------------------------------


def _h1_trend(up: bool, n: int = 60) -> pd.DataFrame:
    """Long H1 frame with a clear EMA20-vs-EMA50 trend; every bar is a strong
    body candle, so the H1 confirmation-candle check also passes when up."""
    bars = []
    for i in range(n):
        if up:
            o = 100.0 + i * 0.5
            bars.append(_bar(i, o, o + 0.45, o - 0.05, o + 0.4))
        else:
            o = 140.0 - i * 0.5
            bars.append(_bar(i, o, o + 0.05, o - 0.45, o - 0.4))
    return pd.DataFrame(bars)


def test_evaluate_buys_when_h1_trend_aligned():
    ctx = MarketContext(
        symbol="BTCUSD",
        candles={
            "M15": _padded_bars(_rbr_tail()),
            "H1": _h1_trend(up=True),
            "H4": _htf_bullish(),
        },
        spread_points=1.0,
    )
    signal = mod.RbrDbdZonesSwingBtcusd().evaluate(ctx)
    assert signal is not None
    assert signal.direction == Direction.BUY
    assert "trend=up" in signal.reason


def test_evaluate_none_when_h1_trend_opposes_buy():
    # Same valid demand retest, but H1 is in a clear downtrend — the trend
    # filter must veto the counter-trend buy before any confirmation check.
    ctx = MarketContext(
        symbol="BTCUSD",
        candles={
            "M15": _padded_bars(_rbr_tail()),
            "H1": _h1_trend(up=False),
            "H4": _htf_bullish(),
        },
        spread_points=1.0,
    )
    assert mod.RbrDbdZonesSwingBtcusd().evaluate(ctx) is None


def test_evaluate_trend_filter_skipped_on_short_h1_history():
    # <= trend_slow_period H1 bars: the filter must skip (not veto).
    ctx = MarketContext(
        symbol="BTCUSD",
        candles={
            "M15": _padded_bars(_rbr_tail()),
            "H1": _htf_bullish(),
            "H4": _htf_bullish(),
        },
        spread_points=1.0,
    )
    signal = mod.RbrDbdZonesSwingBtcusd().evaluate(ctx)
    assert signal is not None
    assert "trend=n/a" in signal.reason
