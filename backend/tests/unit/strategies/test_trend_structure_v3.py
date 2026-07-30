"""Unit tests for `trend_structure_v3.py` — v2's fresh-swing entry trigger,
but SL anchored to the RBR/DBD/RBD/DBR base that launched the current leg
and TP always the nearest unmitigated old high/old low (no fixed TP_RR=2.2
fallback). Same fixtures as `test_trend_follow_zones_scalp_xauusd.py` since
the merge is identical; only the entry timeframe (M5, matching v1/v2) and
the absence of an EMA trend filter (v1/v2's family has none) differ."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

import src.strategies.generated.trend_structure_v3_v1 as mod
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
    strategy = mod.TrendStructureV3()
    ctx = MarketContext(symbol="XAUUSD", candles={"M5": _buy_case()}, spread_points=1.0)
    signal = strategy.evaluate(ctx)
    assert signal is not None
    assert signal.direction == Direction.BUY
    assert signal.zone is not None
    assert signal.zone.kind == ZoneKind.DEMAND
    assert signal.pattern == "RBR"
    assert signal.sl_points > 0.8
    assert signal.sl_points == pytest.approx(0.8207142857142865, rel=1e-6)
    assert signal.tp_points > 0
    assert "sl_zone=RBR" in signal.reason
    assert "tp=old_high" in signal.reason


def test_evaluate_sells_on_fresh_ll_with_dbd_base_sl():
    strategy = mod.TrendStructureV3()
    ctx = MarketContext(symbol="XAUUSD", candles={"M5": _sell_case()}, spread_points=1.0)
    signal = strategy.evaluate(ctx)
    assert signal is not None
    assert signal.direction == Direction.SELL
    assert signal.zone is not None
    assert signal.zone.kind == ZoneKind.SUPPLY
    assert signal.pattern == "DBD"
    assert "sl_zone=DBD" in signal.reason
    assert "tp=old_low" in signal.reason


def test_no_fixed_rr_fallback_in_params():
    """The whole point of v3 vs. v1/v2: no fixed TP_RR anywhere in params."""
    params = mod.TrendStructureV3().spec.params
    assert "tp_rr" not in params
    assert "fallback_rr" not in params
    assert "min_rr_floor" not in params


def test_covers_all_three_symbols_matching_v1_v2():
    spec = mod.TrendStructureV3().spec
    assert set(spec.symbols) == {"XAUUSD", "XAGUSD", "BTCUSD"}
    assert spec.entry_timeframe == "M5"
    assert spec.version == 3


# ---- evaluate: negative paths -------------------------------------------------


def test_evaluate_none_without_a_launching_zone():
    """Structurally valid fresh HH, but no RBR/DBD/RBD/DBR base under the
    final leg to anchor SL to — must skip, not fall back to the raw
    swing-pivot SL v1/v2 used."""
    strategy = mod.TrendStructureV3()
    ctx = MarketContext(symbol="XAUUSD", candles={"M5": _no_zone_case()}, spread_points=1.0)
    assert strategy.evaluate(ctx) is None


def test_evaluate_none_on_short_history():
    strategy = mod.TrendStructureV3()
    ctx = MarketContext(symbol="XAUUSD", candles={"M5": _buy_case().iloc[:50]}, spread_points=1.0)
    assert strategy.evaluate(ctx) is None


# ---- helper functions ---------------------------------------------------------


def test_target_swing_returns_none_when_no_unmitigated_extreme():
    swings = [(10, 90.0, "high"), (20, 80.0, "low")]
    assert mod._target_swing(swings, close=95.0, direction=Direction.BUY) is None


def test_target_swing_finds_nearest_old_high_for_buy():
    swings = [(10, 90.0, "high"), (20, 80.0, "low"), (30, 100.0, "high")]
    target = mod._target_swing(swings, close=85.0, direction=Direction.BUY)
    assert target == (100.0, 30)


# --- Incremental zone-detection cache: bit-identical proof -----------------
#
# `TrendStructureV3._detect_zones_cached` is a timestamp-keyed incremental
# replacement for the stateless `_detect_zones(opens, highs, lows, closes,
# atr, params)` full recompute, replicated from
# `pob_snd_zones_xauusd_v1.PobSndZonesXauusd._detect_zones_cached` (see
# OPTIMIZATION_CHECKLIST.md). `_detect_zones` here is identical to
# `rbr_dbd_zones_scalp_xauusd_v1.py`'s (used only for the SL-anchor zone
# lookup, not the entry trigger itself — the swing/structure check gates
# entries), so these tests call `_detect_zones_cached` directly on a
# persistent strategy instance across a rolling window, exactly like the
# reference proof, rather than going through `evaluate()` (which only
# reaches zone detection on bars where a fresh swing already confirmed).
# This file has no zone-TF resample step (window = raw M5 bars) and already
# does retest/break/flip tracking as an O(window) scan inside zone-building
# (`_build_zones_from_runs`), so — like `pob_snd_zones_vix75_v1.py` — that
# part runs fresh every call, uncached; only the classify+run-grouping step
# is incrementally cached.

CONTEXT_BARS = 200  # zone_lookback_bars production default
ATR_PERIOD = 14  # atr_period production default


def _make_walk_forward_series(n_bars: int, seed: int) -> list[dict]:
    """Multi-week synthetic M5 OHLC series with regime-switching drift
    (trend-up / trend-down / chop, each lasting a random few-to-twenty
    bars), skipping Saturdays like a real feed, so the walk also exercises
    the cache's session-gap fallback (no timestamp overlap -> full
    recompute)."""
    rng = np.random.default_rng(seed)
    bars: list[dict] = []
    t = START
    price = 2000.0  # roughly gold-scale magnitude
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


def _zone_fingerprint(zone: dict, t_ns: np.ndarray) -> tuple:
    """Normalize a zone dict for cross-call comparison: positions are only
    meaningful within the window that produced them, so translate them to
    the bar's absolute timestamp — the stable identifier — before
    comparing. Includes retest_idx/broken_idx/flipped since this file's
    zones carry that info directly (no separate retest-tracking pass)."""
    return (
        zone["pattern"],
        zone["kind"],
        round(zone["price_high"], 6),
        round(zone["price_low"], 6),
        int(t_ns[zone["base_start"]]),
        int(t_ns[zone["conf_idx"]]),
        int(t_ns[zone["leg_out_end"]]),
        int(t_ns[zone["retest_idx"]]) if zone["retest_idx"] is not None else None,
        int(t_ns[zone["broken_idx"]]) if zone["broken_idx"] is not None else None,
        zone["flipped"],
    )


def test_incremental_cache_matches_full_recompute_every_step() -> None:
    """Walk ~4000 M5 bars forward one bar at a time through a fixed-size
    200-bar sliding window (rolling the window over ~19 times), and at
    EVERY single step assert the incremental cache
    (`TrendStructureV3._detect_zones_cached`, called on one persistent
    strategy instance so its cache carries forward) produces exactly the
    same zones as the stateless full recompute (`_detect_zones`) on the
    identical window — not just at the end of the walk."""
    all_bars = _make_walk_forward_series(4200, seed=20260729)
    df_all = pd.DataFrame(all_bars)
    params = mod.TrendStructureV3().spec.params
    incremental = mod.TrendStructureV3()

    checked_steps = 0
    found_any_zone = False
    for end in range(CONTEXT_BARS, len(df_all)):
        window = df_all.iloc[end - CONTEXT_BARS : end].reset_index(drop=True)
        opens = window["open"].to_numpy()
        highs = window["high"].to_numpy()
        lows = window["low"].to_numpy()
        closes = window["close"].to_numpy()
        t_ns = pd.DatetimeIndex(window["time"]).as_unit("ns").asi8
        atr = mod._atr(highs, lows, closes, ATR_PERIOD)
        if atr.dropna().empty:
            continue

        ground_truth = mod._detect_zones(opens, highs, lows, closes, atr, params)
        cached = incremental._detect_zones_cached(opens, highs, lows, closes, t_ns, atr, params)

        gt_fp = [_zone_fingerprint(z, t_ns) for z in ground_truth]
        cached_fp = [_zone_fingerprint(z, t_ns) for z in cached]
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
    the newly-appended tail of the window, never the cached middle — while
    a cold instance (no cache yet, e.g. right after engine restart) walks
    the whole thing, exactly like a bare `_detect_zones` recompute would."""
    all_bars = _make_walk_forward_series(1400, seed=101)
    df_all = pd.DataFrame(all_bars)
    params = mod.TrendStructureV3().spec.params
    incremental = mod.TrendStructureV3()

    bars_walked: list[int] = []
    orig = mod._build_runs_from

    def counting(classes, start, stop=None):
        stop_pos = len(classes) if stop is None else stop
        bars_walked.append(max(0, stop_pos - start))
        return orig(classes, start, stop)

    # Warm the cache up over many steady-state steps first, uninstrumented.
    warm_end = CONTEXT_BARS + 600
    for end in range(CONTEXT_BARS, warm_end):
        window = df_all.iloc[end - CONTEXT_BARS : end].reset_index(drop=True)
        opens = window["open"].to_numpy()
        highs = window["high"].to_numpy()
        lows = window["low"].to_numpy()
        closes = window["close"].to_numpy()
        t_ns = pd.DatetimeIndex(window["time"]).as_unit("ns").asi8
        atr = mod._atr(highs, lows, closes, ATR_PERIOD)
        if atr.dropna().empty:
            continue
        incremental._detect_zones_cached(opens, highs, lows, closes, t_ns, atr, params)

    # One more steady-state step, instrumented, compared against a cold
    # (freshly-constructed, no cache) instance evaluating the *identical*
    # window.
    window = df_all.iloc[warm_end - CONTEXT_BARS : warm_end].reset_index(drop=True)
    opens = window["open"].to_numpy()
    highs = window["high"].to_numpy()
    lows = window["low"].to_numpy()
    closes = window["close"].to_numpy()
    t_ns = pd.DatetimeIndex(window["time"]).as_unit("ns").asi8
    atr = mod._atr(highs, lows, closes, ATR_PERIOD)
    n_bars_in_window = len(closes)
    assert n_bars_in_window > 0

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(mod, "_build_runs_from", counting)

        bars_walked.clear()
        incremental._detect_zones_cached(opens, highs, lows, closes, t_ns, atr, params)
        incremental_bars = sum(bars_walked)

        bars_walked.clear()
        cold = mod.TrendStructureV3()
        cold._detect_zones_cached(opens, highs, lows, closes, t_ns, atr, params)
        cold_bars = sum(bars_walked)

    # Cold (no cache yet) always falls back to a full recompute: every bar
    # in the window goes through the classify+group loop, same as
    # `_detect_zones` would process unconditionally.
    assert cold_bars == n_bars_in_window
    # The warmed-up incremental instance reprocesses strictly fewer bars —
    # only the ATR-warmup head (`atr_period` bars, never cacheable) plus the
    # newly-appended tail, not the whole window.
    assert incremental_bars < cold_bars
    assert incremental_bars <= n_bars_in_window * 0.75
