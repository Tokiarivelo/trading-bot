"""Incremental zone-detection cache proof for `pob_snd_zones_fx_v1.py`
(`PobSndZonesFx._detect_zones_cached`) — same two-test pair used to prove
the pattern on the XAUUSD reference
(`tests/unit/strategies/test_pob_snd_zones_xauusd.py`), replicated for this
file's ACTUAL code: unlike the reference, `pob_snd_zones_fx_v1.py` has no
zone-TF resample step (its window is raw M5 bars) and tracks retest/break
inside `_detect_zones` itself rather than on a separate M5 feed. Loaded via
`importlib` from its path, same convention as
`test_pob_snd_zones_v2_strategy.py` (which already covers this file's
`evaluate()` behavior)."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import numpy as np
import pandas as pd
import pytest

_STRATEGY_PATH = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "strategies"
    / "generated"
    / "pob_snd_zones_fx_v1.py"
)

START = datetime(2026, 1, 1, tzinfo=UTC)
STEP = timedelta(minutes=5)


def _load_strategy_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("pob_snd_zones_fx_under_test", _STRATEGY_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = _load_strategy_module()

CONTEXT_BARS = 200  # engine/backtest window size (zone_lookback_bars default)
ATR_PERIOD = 14  # production default


def _make_walk_forward_series(n_bars: int, seed: int) -> list[dict]:
    """Multi-week synthetic M5 OHLC series with regime-switching drift
    (trend-up / trend-down / chop, each lasting a random few-to-twenty
    bars), skipping Saturdays like a real feed — same generator shape as
    the XAUUSD reference's walk-forward test, so this walk also exercises
    the cache's session-gap fallback (no timestamp overlap -> full
    recompute)."""
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


def _zone_fingerprint(zone: dict, t_ns: np.ndarray) -> tuple:
    """Normalize a zone dict for cross-call comparison: positions are only
    meaningful within the window that produced them, so translate them to
    the bar's absolute timestamp — the stable identifier — before
    comparing. Includes retest_idx/broken_idx (translated too, None stays
    None) since this file's zones carry that info directly."""
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
    )


def test_incremental_cache_matches_full_recompute_every_step() -> None:
    """Walk ~4000 M5 bars forward one bar at a time through a fixed-size
    200-bar sliding window (rolling the window over ~19 times), and at
    EVERY single step assert the incremental cache
    (`PobSndZonesFx._detect_zones_cached`, called on one persistent
    strategy instance so its cache carries forward) produces exactly the
    same zones as the stateless full recompute (`_detect_zones`) on the
    identical window — not just at the end of the walk."""
    all_bars = _make_walk_forward_series(4200, seed=20260729)
    df_all = pd.DataFrame(all_bars)
    params = mod.PobSndZonesFx().spec.params
    incremental = mod.PobSndZonesFx()

    checked_steps = 0
    found_any_zone = False
    for end in range(CONTEXT_BARS, len(df_all)):
        window = df_all.iloc[end - CONTEXT_BARS : end].reset_index(drop=True)
        atr = mod._atr(window, ATR_PERIOD)
        if atr.dropna().empty:
            continue
        t_ns = pd.DatetimeIndex(window["time"]).as_unit("ns").asi8

        ground_truth = mod._detect_zones(window, atr, params)
        cached = incremental._detect_zones_cached(window, atr, params)

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
    all_bars = _make_walk_forward_series(1400, seed=100)
    df_all = pd.DataFrame(all_bars)
    params = mod.PobSndZonesFx().spec.params
    incremental = mod.PobSndZonesFx()

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
        atr = mod._atr(window, ATR_PERIOD)
        if atr.dropna().empty:
            continue
        incremental._detect_zones_cached(window, atr, params)

    # One more steady-state step, instrumented, compared against a cold
    # (freshly-constructed, no cache) instance evaluating the *identical*
    # window.
    window = df_all.iloc[warm_end - CONTEXT_BARS : warm_end].reset_index(drop=True)
    atr = mod._atr(window, ATR_PERIOD)
    n_bars_in_window = len(window)
    assert n_bars_in_window > 0

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(mod, "_build_runs_from", counting)

        bars_walked.clear()
        incremental._detect_zones_cached(window, atr, params)
        incremental_bars = sum(bars_walked)

        bars_walked.clear()
        cold = mod.PobSndZonesFx()
        cold._detect_zones_cached(window, atr, params)
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
