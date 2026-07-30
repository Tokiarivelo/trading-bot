"""Unit tests for `pob_snd_zones_xauusd_v1.py` — the XAUUSD PoB S&D strategy
with zone-rectangle stops and next-opposite-zone targets. The zone timeframe
is resampled in-strategy from M5, so fixtures build M5 bars in groups of
three (one M15 bucket each) and the tests pin `zone_tf_minutes=15`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

import src.strategies.generated.pob_snd_zones_xauusd_v1 as pob_snd_zones_xauusd_v1
from src.strategies.domain.models import Direction, MarketContext, ZoneKind
from src.strategies.generated.pob_snd_zones_xauusd_v1 import (
    PobSndZonesXauusd,
    _atr,
    _detect_zones,
    _nearest_opposite_edge,
    _resample,
)

START = datetime(2026, 1, 1, tzinfo=UTC)
STEP = timedelta(minutes=5)
SPREAD_POINTS = 20.0  # * point_value 0.01 -> 0.2 price units


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
    """Append one M15 bucket as three identical M5 bars (M15 open = first
    bar's open, close = last bar's close, high/low = shared range)."""
    i = len(bars)
    for j in range(3):
        bars.append(_bar(i + j, o, h, low, c))


def _rbr_fixture() -> list[dict]:
    """34 flat M15 buckets (ATR(14) ~ 1.26), then rally (2) - base (1) -
    rally (2): an RBR demand zone with band [103.4, 104.0], followed by six
    M5 bars parked above the band. M5 index 117 is the first bar after the
    leg-out's bucket; the retest is appended by each test."""
    bars: list[dict] = []
    for _ in range(34):
        _bucket(bars, 100.0, 100.6, 99.4, 100.4)
    _bucket(bars, 100.4, 102.1, 100.3, 102.0)  # leg-in
    _bucket(bars, 102.0, 103.7, 101.9, 103.6)
    _bucket(bars, 103.6, 104.0, 103.4, 103.8)  # base -> zone band
    _bucket(bars, 103.8, 105.5, 103.7, 105.4)  # leg-out (confirms: 105.4 > 104.0)
    _bucket(bars, 105.4, 107.1, 105.3, 107.0)
    for _ in range(6):  # away from the band, M5-granular
        bars.append(_bar(len(bars), 106.8, 107.2, 106.5, 107.0))
    return bars


def _strategy(**param_overrides) -> PobSndZonesXauusd:
    strategy = PobSndZonesXauusd()
    strategy.spec.params.update(
        {
            "zone_tf_minutes": 15,
            "session_windows": (),
            "htf_trend_ema_period": 0,
            "min_confirmations": 0,
            "tp_use_h1_zones": False,
            "max_retest_episodes": 1,
        }
    )
    strategy.spec.params.update(param_overrides)
    return strategy


def _ctx(bars: list[dict]) -> MarketContext:
    return MarketContext(
        symbol="XAUUSD", candles={"M5": pd.DataFrame(bars)}, spread_points=SPREAD_POINTS
    )


def test_buy_signal_on_rbr_retest_with_zone_anchored_sl() -> None:
    bars = _rbr_fixture()
    bars.append(_bar(123, 105.0, 105.1, 104.4, 104.5))  # bearish setup bar
    bars.append(_bar(124, 104.4, 105.2, 103.9, 105.0))  # bullish engulfing into band

    strategy = _strategy()
    signal = strategy.evaluate(_ctx(bars))

    assert signal is not None
    assert signal.direction is Direction.BUY
    assert signal.pattern == "bullish_engulfing"
    assert signal.zone is not None
    assert signal.zone.kind is ZoneKind.DEMAND
    assert signal.zone.price_low == pytest.approx(103.4)
    assert signal.zone.price_high == pytest.approx(104.0)
    assert "RBR" in signal.reason

    # SL anchors beyond the zone's distal edge (103.4) plus the volatility
    # margin — strictly deeper than the raw close-to-edge distance.
    close = 105.0
    assert signal.sl_points > close - 103.4
    # No opposite zone in the fixture -> fallback target, expressed as a
    # multiple of the spread-adjusted risk (SpreadGate's formula).
    params = strategy.spec.params
    risk = signal.sl_points + SPREAD_POINTS * params["point_value"]
    assert signal.tp_points == pytest.approx(risk * params["tp_fallback_rr"])
    assert signal.tp_points / risk >= params["min_signal_rr"]


