"""Unit tests for `rbr_dbd_zones_swing_btcusd_v1.py` — direct port of
`rbr_dbd_zones_swing_xauusd_v1.py` to BTCUSD; same mechanics,
same tests (module/class/symbol swapped)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

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


# ---- incremental zone-detection cache ----------------------------------------
# `RbrDbdZonesSwingBtcusd._detect_zones_cached` (evaluate()'s per-instance,
# incremental replacement for the module-level `_detect_zones`) must be
# bit-identical to a full recompute on every call, and must actually walk
# fewer bars than a cold instance once its cache is warmed up. Same design
# and proof pattern as
# `rbr_dbd_zones_scalp_xauusd_v1.RbrDbdZonesScalpXauusd._detect_zones_cached`
# (see `test_rbr_dbd_zones_scalp_xauusd.py`), since this variant's zone
# geometry+retest+flip logic is incrementally cached the same way.

CONTEXT_BARS = 200  # zone_lookback_bars production default
ATR_PERIOD = 14  # atr_period production default


def _make_walk_forward_series(n_bars: int, seed: int) -> list[dict]:
    """Multi-week synthetic M15 OHLC series with regime-switching drift
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
    comparing."""
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
    """Walk ~4200 M15 bars forward one bar at a time through a fixed-size
    200-bar sliding window (rolling the window over ~19 times), and at
    EVERY single step assert the incremental cache
    (`RbrDbdZonesSwingBtcusd._detect_zones_cached`, called on one persistent
    strategy instance so its cache carries forward) produces exactly the
    same zones as the stateless full recompute (`_detect_zones`) on the
    identical window — not just at the end of the walk."""
    all_bars = _make_walk_forward_series(4200, seed=20260729)
    df_all = pd.DataFrame(all_bars)
    params = mod.RbrDbdZonesSwingBtcusd().spec.params
    incremental = mod.RbrDbdZonesSwingBtcusd()

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
    params = mod.RbrDbdZonesSwingBtcusd().spec.params
    incremental = mod.RbrDbdZonesSwingBtcusd()

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
        cold = mod.RbrDbdZonesSwingBtcusd()
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
