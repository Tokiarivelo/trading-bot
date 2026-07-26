"""Unit tests for `rbr_dbd_zones_scalp_m5_btcusd_v1.py` — same fixture shape
as `test_rbr_dbd_zones_scalp_btcusd_v2.py` (the M1 sibling this was ported
from), with M5 entry bars and an M15 confirmation frame instead of M1/M5."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

import src.strategies.generated.rbr_dbd_zones_scalp_m5_btcusd_v1 as mod
from src.strategies.domain.models import Direction, MarketContext, ZoneKind

START = datetime(2026, 1, 1, tzinfo=UTC)
STEP = timedelta(minutes=5)


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


def _mtf_bullish() -> pd.DataFrame:
    bars = _flat(8)
    bars.append(_bar(8, 100.4, 100.5, 99.8, 99.9))  # bearish
    bars.append(_bar(9, 99.8, 101.2, 99.7, 101.0))  # engulfs it
    return pd.DataFrame(bars)


def _mtf_bearish() -> pd.DataFrame:
    bars = _flat(8)
    bars.append(_bar(8, 100.0, 100.6, 99.9, 100.5))  # bullish
    bars.append(_bar(9, 100.6, 100.7, 99.2, 99.4))  # engulfs it
    return pd.DataFrame(bars)


PARAMS = mod.RbrDbdZonesScalpM5Btcusd().spec.params


def test_detect_zones_finds_rbr_with_retest():
    bars = _flat(34)
    i = len(bars)
    bars.append(_bar(i, 100.0, 104.2, 100.0, 104.0))  # rally in
    bars.append(_bar(i + 1, 104.0, 104.4, 103.6, 104.1))  # base
    bars.append(_bar(i + 2, 104.1, 108.3, 104.0, 108.0))  # rally out
    bars.append(_bar(i + 3, 108.0, 108.5, 107.5, 108.2))  # drift
    bars.append(_bar(i + 4, 108.2, 108.4, 104.3, 107.9))  # retest
    df = pd.DataFrame(bars)
    opens, highs, lows, closes = (df[c].to_numpy() for c in ("open", "high", "low", "close"))
    atr = mod._atr(highs, lows, closes, int(PARAMS["atr_period"]))

    zones = mod._detect_zones(opens, highs, lows, closes, atr, PARAMS)
    rbr = [z for z in zones if z["pattern"] == "RBR"]
    assert len(rbr) == 1
    assert rbr[0]["kind"] == ZoneKind.DEMAND
    assert rbr[0]["retest_idx"] == i + 4
    assert rbr[0]["broken_idx"] is None


def _pattern_tail(rally: bool) -> list[dict]:
    if rally:
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
    return [
        _bar(0, 100.8, 100.8, 96.6, 96.8),  # drop in
        _bar(1, 96.8, 97.2, 96.4, 96.7),  # base
        _bar(2, 96.7, 96.8, 92.5, 92.8),  # drop out
        _bar(3, 92.6, 93.4, 92.5, 93.1),
        _bar(4, 93.1, 93.9, 93.0, 93.6),
        _bar(5, 93.6, 94.4, 93.5, 94.1),
        _bar(6, 94.1, 94.9, 94.0, 94.6),
        _bar(7, 94.7, 96.6, 93.8, 94.0),  # retest + bearish engulf
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
    strategy = mod.RbrDbdZonesScalpM5Btcusd()
    ctx = MarketContext(
        symbol="BTCUSD",
        candles={
            "M5": _padded_bars(_pattern_tail(rally=True)),
            "M15": _mtf_bullish(),
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


def test_evaluate_sells_supply_zone_retest():
    strategy = mod.RbrDbdZonesScalpM5Btcusd()
    ctx = MarketContext(
        symbol="BTCUSD",
        candles={
            "M5": _padded_bars(_pattern_tail(rally=False)),
            "M15": _mtf_bearish(),
        },
        spread_points=1.0,
    )
    signal = strategy.evaluate(ctx)
    assert signal is not None
    assert signal.direction == Direction.SELL
    assert signal.zone is not None
    assert signal.zone.kind == ZoneKind.SUPPLY
    assert "DBD-retest" in signal.reason


def test_evaluate_none_without_retest():
    tail = _pattern_tail(rally=True)[:-1]
    tail.append(_bar(len(tail), 106.1, 107.0, 105.9, 106.9))  # stays away from the band
    ctx = MarketContext(
        symbol="BTCUSD",
        candles={"M5": _padded_bars(tail), "M15": _mtf_bullish()},
        spread_points=1.0,
    )
    assert mod.RbrDbdZonesScalpM5Btcusd().evaluate(ctx) is None


def test_evaluate_none_without_mtf_confirmation():
    ctx = MarketContext(
        symbol="BTCUSD",
        candles={"M5": _padded_bars(_pattern_tail(rally=True))},
        spread_points=1.0,
    )
    assert mod.RbrDbdZonesScalpM5Btcusd().evaluate(ctx) is None


def test_evaluate_none_on_short_history():
    ctx = MarketContext(
        symbol="BTCUSD",
        candles={"M5": pd.DataFrame(_flat(10)), "M15": _mtf_bullish()},
        spread_points=1.0,
    )
    assert mod.RbrDbdZonesScalpM5Btcusd().evaluate(ctx) is None


def _m15_trend(up: bool, n: int = 60) -> pd.DataFrame:
    bars = []
    for i in range(n):
        if up:
            o = 100.0 + i * 0.5
            bars.append(_bar(i, o, o + 0.45, o - 0.05, o + 0.4))
        else:
            o = 140.0 - i * 0.5
            bars.append(_bar(i, o, o + 0.05, o - 0.45, o - 0.4))
    return pd.DataFrame(bars)


def test_evaluate_none_when_m15_trend_opposes_setup():
    ctx = MarketContext(
        symbol="BTCUSD",
        candles={"M5": _padded_bars(_pattern_tail(rally=True)), "M15": _m15_trend(up=False)},
        spread_points=1.0,
    )
    assert mod.RbrDbdZonesScalpM5Btcusd().evaluate(ctx) is None


def test_evaluate_reason_records_confluence_and_tp_mult():
    strategy = mod.RbrDbdZonesScalpM5Btcusd()
    ctx = MarketContext(
        symbol="BTCUSD",
        candles={
            "M5": _padded_bars(_pattern_tail(rally=True)),
            "M15": _mtf_bullish(),
        },
        spread_points=1.0,
    )
    signal = strategy.evaluate(ctx)
    assert signal is not None
    assert "confluence rsi=" in signal.reason
    assert "tp_mult=" in signal.reason


def test_confluence_votes_all_true_on_strong_uptrend_with_rising_volume():
    n = 80
    closes = pd.Series(np.linspace(100.0, 200.0, n))
    volume = pd.Series(np.linspace(100.0, 500.0, n))

    rsi_ok, ema_ok, vol_ok = mod._confluence_votes(closes, volume, Direction.BUY)

    assert rsi_ok is True
    assert ema_ok is True
    assert vol_ok is True


def test_confluence_votes_default_false_on_flat_series():
    n = 80
    closes = pd.Series([100.0] * n)
    volume = pd.Series([100.0] * n)

    rsi_ok, ema_ok, vol_ok = mod._confluence_votes(closes, volume, Direction.BUY)

    assert rsi_ok is False
    assert ema_ok is False
    assert vol_ok is False


def test_spec_version_symbol_and_timeframes():
    spec = mod.RbrDbdZonesScalpM5Btcusd().spec
    assert spec.name == "rbr_dbd_zones_scalp_m5_btcusd"
    assert spec.version == 1
    assert spec.symbols == ("BTCUSD",)
    assert spec.entry_timeframe == "M5"
    assert spec.confirmation_timeframes == ("M15",)