def test_no_signal_on_short_history() -> None:
    bars = [_bar(i, 100.0, 100.6, 99.4, 100.4) for i in range(30)]
    assert _strategy().evaluate(_ctx(bars)) is None


def test_no_signal_when_zone_broken() -> None:
    bars = _rbr_fixture()
    bars.append(_bar(123, 104.0, 104.1, 102.9, 103.0))  # closes through 103.4 -> zone dead
    bars.append(_bar(124, 103.0, 104.6, 102.9, 104.5))  # would-be confirmation candle
    assert _strategy().evaluate(_ctx(bars)) is None


def test_no_signal_when_retest_is_stale() -> None:
    bars = _rbr_fixture()
    bars.append(_bar(123, 105.0, 105.1, 104.4, 104.5))
    # Episode starts here (wick into band) but prints no confirming candle...
    for k in range(4):
        bars.append(_bar(124 + k, 104.0, 104.1, 103.9, 104.0))
    # ...and by the time one prints, the episode is older than the window.
    bars.append(_bar(128, 104.0, 105.2, 103.95, 105.0))
    assert _strategy(retest_entry_window_bars=2).evaluate(_ctx(bars)) is None


def test_no_signal_on_wrong_direction_pattern() -> None:
    bars = _rbr_fixture()
    bars.append(_bar(123, 104.6, 105.2, 104.5, 105.1))  # bullish setup bar
    bars.append(_bar(124, 105.2, 105.3, 103.9, 104.45))  # BEARISH engulfing at a demand zone
    assert _strategy().evaluate(_ctx(bars)) is None


def test_no_second_signal_for_same_episode() -> None:
    bars = _rbr_fixture()
    bars.append(_bar(123, 105.0, 105.1, 104.4, 104.5))
    bars.append(_bar(124, 104.4, 105.2, 103.9, 105.0))  # first confirming candle (fired)
    bars.append(_bar(125, 105.0, 105.6, 104.9, 105.5))  # later confirming candle, same episode
    assert _strategy().evaluate(_ctx(bars)) is None


def test_no_signal_outside_session_windows() -> None:
    bars = _rbr_fixture()
    bars.append(_bar(123, 105.0, 105.1, 104.4, 104.5))
    bars.append(_bar(124, 104.4, 105.2, 103.9, 105.0))
    # Entry bar is at 10:20 UTC (minute 620); allow only the first minute.
    assert _strategy(session_windows=((0, 1),)).evaluate(_ctx(bars)) is None


def test_resample_aggregates_and_drops_partial_bucket() -> None:
    bars = [
        _bar(0, 100.0, 101.0, 99.5, 100.5),
        _bar(1, 100.5, 102.0, 100.4, 101.5),
        _bar(2, 101.5, 101.8, 100.9, 101.0),
        _bar(3, 101.0, 101.2, 99.0, 99.2),
        _bar(4, 99.2, 99.6, 98.8, 99.5),
        _bar(5, 99.5, 100.4, 99.4, 100.3),
        _bar(6, 100.3, 100.9, 100.2, 100.8),  # partial third bucket -> dropped
    ]
    result = _resample(pd.DataFrame(bars), 15)
    assert result is not None
    frame, end_times = result
    assert len(frame) == 2
    assert frame["open"].tolist() == [100.0, 101.0]
    assert frame["high"].tolist() == [102.0, 101.2]
    assert frame["low"].tolist() == [99.5, 98.8]
    assert frame["close"].tolist() == [101.0, 100.3]
    assert list(end_times) == [
        int(pd.Timestamp(START + 3 * STEP).value),
        int(pd.Timestamp(START + 6 * STEP).value),
    ]


def test_nearest_opposite_edge_picks_closest_past_price() -> None:
    supplies = [(110.0, "RBD"), (107.5, "DBD"), (99.0, "DBD")]
    assert _nearest_opposite_edge(supplies, demand=True, close=105.0) == (107.5, "DBD")
    demands = [(101.0, "RBR"), (103.5, "DBR"), (108.0, "RBR")]
    assert _nearest_opposite_edge(demands, demand=False, close=105.0) == (103.5, "DBR")


