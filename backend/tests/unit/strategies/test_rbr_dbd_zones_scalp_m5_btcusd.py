"""Unit tests for `rbr_dbd_zones_scalp_m5_btcusd_v1.py` — same fixture shape
as `test_rbr_dbd_zones_scalp_btcusd_v2.py` (the M1 sibling this was ported
from), with M5 entry bars and an M15 confirmation frame instead of M1/M5."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

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
    # Structured confluence readings mirror the boolean votes in the reason
    # string -- additive-only, doesn't affect the vote or reason itself.
    assert len(signal.indicators) == 3
    assert {r.name for r in signal.indicators} == {"RSI", "EMA_FAST_VS_SLOW", "VOLUME"}
    for reading in signal.indicators:
        short = "vol" if reading.name == "VOLUME" else reading.name.split("_")[0].lower()
        assert (f"{short}=True" in signal.reason) == reading.passed


def test_confluence_votes_all_true_on_strong_uptrend_with_rising_volume():
    n = 80
    closes = pd.Series(np.linspace(100.0, 200.0, n))
    volume = pd.Series(np.linspace(100.0, 500.0, n))

    rsi_ok, ema_ok, vol_ok, readings = mod._confluence_votes(closes, volume, Direction.BUY)

    assert rsi_ok is True
    assert ema_ok is True
    assert vol_ok is True
    assert len(readings) == 3
    assert all(r.passed for r in readings)


def test_confluence_votes_default_false_on_flat_series():
    n = 80
    closes = pd.Series([100.0] * n)
    volume = pd.Series([100.0] * n)

    rsi_ok, ema_ok, vol_ok, readings = mod._confluence_votes(closes, volume, Direction.BUY)

    assert rsi_ok is False
    assert ema_ok is False
    assert vol_ok is False
    assert len(readings) == 3
    assert all(not r.passed for r in readings)


def test_spec_version_symbol_and_timeframes():
    spec = mod.RbrDbdZonesScalpM5Btcusd().spec
    assert spec.name == "rbr_dbd_zones_scalp_m5_btcusd"
    assert spec.version == 1
    assert spec.symbols == ("BTCUSD",)
    assert spec.entry_timeframe == "M5"
    assert spec.confirmation_timeframes == ("M15",)


# --- Incremental zone-detection cache: bit-identical proof -----------------
#
# `RbrDbdZonesScalpM5Btcusd._detect_zones_cached` is a timestamp-keyed
# incremental replacement for the stateless `_detect_zones(opens, highs,
# lows, closes, atr, params)` full recompute (see OPTIMIZATION_CHECKLIST.md
# and `pob_snd_zones_xauusd_v1.py` / `pob_snd_zones_vix75_v1.py` for the
# design this replicates). These tests are the actual proof it's safe: a
# long synthetic walk-forward series is fed through a fixed-size sliding
# window (mirroring the engine's `get_candles(symbol, timeframe,
# context_bars)` / the backtest context builder) one bar at a time, and at
# EVERY step the incremental cache's output must exactly match a
# from-scratch `_detect_zones` recompute on the identical window.

CONTEXT_BARS = 200  # zone_lookback_bars production default
ATR_PERIOD = 14  # production default


def _make_walk_forward_series(n_bars: int, seed: int) -> list[dict]:
    """Regime-switching synthetic OHLC series (trend-up / trend-down /
    chop, each lasting a random few-to-twenty bars) so the leg-base-leg
    detector (plus its zone-flip extension) sees a realistic mix of legs,
    bases, weak-run merges, and strong-candle breaks — not just noise."""
    rng = np.random.default_rng(seed)
    bars: list[dict] = []
    price = 20000.0  # roughly BTCUSD-scale magnitude
    regime = 0
    regime_len = 0
    for i in range(n_bars):
        if regime_len <= 0:
            regime = int(rng.choice([-1, 0, 1], p=[0.35, 0.3, 0.35]))
            regime_len = int(rng.integers(4, 20))
        drift = {-1: -35.0, 0: 0.0, 1: 35.0}[regime] * rng.uniform(0.5, 1.5)
        noise = rng.normal(0, 15.0)
        o = price
        c = o + drift + noise
        hi = max(o, c) + abs(rng.normal(0, 8.0))
        lo = min(o, c) - abs(rng.normal(0, 8.0))
        bars.append(_bar(i, o, hi, lo, c))
        price = c
        regime_len -= 1
    return bars


def _zone_fingerprint(zone: dict, times_ns: np.ndarray) -> tuple:
    """Normalize a zone dict for cross-call comparison: positions
    (base_start/conf_idx/leg_out_end/retest_idx/broken_idx) are only
    meaningful within the window that produced them, so translate them to
    the bar's absolute timestamp — the stable identifier — before
    comparing."""

    def t(idx: int | None) -> int | None:
        return None if idx is None else int(times_ns[idx])

    return (
        zone["pattern"],
        zone["kind"],
        round(zone["price_high"], 6),
        round(zone["price_low"], 6),
        t(zone["base_start"]),
        t(zone["conf_idx"]),
        t(zone["leg_out_end"]),
        t(zone["retest_idx"]),
        t(zone["broken_idx"]),
        zone["flipped"],
    )


def test_incremental_cache_matches_full_recompute_every_step() -> None:
    """Walk ~4000 bars forward one bar at a time through a fixed-size
    200-bar sliding window (`zone_lookback_bars`, rolling the window over
    ~19 times), and at EVERY single step assert the incremental cache
    (`RbrDbdZonesScalpM5Btcusd._detect_zones_cached`, called on one
    persistent strategy instance so its cache carries forward) produces
    exactly the same zones as the stateless full recompute
    (`_detect_zones`) on the identical window — not just at the end of the
    walk."""
    all_bars = _make_walk_forward_series(4200, seed=20260729)
    opens_all = np.array([b["open"] for b in all_bars])
    highs_all = np.array([b["high"] for b in all_bars])
    lows_all = np.array([b["low"] for b in all_bars])
    closes_all = np.array([b["close"] for b in all_bars])
    times_all = pd.DatetimeIndex([b["time"] for b in all_bars]).as_unit("ns").asi8

    params = mod.RbrDbdZonesScalpM5Btcusd().spec.params
    incremental = mod.RbrDbdZonesScalpM5Btcusd()

    checked_steps = 0
    found_any_zone = False
    for end in range(CONTEXT_BARS, len(all_bars)):
        sl = slice(end - CONTEXT_BARS, end)
        opens, highs, lows, closes = opens_all[sl], highs_all[sl], lows_all[sl], closes_all[sl]
        times_ns = times_all[sl]
        atr_series = mod._atr(highs, lows, closes, ATR_PERIOD)
        if atr_series.dropna().empty:
            continue

        ground_truth = mod._detect_zones(opens, highs, lows, closes, atr_series, params)
        cached = incremental._detect_zones_cached(
            opens, highs, lows, closes, times_ns, atr_series, params
        )

        gt_fp = [_zone_fingerprint(z, times_ns) for z in ground_truth]
        cached_fp = [_zone_fingerprint(z, times_ns) for z in cached]
        assert cached_fp == gt_fp, f"zone mismatch at window end={end}: {cached_fp} != {gt_fp}"
        checked_steps += 1
        found_any_zone = found_any_zone or bool(ground_truth)

    # Sanity: the walk actually exercised a meaningful number of steps
    # (rolling the 200-bar window over many times), and zones were actually
    # found somewhere along the way — this isn't vacuously passing on empty
    # output the entire walk.
    assert checked_steps > 3900
    assert found_any_zone


def test_incremental_cache_reprocesses_far_fewer_bars_than_full_recompute() -> None:
    """Prove the algorithmic claim from the design (not a wall-clock
    benchmark): in steady state, `_detect_zones_cached`'s classify+run-
    grouping helper (`_build_runs_from`) only walks the ATR-warmup head and
    the newly-appended tail of the window, never the cached middle — while
    a cold instance (no cache yet, e.g. right after engine restart) walks
    the whole thing, exactly like a bare `_detect_zones` recompute would."""
    all_bars = _make_walk_forward_series(1400, seed=99)
    opens_all = np.array([b["open"] for b in all_bars])
    highs_all = np.array([b["high"] for b in all_bars])
    lows_all = np.array([b["low"] for b in all_bars])
    closes_all = np.array([b["close"] for b in all_bars])
    times_all = pd.DatetimeIndex([b["time"] for b in all_bars]).as_unit("ns").asi8

    params = mod.RbrDbdZonesScalpM5Btcusd().spec.params
    incremental = mod.RbrDbdZonesScalpM5Btcusd()

    bars_walked: list[int] = []
    orig = mod._build_runs_from

    def counting(classes, start, stop=None):
        stop_pos = len(classes) if stop is None else stop
        bars_walked.append(max(0, stop_pos - start))
        return orig(classes, start, stop)

    # Warm the cache up over many steady-state steps first, uninstrumented.
    warm_end = CONTEXT_BARS + 600
    for end in range(CONTEXT_BARS, warm_end):
        sl = slice(end - CONTEXT_BARS, end)
        opens, highs, lows, closes = opens_all[sl], highs_all[sl], lows_all[sl], closes_all[sl]
        times_ns = times_all[sl]
        atr_series = mod._atr(highs, lows, closes, ATR_PERIOD)
        if atr_series.dropna().empty:
            continue
        incremental._detect_zones_cached(opens, highs, lows, closes, times_ns, atr_series, params)

    # One more steady-state step, instrumented, compared against a cold
    # (freshly-constructed, no cache) instance evaluating the *identical*
    # window.
    sl = slice(warm_end - CONTEXT_BARS, warm_end)
    opens, highs, lows, closes = opens_all[sl], highs_all[sl], lows_all[sl], closes_all[sl]
    times_ns = times_all[sl]
    atr_series = mod._atr(highs, lows, closes, ATR_PERIOD)
    n_bars_in_window = len(closes)
    assert n_bars_in_window > 0

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(mod, "_build_runs_from", counting)

        bars_walked.clear()
        incremental._detect_zones_cached(opens, highs, lows, closes, times_ns, atr_series, params)
        incremental_bars = sum(bars_walked)

        bars_walked.clear()
        cold = mod.RbrDbdZonesScalpM5Btcusd()
        cold._detect_zones_cached(opens, highs, lows, closes, times_ns, atr_series, params)
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
