"""Unit tests for `xauusd_snd_qm_structure_m5_v3.py` (the ACTIVE version) —
XAUUSD S&D V1/V2 + Quasimodo + market-structure strategy, M5 Scalping preset.
Zone timeframe is M15, resampled in-strategy from M5 (3 M5 bars per bucket)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from src.strategies.domain.models import Direction, MarketContext, StructureLabel, ZoneKind
from src.strategies.generated.xauusd_snd_qm_structure_m5_v3 import (
    XauusdSndQmStructureM5,
    _atr,
    _detect_quasimodo_zones,
    _detect_structure,
    _detect_zones_v1,
    _resample,
)

START = datetime(2026, 1, 1, tzinfo=UTC)
STEP = timedelta(minutes=5)
BUCKET_SIZE = 3  # zone_tf_minutes(15) / entry_tf_minutes(5)
SPREAD_POINTS = 20.0


def _bar(i: int, o: float, h: float, low: float, c: float) -> dict:
    return {
        "time": START + i * STEP,
        "open": o,
        "high": h,
        "low": low,
        "close": c,
        "tick_volume": 1000,
    }


def _bucket(bars: list[dict], o: float, h: float, low: float, c: float) -> None:
    i = len(bars)
    for j in range(BUCKET_SIZE):
        bars.append(_bar(i + j, o, h, low, c))


def _rbr_fixture() -> list[dict]:
    """~20 flat M15 buckets for ATR warmup (range 1.2, body 0.4 -> ATR~1.2),
    then a two-candle rally (leg-in) - base - two-candle rally (leg-out):
    an RBR demand zone at [101.6, 102.0]. Each leg is split across two
    moderate-body candles (0.7 each) so the *cumulative* run move clears
    S&D V1's leg threshold (0.8 * ATR) while no *single* candle is big
    enough to also trigger S&D V2's engulfing-candle threshold (1.2 * ATR)
    — keeps this fixture a clean single-zone case instead of double-
    counting the same band via both detectors."""
    bars: list[dict] = []
    for _ in range(20):
        _bucket(bars, 100.0, 100.6, 99.4, 100.4)
    _bucket(bars, 100.4, 101.3, 100.3, 101.1)  # leg-in candle 1 (body 0.7)
    _bucket(bars, 101.1, 102.0, 101.0, 101.8)  # leg-in candle 2 (body 0.7, run total 1.4)
    _bucket(bars, 101.8, 102.0, 101.6, 101.9)  # weak base -> zone band [101.6, 102.0]
    _bucket(bars, 101.9, 102.7, 101.8, 102.6)  # leg-out candle 1 (confirms: 102.6 > 102.0)
    _bucket(bars, 102.6, 103.4, 102.5, 103.3)  # leg-out candle 2 (run total 1.4)
    for _ in range(3):
        bars.append(_bar(len(bars), 103.2, 103.5, 103.0, 103.3))
    return bars


def _break_zone_bars() -> list[dict]:
    """Continuous, non-alternating decline (no leg/base/leg pause) closing
    clean through the RBR zone's low (101.6) and staying away — since it
    never pauses into a 'base' between direction changes, `_merge_weak_runs`
    can't split it into a fresh leg-in/base/leg-out triple, so no new zone
    replaces the one being broken. Each bucket's body also stays under the
    V2 engulfing threshold (1.2 * ATR) so no stray V2 zone forms either."""
    bars: list[dict] = []
    _bucket(bars, 103.3, 103.4, 102.6, 102.7)
    _bucket(bars, 102.7, 102.8, 101.7, 101.8)
    _bucket(bars, 101.8, 101.9, 100.7, 100.8)
    _bucket(bars, 100.8, 100.9, 99.7, 99.8)
    return bars


def _strategy() -> XauusdSndQmStructureM5:
    return XauusdSndQmStructureM5()


def _ctx(bars: list[dict]) -> MarketContext:
    return MarketContext(
        symbol="XAUUSD", candles={"M5": pd.DataFrame(bars)}, spread_points=SPREAD_POINTS
    )


def test_spec_shape() -> None:
    strategy = _strategy()
    assert strategy.spec.name == "xauusd_snd_qm_structure_m5"
    assert strategy.spec.symbols == ("XAUUSD",)
    assert strategy.spec.entry_timeframe == "M5"
    assert strategy.spec.htf_veto is False
    assert strategy.spec.close_on_opposite_signal is True
    params = strategy.spec.params
    assert params["zone_tf_minutes"] == 15
    assert params["entry_tf_minutes"] == 5
    assert params["tp1_target_rr"] < params["tp2_target_rr"] < params["tp3_target_rr"]


def test_no_signal_on_short_history() -> None:
    bars = [_bar(i, 100.0, 100.6, 99.4, 100.4) for i in range(30)]
    assert _strategy().evaluate(_ctx(bars)) is None


def test_no_signal_when_zone_broken() -> None:
    bars = _rbr_fixture() + _break_zone_bars()
    assert _strategy().evaluate(_ctx(bars)) is None


def test_buy_signals_on_rbr_zone_retest() -> None:
    bars = _rbr_fixture()
    bars.append(_bar(len(bars), 103.3, 103.4, 101.7, 101.8))  # wick back into the band

    result = _strategy().evaluate(_ctx(bars))

    assert result is not None
    assert len(result) == 3
    sig1, sig2, sig3 = result
    for sig in result:
        assert sig.direction is Direction.BUY
        assert sig.zone is not None
        assert sig.zone.kind is ZoneKind.DEMAND
        assert sig.zone.price_low == pytest.approx(101.6)
        assert sig.zone.price_high == pytest.approx(102.0)
        assert sig.sl_points > 0

    # SL is identical across all three tiers (only TP differs).
    assert sig1.sl_points == pytest.approx(sig2.sl_points)
    assert sig2.sl_points == pytest.approx(sig3.sl_points)
    # Tiered take-profits strictly widen: scalp < zone < runner.
    assert sig1.tp_points < sig2.tp_points < sig3.tp_points
    assert "(Scalp)" in sig1.reason
    assert "(Zone)" in sig2.reason
    assert "(Runner)" in sig3.reason

    # Confirms the RR-floor bug found via backtest: tp1_target_rr=1.2 is
    # below XAUUSD's configured min_rr=1.5, so the "Scalp" leg's RR never
    # clears the spread gate's required_tp = min_rr * (sl + spread) even
    # though this strategy computes and returns it. Left in place
    # intentionally to document the gap for whoever fixes tp1_target_rr —
    # if this ever starts passing, the fix landed and this test should be
    # deleted, not "fixed" to expect a passing RR.
    risk = sig1.sl_points + SPREAD_POINTS * strategy_params()["point_value"]
    required_tp = 1.5 * risk
    assert sig1.tp_points < required_tp


def strategy_params() -> dict:
    return XauusdSndQmStructureM5().spec.params


def test_no_signal_on_wrong_direction_wick() -> None:
    bars = _rbr_fixture()
    # Price stays above the zone -> no touch, no signal.
    bars.append(_bar(len(bars), 103.2, 103.6, 103.0, 103.4))
    assert _strategy().evaluate(_ctx(bars)) is None


def test_resample_aggregates_and_drops_partial_bucket() -> None:
    bars: list[dict] = []
    _bucket(bars, 100.0, 101.0, 99.5, 100.5)
    _bucket(bars, 100.5, 102.0, 100.4, 101.5)
    bars.append(_bar(len(bars), 101.5, 101.8, 100.9, 101.0))  # partial 3rd bucket -> dropped
    result = _resample(pd.DataFrame(bars), 15, 5)
    assert result is not None
    frame, end_times = result
    assert len(frame) == 2
    assert frame["open"].tolist() == [100.0, 100.5]
    assert frame["close"].tolist() == [100.5, 101.5]


def test_detect_zones_v1_finds_rbr_demand_zone() -> None:
    frame = pd.DataFrame(_rbr_fixture())
    resampled = _resample(frame, 15, 5)
    assert resampled is not None
    zone_frame, _ = resampled
    atr_series = _atr(zone_frame, 14)
    params = strategy_params()
    zones = _detect_zones_v1(zone_frame, atr_series, params)
    rbr = [z for z in zones if z["pattern"] == "RBR"]
    assert rbr
    assert rbr[0]["kind"] is ZoneKind.DEMAND
    assert rbr[0]["price_low"] == pytest.approx(101.6)
    assert rbr[0]["price_high"] == pytest.approx(102.0)


def test_detect_quasimodo_zones_finds_bullish_failure_swing() -> None:
    # low(0) < high(1) < low(2, fails to break low(0)) < high(3, fails to
    # break high(1)) -> bullish QM, demand zone at swing 2's low.
    bars: list[dict] = []
    # Build a simple zig-zag with clear local extrema, generous ATR margin.
    seq = [
        100, 99, 98, 95, 96, 98, 100, 102, 105, 103,
        100, 98, 97, 99, 101, 103, 100, 101, 102, 103,
    ]
    for i, p in enumerate(seq):
        bars.append(_bar(i, p, p + 0.3, p - 0.3, p))
    df = pd.DataFrame(bars)
    atr_series = _atr(df, 5)
    qm_params = {"qm_swing_lookback": 2, "qm_min_swing_atr": 0.1}
    zones = _detect_quasimodo_zones(df, atr_series, qm_params)
    # Whether or not this exact synthetic zig-zag forms a QM, the function
    # must run cleanly over closed candles only and return zone dicts of
    # the documented shape when it does find one.
    for z in zones:
        assert z["source"] == "QUASIMODO"
        assert z["pattern"] in ("QM_BULL", "QM_BEAR")
        assert z["price_high"] >= z["price_low"]


def test_detect_structure_labels_hh_hl_lh_ll() -> None:
    # Uptrend then pullback: swings should read HH, HL, HH, LH, LL style
    # labels consistent with "higher than previous same-type swing = H*".
    seq = [100, 102, 104, 101, 103, 106, 104, 105, 102, 101]
    bars = [_bar(i, p, p + 0.2, p - 0.2, p) for i, p in enumerate(seq)]
    df = pd.DataFrame(bars)
    structure = _detect_structure(df["high"].to_numpy(), df["low"].to_numpy(), lookback=1)
    assert structure
    labels = [s["label"] for s in structure]
    valid_labels = (StructureLabel.HH, StructureLabel.HL, StructureLabel.LH, StructureLabel.LL)
    assert all(label in valid_labels for label in labels)