def test_spec_shape() -> None:
    strategy = PobSndZonesXauusd()
    assert strategy.spec.name == "pob_snd_zones_xauusd"
    assert strategy.spec.symbols == ("XAUUSD",)
    assert strategy.spec.entry_timeframe == "M5"
    assert strategy.spec.confirmation_timeframes == ("H1", "H4")


# --- Incremental zone-detection cache: bit-identical proof -----------------
#
# `PobSndZonesXauusd._detect_zones_cached` is a timestamp-keyed incremental
# replacement for the stateless `_detect_zones(zone_frame, atr, params)` full
# recompute, designed to be replicated to the other 22 generated strategy
# files (see OPTIMIZATION_CHECKLIST.md). These tests are the actual proof
# it's safe to do that: a long synthetic walk-forward series is fed through a
# fixed-size sliding window (mirroring the engine's `get_candles(symbol,
# timeframe, context_bars)` / the backtest context builder) one bar at a
# time, and at EVERY step the incremental cache's output must exactly match
# a from-scratch `_detect_zones` recompute on the identical zone_frame.

CONTEXT_BARS = 200  # engine/backtest window size, per the module docstring
ZONE_TF_MINUTES = 30  # production default (see PobSndZonesXauusd.__init__)
ATR_PERIOD = 14  # production default


def _make_walk_forward_series(n_bars: int, seed: int) -> list[dict]:
    """Multi-week synthetic M5 OHLC series with regime-switching drift
    (trend-up / trend-down / chop, each lasting a random few-to-twenty
    bars) so the zone-TF-resampled bars produce a realistic mix of legs,
    bases, and weak-run merges — not just noise. Skips Saturdays like a
    real forex/CFD feed, so the walk also exercises the cache's
    session-gap fallback (no timestamp overlap -> full recompute)."""
    rng = np.random.default_rng(seed)
    bars: list[dict] = []
    t = START
    price = 2000.0
    regime = 0
    regime_len = 0
    while len(bars) < n_bars:
        if t.weekday() == 5:  # Saturday: jump the weekend gap
            t = t + timedelta(days=2)
            continue
        if regime_len <= 0:
            regime = int(rng.choice([-1, 0, 1], p=[0.35, 0.3, 0.35]))
            regime_len = int(rng.integers(4, 20))
        drift = {-1: -0.35, 0: 0.0, 1: 0.35}[regime] * rng.uniform(0.5, 1.5)
        noise = rng.normal(0, 0.15)
        o = price
        c = o + drift + noise
        hi = max(o, c) + abs(rng.normal(0, 0.08))
        lo = min(o, c) - abs(rng.normal(0, 0.08))
        bars.append({"time": t, "open": o, "high": hi, "low": lo, "close": c, "tick_volume": 1000})
        price = c
        t = t + STEP
        regime_len -= 1
    return bars


def _zone_fingerprint(zone: dict, zone_end_ns: np.ndarray) -> tuple:
    """Normalize a zone dict for cross-call comparison: positions
    (base_start/conf_idx/leg_out_end) are only meaningful within the
    zone_frame that produced them, so translate them to the bucket's
    absolute end timestamp — the stable identifier — before comparing."""
    return (
        zone["pattern"],
        zone["kind"],
        round(zone["price_high"], 6),
        round(zone["price_low"], 6),
        int(zone_end_ns[zone["base_start"]]),
        int(zone_end_ns[zone["conf_idx"]]),
        int(zone_end_ns[zone["leg_out_end"]]),
    )


