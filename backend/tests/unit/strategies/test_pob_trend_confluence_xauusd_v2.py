"""Unit tests for `pob_trend_confluence_xauusd_v2.py` — the M1-only
aggressive variant of the XAUUSD PoB trend-confluence strategy. Analysis
frames (M15 structure, S&D zones, QM levels) are still resampled from the
M5 confirmation feed, but retest episodes and the entry trigger live on the
M1 entry feed — so fixtures build an M5 analysis staircase (in groups of
three bars = one M15 bucket, both analysis timeframes pinned to 15 minutes)
plus a separate timed M1 feed that performs the retest."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

import src.strategies.generated.pob_trend_confluence_xauusd_v2 as pob_trend_confluence_xauusd_v2
from src.strategies.domain.models import Direction, MarketContext, ZoneKind
from src.strategies.generated.pob_trend_confluence_xauusd_v2 import (
    PobTrendConfluenceXauusdV2,
    _atr,
    _detect_zones,
    _resample,
)

START = datetime(2026, 1, 1, tzinfo=UTC)
STEP = timedelta(minutes=5)
M1_STEP = timedelta(minutes=1)
SPREAD_POINTS = 20.0  # * point_value 0.01 -> 0.2 price units

PARKED_HIGH = (106.8, 107.2, 106.5, 107.0)  # above the RBR band, never in it
PARKED_LOW = (100.7, 101.0, 100.4, 100.8)  # below the QM shoulder, never in it


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


def _uptrend_rbr_fixture() -> list[dict]:
    """M15 structure staircase (HH at 103.0, HL at 101.5 — clean uptrend)
    followed by rally - base - rally: an RBR demand zone with band
    [103.3, 104.0], then six M5 bars parked above the band. The retest is
    performed by the M1 feed each test builds."""
    bars: list[dict] = []
    for _ in range(14):  # ATR warmup
        _bucket(bars, 100.0, 100.6, 99.4, 100.4)
    _bucket(bars, 100.4, 101.0, 100.0, 100.6)
    _bucket(bars, 100.6, 102.0, 100.5, 101.6)  # pivot high A=102.0 (HH)
    _bucket(bars, 101.6, 101.7, 100.8, 101.0)
    _bucket(bars, 101.0, 101.2, 100.4, 100.6)  # pivot low B=100.4 (HL)
    _bucket(bars, 100.6, 102.3, 100.5, 102.0)
    _bucket(bars, 102.0, 103.0, 101.8, 102.7)  # pivot high C=103.0 (HH)
    _bucket(bars, 102.7, 102.8, 101.9, 102.3)
    _bucket(bars, 102.3, 102.4, 101.5, 101.9)  # pivot low D=101.5 (HL)
    _bucket(bars, 101.9, 103.5, 101.8, 103.4)  # leg-in
    _bucket(bars, 103.4, 104.0, 103.3, 103.8)  # base -> zone band [103.3, 104.0]
    _bucket(bars, 103.8, 105.6, 103.7, 105.4)  # leg-out (105.4 > 104.0 confirms)
    _bucket(bars, 105.4, 107.1, 105.3, 107.0)
    for _ in range(6):  # away from the band
        bars.append(_bar(len(bars), *PARKED_HIGH))
    return bars


def _downtrend_qm_fixture() -> list[dict]:
    """Bearish Quasimodo on the M15 structure: HH shoulder 102.4, HL
    neckline 100.9, higher-HH head 103.6, confirmed by the close at 100.7
    back through the neckline. H1 (fabricated separately) is in a downtrend,
    so the QM's break re-joins the trend — a QMC sell. The shoulder retest
    is performed by the M1 feed each test builds."""
    bars: list[dict] = []
    for _ in range(14):  # ATR warmup
        _bucket(bars, 100.0, 100.6, 99.4, 100.4)
    _bucket(bars, 100.4, 101.6, 100.2, 101.4)
    _bucket(bars, 101.4, 102.4, 101.2, 102.2)  # shoulder pivot high 102.4 (HH)
    _bucket(bars, 102.2, 102.3, 101.3, 101.6)
    _bucket(bars, 101.6, 101.8, 100.9, 101.2)  # neckline pivot low 100.9 (HL)
    _bucket(bars, 101.2, 103.0, 101.1, 102.8)
    _bucket(bars, 102.8, 103.6, 102.0, 103.2)  # head pivot high 103.6 (HH > shoulder)
    _bucket(bars, 103.2, 103.3, 101.8, 102.0)
    _bucket(bars, 102.0, 102.1, 100.5, 100.7)  # closes 100.7 < neckline -> confirmed
    _bucket(bars, 100.7, 101.0, 100.4, 100.8)  # parked below the shoulder
    return bars


def _h1(trend: str, rows: int = 12) -> pd.DataFrame:
    if trend == "up":
        closes = [100.0 + i for i in range(rows)]
    else:
        closes = [100.0 + rows - i for i in range(rows)]
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes],
            "close": closes,
        }
    )


def _m1_feed(m5_bars: list[dict], rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    """M1 frame whose bars start right after the last M5 bar, one minute
    apart — every zone/QM confirmation time therefore precedes the whole
    M1 feed, so retest tracking scans it from the first row."""
    start = START + len(m5_bars) * STEP
    return pd.DataFrame(
        {
            "time": [start + k * M1_STEP for k in range(len(rows))],
            "open": [r[0] for r in rows],
            "high": [r[1] for r in rows],
            "low": [r[2] for r in rows],
            "close": [r[3] for r in rows],
            "tick_volume": [10] * len(rows),
        }
    )


def _strategy(**param_overrides) -> PobTrendConfluenceXauusdV2:
    strategy = PobTrendConfluenceXauusdV2()
    strategy.spec.params.update(
        {
            "zone_tf_minutes": 15,
            "structure_tf_minutes": 15,
            "htf_trend_ema_period": 5,
            "entry_max_dist_atr_mult": 1.5,
        }
    )
    strategy.spec.params.update(param_overrides)
    return strategy


def _ctx(m5_bars: list[dict], h1: pd.DataFrame, m1: pd.DataFrame) -> MarketContext:
    return MarketContext(
        symbol="XAUUSD",
        candles={"M1": m1, "M5": pd.DataFrame(m5_bars), "H1": h1},
        spread_points=SPREAD_POINTS,
    )


# M1 retest of the RBR band [103.3, 104.0]: a bearish setup bar parked just
# above the band, then a bullish engulfing whose wick dips into it.
RBR_SETUP_BAR = (105.0, 105.1, 104.4, 104.5)
RBR_ENTRY_ENGULF = (104.4, 105.2, 103.9, 105.0)
# In-band bearish body candle that starts an episode without printing a
# confirming *buy* pattern — used to consume episode 1.
RBR_EP_CONSUMER = (105.9, 106.0, 103.9, 104.0)


def test_buy_signal_on_trend_aligned_rbr_retest() -> None:
    m5 = _uptrend_rbr_fixture()
    m1 = _m1_feed(m5, [PARKED_HIGH] * 10 + [RBR_SETUP_BAR, RBR_ENTRY_ENGULF])

    strategy = _strategy()
    signal = strategy.evaluate(_ctx(m5, _h1("up"), m1))

    assert signal is not None
    assert signal.direction is Direction.BUY
    assert signal.pattern == "bullish_engulfing"
    assert signal.zone is not None
    assert signal.zone.kind is ZoneKind.DEMAND
    assert signal.zone.price_low == pytest.approx(103.3)
    assert signal.zone.price_high == pytest.approx(104.0)
    assert "RBR" in signal.reason
    assert "retest_ep=1" in signal.reason
    assert "m15_structure" in signal.reason
    assert signal.structure  # labeled swings attached for the chart

    # SL anchors beyond the zone's far edge (103.3) plus the volatility
    # margin — strictly deeper than the raw close-to-edge distance.
    close = RBR_ENTRY_ENGULF[3]
    assert signal.sl_points > close - 103.3
    # TP is a fixed multiple of the spread-adjusted risk (SpreadGate formula).
    params = strategy.spec.params
    risk = signal.sl_points + SPREAD_POINTS * params["point_value"]
    assert signal.tp_points == pytest.approx(risk * params["tp_rr"])


def test_body_candle_qualifies_as_entry_pattern() -> None:
    # entry_patterns="any": a strong bullish body candle (not an engulfing,
    # not a pin bar) dipping into the band is a valid v2 entry trigger.
    m5 = _uptrend_rbr_fixture()
    body_candle = (104.2, 105.0, 103.95, 104.95)
    m1 = _m1_feed(m5, [PARKED_HIGH] * 10 + [body_candle])

    signal = _strategy().evaluate(_ctx(m5, _h1("up"), m1))

    assert signal is not None
    assert signal.pattern == "bullish_body_candle"


def test_second_retest_episode_allowed() -> None:
    # Episode 1 is consumed by a bearish dip whose entry window (120 M1
    # bars) fully expires; the second touch of the band is episode 2 and
    # still tradeable in v2 (v1 allowed only one episode).
    m5 = _uptrend_rbr_fixture()
    rows = (
        [PARKED_HIGH] * 10
        + [RBR_EP_CONSUMER]
        + [PARKED_HIGH] * 125
        + [RBR_SETUP_BAR, RBR_ENTRY_ENGULF]
    )
    m1 = _m1_feed(m5, rows)

    signal = _strategy().evaluate(_ctx(m5, _h1("up"), m1))

    assert signal is not None
    assert signal.direction is Direction.BUY
    assert "retest_ep=2" in signal.reason


def test_third_retest_episode_rejected() -> None:
    # Two stale episodes already exist — the third touch is beyond
    # max_retest_episodes=2 and must not trade.
    m5 = _uptrend_rbr_fixture()
    rows = (
        [PARKED_HIGH] * 10
        + [RBR_EP_CONSUMER]
        + [PARKED_HIGH] * 125
        + [RBR_EP_CONSUMER]
        + [PARKED_HIGH] * 125
        + [RBR_SETUP_BAR, RBR_ENTRY_ENGULF]
    )
    m1 = _m1_feed(m5, rows)

    assert _strategy().evaluate(_ctx(m5, _h1("up"), m1)) is None


def test_no_signal_on_short_history() -> None:
    short_m5 = [_bar(i, 100.0, 100.6, 99.4, 100.4) for i in range(30)]
    full_m5 = _uptrend_rbr_fixture()
    m1 = _m1_feed(full_m5, [PARKED_HIGH] * 10 + [RBR_SETUP_BAR, RBR_ENTRY_ENGULF])

    # Short analysis feed.
    assert _strategy().evaluate(_ctx(short_m5, _h1("up"), m1)) is None
    # Short entry feed.
    short_m1 = _m1_feed(full_m5, [RBR_SETUP_BAR, RBR_ENTRY_ENGULF])
    assert _strategy().evaluate(_ctx(full_m5, _h1("up"), short_m1)) is None


def test_no_signal_when_h1_trend_misaligned() -> None:
    # Perfect RBR retest in a clean M15 uptrend — but H1 says downtrend, so
    # the demand zone is against the trend and must be skipped.
    m5 = _uptrend_rbr_fixture()
    m1 = _m1_feed(m5, [PARKED_HIGH] * 10 + [RBR_SETUP_BAR, RBR_ENTRY_ENGULF])
    assert _strategy().evaluate(_ctx(m5, _h1("down"), m1)) is None


def test_no_signal_on_wrong_direction_pattern() -> None:
    # A BEARISH engulfing tagging the demand band is not a buy trigger.
    m5 = _uptrend_rbr_fixture()
    bullish_setup = (104.6, 105.2, 104.5, 105.1)
    bearish_engulf = (105.2, 105.3, 103.9, 104.45)
    m1 = _m1_feed(m5, [PARKED_HIGH] * 10 + [bullish_setup, bearish_engulf])
    assert _strategy().evaluate(_ctx(m5, _h1("up"), m1)) is None


def test_sell_signal_on_qm_retest_in_downtrend() -> None:
    m5 = _downtrend_qm_fixture()
    bullish_setup = (101.4, 101.9, 101.3, 101.8)
    bearish_engulf = (101.9, 102.6, 101.2, 101.3)  # tags the 102.4 shoulder
    m1 = _m1_feed(m5, [PARKED_LOW] * 10 + [bullish_setup, bearish_engulf])

    signal = _strategy().evaluate(_ctx(m5, _h1("down"), m1))

    assert signal is not None
    assert signal.direction is Direction.SELL
    assert signal.pattern == "bearish_engulfing"
    assert "QML" in signal.reason
    assert signal.zone is not None
    assert signal.zone.kind is ZoneKind.SUPPLY
    assert signal.zone.price_low == pytest.approx(102.4)  # shoulder
    assert signal.zone.price_high == pytest.approx(103.6)  # head (max pain level)
    # SL anchors beyond the head plus the volatility margin.
    close = bearish_engulf[3]
    assert signal.sl_points > 103.6 - close


def test_no_signal_when_qm_voided_past_head() -> None:
    # An M1 close beyond the head (103.6) after confirmation hits the
    # maximum pain level and voids the QM — the later retest must not trade.
    m5 = _downtrend_qm_fixture()
    void_bar = (101.0, 104.0, 100.9, 103.8)
    pullback = (103.8, 103.9, 101.4, 101.8)
    bullish_setup = (101.4, 101.9, 101.3, 101.8)
    bearish_engulf = (101.9, 102.6, 101.2, 101.3)
    m1 = _m1_feed(
        m5, [PARKED_LOW] * 10 + [void_bar, pullback, bullish_setup, bearish_engulf]
    )
    assert _strategy().evaluate(_ctx(m5, _h1("down"), m1)) is None


def test_spec_shape() -> None:
    strategy = PobTrendConfluenceXauusdV2()
    assert strategy.spec.name == "pob_trend_confluence_xauusd"
    assert strategy.spec.version == 2
    assert strategy.spec.symbols == ("XAUUSD",)
    assert strategy.spec.entry_timeframe == "M1"
    assert strategy.spec.confirmation_timeframes == ("M5", "H1")
    assert strategy.spec.params["tp_rr"] >= 1.55  # headroom over xauusd min_rr 1.5
    assert strategy.spec.params["session_windows"] == ()  # trades all sessions
    assert strategy.spec.params["max_retest_episodes"] == 2


# --- Incremental zone-detection cache: bit-identical proof -----------------
#
# `PobTrendConfluenceXauusdV2._detect_zones_cached` is a timestamp-keyed
# incremental replacement for the stateless `_detect_zones(zone_frame, atr,
# params)` full recompute, replicated from the proven design on
# `pob_snd_zones_xauusd_v1.PobSndZonesXauusd._detect_zones_cached` (see
# OPTIMIZATION_CHECKLIST.md). These tests are the actual proof it's safe: a
# long synthetic walk-forward series is fed through a fixed-size sliding
# window one bar at a time, and at EVERY step the incremental cache's output
# must exactly match a from-scratch `_detect_zones` recompute on the
# identical zone_frame. Called directly on `_detect_zones_cached` (bypassing
# `evaluate()`'s trend-alignment gate) so the cache mechanism itself is
# exercised on every step, not just the subset of bars where Setup A fires.

CONTEXT_BARS = 200  # engine/backtest window size, per the module docstring
ZONE_TF_MINUTES = 30  # production default (see PobTrendConfluenceXauusdV2.__init__)
ATR_PERIOD = 14  # production default


def _make_walk_forward_series(n_bars: int, seed: int) -> list[dict]:
    """Multi-week synthetic M5 OHLC series with regime-switching drift
    (trend-up / trend-down / chop) so the zone-TF-resampled bars produce a
    realistic mix of legs, bases, and weak-run merges — not just noise.
    Skips Saturdays like a real forex/CFD feed, exercising the cache's
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
    (`PobTrendConfluenceXauusdV2._detect_zones_cached`, called on one
    persistent strategy instance so its cache carries forward) produces
    exactly the same zones as the stateless full recompute (`_detect_zones`)
    on the identical zone_frame — not just at the end of the walk."""
    all_bars = _make_walk_forward_series(4200, seed=20260729)
    df_all = pd.DataFrame(all_bars)
    params = PobTrendConfluenceXauusdV2().spec.params
    incremental = PobTrendConfluenceXauusdV2()

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
    params = PobTrendConfluenceXauusdV2().spec.params
    incremental = PobTrendConfluenceXauusdV2()

    bars_walked: list[int] = []
    orig = pob_trend_confluence_xauusd_v2._build_runs_from

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
        mp.setattr(pob_trend_confluence_xauusd_v2, "_build_runs_from", counting)

        bars_walked.clear()
        incremental._detect_zones_cached(zone_frame, zone_end_ns, atr_series, params)
        incremental_bars = sum(bars_walked)

        bars_walked.clear()
        cold = PobTrendConfluenceXauusdV2()
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