def test_incremental_cache_matches_full_recompute_every_step() -> None:
    """Walk ~4000 M5 bars forward one bar at a time through a fixed-size
    200-bar sliding window (rolling the window over ~19 times), and at
    EVERY single step assert the incremental cache
    (`PobSndZonesXauusd._detect_zones_cached`, called on one persistent
    strategy instance so its cache carries forward) produces exactly the
    same zones as the stateless full recompute (`_detect_zones`) on the
    identical zone_frame — not just at the end of the walk."""
    all_bars = _make_walk_forward_series(4200, seed=20260728)
    df_all = pd.DataFrame(all_bars)
    params = PobSndZonesXauusd().spec.params
    incremental = PobSndZonesXauusd()

    checked_steps = 0
    found_any_zone = False
    for end in range(CONTEXT_BARS, len(df_all)):
        window = df_all.iloc[end - CONTEXT_BARS : end].reset_index(drop=True)
        resampled = _resample(window, ZONE_TF_MINUTES)
        if resampled is None:
            continue
        zone_frame, zone_end_ns = resampled
        atr_series = _atr(zone_frame, ATR_PERIOD)
        if atr_series.dropna().empty:
            continue

        ground_truth = _detect_zones(zone_frame, atr_series, params)
        cached = incremental._detect_zones_cached(zone_frame, zone_end_ns, atr_series, params)

        gt_fp = [_zone_fingerprint(z, zone_end_ns) for z in ground_truth]
        cached_fp = [_zone_fingerprint(z, zone_end_ns) for z in cached]
        assert cached_fp == gt_fp, f"zone mismatch at window end={end}: {cached_fp} != {gt_fp}"
        checked_steps += 1
        found_any_zone = found_any_zone or bool(ground_truth)

    # Sanity: the walk actually exercised a meaningful number of steps
    # (rolling the 200-bar window over many times), and zones were actually
    # found somewhere along the way — this isn't vacuously passing on empty
    # output the entire walk.
    assert checked_steps > 3000
    assert found_any_zone


def test_incremental_cache_reprocesses_far_fewer_bars_than_full_recompute() -> None:
    """Prove the algorithmic claim from the design (not a wall-clock
    benchmark): in steady state, `_detect_zones_cached`'s classify+run-
    grouping loop (`_build_runs_from`) only walks the ATR-warmup head and
    the newly-appended tail of the zone_frame, never the cached middle —
    while a cold instance (no cache yet, e.g. right after engine restart)
    walks the whole thing, exactly like a bare `_detect_zones` recompute
    would."""
    all_bars = _make_walk_forward_series(1400, seed=99)
    df_all = pd.DataFrame(all_bars)
    params = PobSndZonesXauusd().spec.params
    incremental = PobSndZonesXauusd()

    bars_walked: list[int] = []
    orig = pob_snd_zones_xauusd_v1._build_runs_from

    def counting(classes, start, stop=None):
        stop_pos = len(classes) if stop is None else stop
        bars_walked.append(max(0, stop_pos - start))
        return orig(classes, start, stop)

    # Warm the cache up over many steady-state steps first, uninstrumented.
    warm_end = CONTEXT_BARS + 600
    for end in range(CONTEXT_BARS, warm_end):
        window = df_all.iloc[end - CONTEXT_BARS : end].reset_index(drop=True)
        resampled = _resample(window, ZONE_TF_MINUTES)
        if resampled is None:
            continue
        zone_frame, zone_end_ns = resampled
        atr_series = _atr(zone_frame, ATR_PERIOD)
        if atr_series.dropna().empty:
            continue
        incremental._detect_zones_cached(zone_frame, zone_end_ns, atr_series, params)

    # One more steady-state step, instrumented, compared against a cold
    # (freshly-constructed, no cache) instance evaluating the *identical*
    # window.
    window = df_all.iloc[warm_end - CONTEXT_BARS : warm_end].reset_index(drop=True)
    zone_frame, zone_end_ns = _resample(window, ZONE_TF_MINUTES)
    atr_series = _atr(zone_frame, ATR_PERIOD)
    n_bars_in_frame = len(zone_frame)
    assert n_bars_in_frame > 0

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(pob_snd_zones_xauusd_v1, "_build_runs_from", counting)

        bars_walked.clear()
        incremental._detect_zones_cached(zone_frame, zone_end_ns, atr_series, params)
        incremental_bars = sum(bars_walked)

        bars_walked.clear()
        cold = PobSndZonesXauusd()
        cold._detect_zones_cached(zone_frame, zone_end_ns, atr_series, params)
        cold_bars = sum(bars_walked)

    # Cold (no cache yet) always falls back to a full recompute: every bar
    # in the frame goes through the classify+group loop, same as
    # `_detect_zones` would process unconditionally.
    assert cold_bars == n_bars_in_frame
    # The warmed-up incremental instance reprocesses strictly fewer bars —
    # only the ATR-warmup head (`atr_period` bars, never cacheable — see
    # `_detect_zones_cached` docstring) plus the newly-appended tail, not
    # the whole window.
    assert incremental_bars < cold_bars
    assert incremental_bars <= n_bars_in_frame * 0.75
