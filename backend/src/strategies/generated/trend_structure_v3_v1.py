"""Trend-structure v3: v2's fresh-swing trigger, but zone-anchored SL and a
structural TP instead of a fixed 2.2 TP:SL ratio.

`trend_structure_v1`/`v2` are pure price-structure (fractal swing pivots
only, no S&D zone concept) with SL anchored to the opposite-kind pivot
between the two swings that confirmed the signal, and TP a fixed `TP_RR=2.2`
multiple of that SL — same shape as `trend_follow_zones_scalp_xauusd_v1.py`'s
parent, `trend_structure_v2`, before that module was merged with
`rbr_dbd_zones_scalp_xauusd_v1.py`'s zone geometry. This is the same merge
applied directly to the `trend_structure` family itself, across its existing
three symbols instead of a single-symbol sibling:

  - Entry trigger unchanged from v2: a freshly confirmed zigzag swing extreme
    (HH for a buy, LL for a sell), with structural alignment (the swing low
    right before a HH must itself be a higher low than the one before that —
    both zigzag legs agree on direction; symmetric for a LL) and a minimum
    amplitude filter (the new extreme must beat the prior same-kind swing by
    at least `min_swing_atr_mult` x ATR, so a 1-tick technical new extreme
    doesn't count as continuation).
  - SL now anchored to the RBR/DBD/RBD/DBR base that actually launched the
    current leg (`_detect_zones`, identical leg-in/base/leg-out detector to
    `rbr_dbd_zones_scalp_xauusd_v1.py`) instead of the raw opposite-kind
    swing pivot — the base must have formed at/after the last opposite-kind
    swing (`leg_start_idx`), and if none exists the signal is skipped; there
    is no non-zone SL fallback.
  - TP is always the nearest unmitigated old high/old low (`_target_swing`)
    instead of the fixed `TP_RR=2.2` multiple — if none exists, the signal is
    skipped rather than guessing a distance. The broker's own `SpreadGate`
    (`configs/symbols/<symbol>.yaml` `min_rr`) still vetoes any trade whose
    resulting RR is too thin.
  - No EMA/indicator trend filter: v1/v2's whole premise is "no external
    indicators — ATR here is a volatility measure derived from the same OHLC
    series, used only to size 'is this move bigger than noise'." v3 keeps
    that: unlike the scalp/swing `trend_follow_zones_*` siblings (which add
    an EMA(20)/EMA(50) HTF filter), this version has no such filter — the
    structural-alignment check on the swing sequence itself is the only
    directional gate, matching the parent family's design.

Symbols, entry timeframe (M5), and empty `confirmation_timeframes` are
unchanged from v1/v2. No live/backtest track record yet — validate with
`/backtest/run` before activating.

Sandbox-safe: only `numpy`/`pandas` — no I/O, no broker access.
"""

import numpy as np
import pandas as pd

from src.strategies.domain.models import (
    Direction,
    MarketContext,
    PriceZone,
    Signal,
    StrategySpec,
    StructureLabel,
    StructurePoint,
    ZoneKind,
)

MIN_HISTORY = 60  # room for ATR(14) warmup plus at least 5 alternating swing pivots


def _true_range_values(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> np.ndarray:
    tr = highs - lows
    if len(tr) > 1:
        gap_high = np.abs(highs[1:] - closes[:-1])
        gap_low = np.abs(lows[1:] - closes[:-1])
        tr[1:] = np.maximum(tr[1:], np.maximum(gap_high, gap_low))
    return tr


def _atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int) -> pd.Series:
    tr = pd.Series(_true_range_values(highs, lows, closes))
    return tr.rolling(period, min_periods=period).mean()


def _swing_flags(highs: np.ndarray, lows: np.ndarray, wing: int) -> tuple[np.ndarray, np.ndarray]:
    n = len(highs)
    is_high = np.zeros(n, dtype=bool)
    is_low = np.zeros(n, dtype=bool)
    window = 2 * wing + 1
    if n >= window:
        window_max = np.lib.stride_tricks.sliding_window_view(highs, window).max(axis=1)
        window_min = np.lib.stride_tricks.sliding_window_view(lows, window).min(axis=1)
        is_high[wing : n - wing] = highs[wing : n - wing] == window_max
        is_low[wing : n - wing] = lows[wing : n - wing] == window_min
    return is_high, is_low


def _push_swing(swings: list[tuple[int, float, str]], index: int, price: float, kind: str) -> None:
    if swings and swings[-1][2] == kind:
        _, prev_price, _ = swings[-1]
        if (kind == "high" and price > prev_price) or (kind == "low" and price < prev_price):
            swings[-1] = (index, price, kind)
        return
    swings.append((index, price, kind))


def _zigzag_swings(highs: np.ndarray, lows: np.ndarray, wing: int) -> list[tuple[int, float, str]]:
    is_high, is_low = _swing_flags(highs, lows, wing)
    swings: list[tuple[int, float, str]] = []
    for i in np.flatnonzero(is_high | is_low):
        index = int(i)
        if is_high[index]:
            _push_swing(swings, index, float(highs[index]), "high")
        if is_low[index]:
            _push_swing(swings, index, float(lows[index]), "low")
    return swings


def _target_swing(
    swings: list[tuple[int, float, str]], close: float, direction: Direction
) -> tuple[float, int] | None:
    """Nearest unmitigated opposite-side swing in the trade's direction: the
    most recent swing high still above price for a buy, or swing low still
    below price for a sell — the "old high" / "old low" the trend is
    expected to run into. No fixed-RR fallback: if none exists, the caller
    skips the trade."""
    kind_needed = "high" if direction == Direction.BUY else "low"
    for index, price, kind in reversed(swings):
        if kind != kind_needed:
            continue
        if direction == Direction.BUY and price > close:
            return price, index
        if direction == Direction.SELL and price < close:
            return price, index
    return None


def _classify_bars(
    closes: np.ndarray, opens: np.ndarray, atr_filled: np.ndarray, base_mult: float
) -> np.ndarray:
    """Vectorized per-bar classification: 0 = base (small body, either
    color); +1/-1 = directional momentum bar. Split out of `_detect_zones`
    to keep it in sync with `TrendStructureV3._detect_zones_cached`."""
    return np.where(
        np.abs(closes - opens) <= base_mult * atr_filled,
        0,
        np.where(closes >= opens, 1, -1),
    )


def _build_runs_from(classes: np.ndarray, start: int, stop: int | None = None) -> list[list[int]]:
    """Group `classes[start:stop]` into consecutive-same-class runs, as
    [cls, start, end] triples of absolute positions. Vectorized (diff +
    flatnonzero) to match this file's existing numpy-array style — used
    both for the full recompute and the head/tail segments in
    `TrendStructureV3._detect_zones_cached`."""
    end_pos = len(classes) if stop is None else stop
    seg = classes[start:end_pos]
    if len(seg) == 0:
        return []
    change = np.flatnonzero(seg[1:] != seg[:-1]) + 1
    seg_starts = np.concatenate(([0], change))
    seg_ends = np.append(change - 1, len(seg) - 1)
    abs_starts = seg_starts + start
    abs_ends = seg_ends + start
    return [
        [int(classes[s]), int(s), int(e)] for s, e in zip(abs_starts, abs_ends, strict=True)
    ]


def _coalesce_adjacent_runs(runs: list[list[int]]) -> list[list[int]]:
    """Re-join directly-adjacent same-class runs at a splice seam (used when
    a cached run-list prefix is stitched to freshly-built head/tail segments
    in `TrendStructureV3._detect_zones_cached`). A from-scratch
    `_build_runs_from` pass never produces two adjacent same-class runs, so
    any that appear at a seam are a splicing artifact, not a real
    boundary — the weak-run merge-loop's 3-run window assumes that
    invariant holds."""
    out: list[list[int]] = []
    for r in runs:
        if out and out[-1][0] == r[0] and out[-1][2] + 1 == r[1]:
            out[-1][2] = r[2]
        else:
            out.append(list(r))
    return out


def _make_is_leg(closes: np.ndarray, opens: np.ndarray, atr_filled: np.ndarray, leg_mult: float):
    def is_leg(run: list[int]) -> bool:
        cls_, start, end = run
        return cls_ != 0 and abs(closes[end] - opens[start]) >= leg_mult * atr_filled[end]

    return is_leg


def _merge_weak_runs(runs: list[list[int]], is_leg, max_base: int) -> list[list[int]]:
    """Fixed-point pass absorbing a short same-color-bracketed base run into
    one leg (see the `_detect_zones` module docstring). Mutates and returns
    `runs`. Cheap even when `runs` includes an already-final cached prefix:
    re-scanning entries that can't merge again is what makes the incremental
    cache exact rather than approximate — see
    `TrendStructureV3._detect_zones_cached`."""
    merged = True
    while merged:
        merged = False
        for k in range(len(runs) - 2):
            d1, pause, d2 = runs[k], runs[k + 1], runs[k + 2]
            if d1[0] == 0 or pause[0] != 0 or d2[0] != d1[0]:
                continue
            if pause[2] - pause[1] + 1 > max_base:
                continue
            if is_leg(d1) and is_leg(d2):
                continue
            runs[k : k + 3] = [[d1[0], d1[1], d2[2]]]
            merged = True
            break
    return runs


def _scan_retest_break(
    demand: bool,
    scan_start: int,
    price_low: float,
    price_high: float,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
) -> tuple[int | None, int | None]:
    if demand:
        touched = lows[scan_start:] <= price_high
        broke = closes[scan_start:] < price_low
    else:
        touched = highs[scan_start:] >= price_low
        broke = closes[scan_start:] > price_high
    touch_hits = np.flatnonzero(touched)
    break_hits = np.flatnonzero(broke)
    broken_idx = int(break_hits[0]) + scan_start if len(break_hits) else None
    retest_idx = None
    if len(touch_hits):
        first_touch = int(touch_hits[0]) + scan_start
        if broken_idx is None or first_touch <= broken_idx:
            retest_idx = first_touch
    return retest_idx, broken_idx


def _build_zones_from_runs(
    runs: list[list[int]],
    is_leg,
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    atr_filled: np.ndarray,
    max_base: int,
    params: dict,
) -> list[dict]:
    """Zone geometry, retest/break tracking, and zone-flip — the whole
    per-leg-pair body of `_detect_zones` (see its docstring), split out so
    both the full recompute and `TrendStructureV3._detect_zones_cached`
    share it. This is an O(window) scan per zone regardless of what's
    cached, so unlike the run-building above it is NOT part of the
    incremental cache — it runs fresh, over the full current window, every
    call: a newly-arrived bar can always start, extend, or break a retest
    episode for ANY still-live zone, not just newly-formed ones, same as the
    M5 retest tracking in the `pob_snd_zones_xauusd_v1.py` reference this
    pattern was replicated from."""
    n = len(closes)
    legs = [r for r in runs if is_leg(r)]

    zones: list[dict] = []
    for k in range(len(legs) - 1):
        leg_in, leg_out = legs[k], legs[k + 1]
        base_start = leg_in[2] + 1
        base_end = leg_out[1] - 1
        base_count = base_end - base_start + 1
        if base_count < 1 or base_count > max_base:
            continue

        price_high = float(highs[base_start : base_end + 1].max())
        price_low = float(lows[base_start : base_end + 1].min())

        leg_out_up = leg_out[0] == 1
        conf_idx = None
        for j in range(leg_out[1], leg_out[2] + 1):
            cleared = (closes[j] > price_high) if leg_out_up else (closes[j] < price_low)
            if cleared:
                conf_idx = j
                break
        if conf_idx is None:
            continue

        if leg_in[0] == 1:
            pattern = "RBR" if leg_out_up else "RBD"
        else:
            pattern = "DBR" if leg_out_up else "DBD"
        demand = leg_out_up

        scan_start = leg_out[2] + 1
        retest_idx, broken_idx = _scan_retest_break(
            demand, scan_start, price_low, price_high, highs, lows, closes
        )

        zones.append(
            {
                "pattern": pattern,
                "kind": ZoneKind.DEMAND if demand else ZoneKind.SUPPLY,
                "price_high": price_high,
                "price_low": price_low,
                "base_start": base_start,
                "conf_idx": conf_idx,
                "leg_out_end": leg_out[2],
                "retest_idx": retest_idx,
                "broken_idx": broken_idx,
                "flipped": False,
            }
        )

        if broken_idx is not None:
            break_body = abs(closes[broken_idx] - opens[broken_idx])
            if break_body >= params["flip_break_body_atr_mult"] * atr_filled[broken_idx]:
                flip_demand = not demand
                flip_scan_start = broken_idx + 1
                if flip_scan_start < n:
                    f_retest, f_broken = _scan_retest_break(
                        flip_demand, flip_scan_start, price_low, price_high, highs, lows, closes
                    )
                    zones.append(
                        {
                            "pattern": f"{pattern}_flip",
                            "kind": ZoneKind.DEMAND if flip_demand else ZoneKind.SUPPLY,
                            "price_high": price_high,
                            "price_low": price_low,
                            "base_start": base_start,
                            "conf_idx": broken_idx,
                            "leg_out_end": broken_idx,
                            "retest_idx": f_retest,
                            "broken_idx": f_broken,
                            "flipped": True,
                        }
                    )
    return zones


def _detect_zones(
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    atr: pd.Series,
    params: dict,
) -> list[dict]:
    """RBR/DBD/RBD/DBR zones over the window, each with an optional flipped
    counterpart appended when a strong candle invalidates it. Identical
    detector to `rbr_dbd_zones_scalp_xauusd_v1.py` — see that module for the
    full mechanics.

    Zone dict fields: pattern, kind, price_high, price_low, base_start,
    conf_idx, leg_out_end, retest_idx, broken_idx, flipped (bool).

    Pure full recompute, O(n) classify + O(runs^2)-ish merge every call —
    this is the stateless ground truth. `TrendStructureV3` uses the
    incremental, cache-backed `_detect_zones_cached` for its own
    (repeatedly-called, sliding-window) `evaluate()` instead; this function
    stays untouched and is available for any other one-shot use / direct
    testing.
    """
    valid_atr = atr.dropna()
    if valid_atr.empty:
        return []
    atr_filled = atr.fillna(valid_atr.iloc[0]).to_numpy()

    base_mult = params["base_body_atr_mult"]
    leg_mult = params["leg_travel_atr_mult"]
    max_base = int(params["max_base_candles"])

    classes = _classify_bars(closes, opens, atr_filled, base_mult)
    runs = _build_runs_from(classes, 0)
    is_leg = _make_is_leg(closes, opens, atr_filled, leg_mult)
    runs = _merge_weak_runs(runs, is_leg, max_base)
    return _build_zones_from_runs(
        runs, is_leg, opens, highs, lows, closes, atr_filled, max_base, params
    )


class TrendStructureV3:
    def __init__(self) -> None:
        self.spec = StrategySpec(
            name="trend_structure_v3",
            version=3,
            symbols=("XAUUSD", "XAGUSD", "BTCUSD"),
            entry_timeframe="M5",
            confirmation_timeframes=(),
            params={
                "pivot_wing": 3,
                "atr_period": 14,
                "min_swing_atr_mult": 0.5,
                "zone_lookback_bars": 200,
                "base_body_atr_mult": 0.5,
                "leg_travel_atr_mult": 0.7,
                "max_base_candles": 3,
                "max_base_atr_mult": 2.0,
                "sl_base_mult": 1.0,
                "min_sl_atr_mult": 0.3,
                "flip_break_body_atr_mult": 1.2,
                "min_confidence": 0.5,
            },
        )
        # Incremental zone-detection cache for `_detect_zones_cached`, keyed
        # on the window's own M5 bar timestamps (int64 ns) rather than
        # position — positions are meaningless across calls because
        # `evaluate()` hands this strategy a fixed-size TRAILING window
        # (`zone_lookback_bars`) that slides forward each call (oldest bar
        # dropped, newest appended) with a fresh 0-based index every time.
        # None until the first successful detection; reset to None whenever
        # a call can't produce a usable ATR (mirrors `_detect_zones`
        # returning `[]` early). Same design as
        # `pob_snd_zones_xauusd_v1.PobSndZonesXauusd._detect_zones_cached`,
        # adapted for a window that's raw M5 bars (no zone-TF resample
        # step, like `pob_snd_zones_vix75_v1.py`): every position's OHLC is
        # that bar's own value and is invariant across calls regardless of
        # where the window starts — only the ATR warmup band (position <
        # atr_period) and the old window's own still-growing last run are
        # excluded from reuse.
        self._zone_cache: dict[str, object] | None = None

    def _detect_zones_cached(
        self,
        opens: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        t_ns: np.ndarray,
        atr: pd.Series,
        params: dict,
    ) -> list[dict]:
        """Incremental, bit-identical replacement for module-level
        `_detect_zones(opens, highs, lows, closes, atr, params)`, exploiting
        that `evaluate()` calls this with a *sliding* window over the same
        M5 bar stream every time (see `__init__`). `t_ns` is the window's
        bar timestamps (int64 ns), positionally aligned 1:1 with
        opens/highs/lows/closes, ascending. There is no zone-TF resample
        step here — the window is raw M5 bars — so every position's OHLC is
        that bar's own value and is invariant across calls regardless of
        where the window starts; only the rolling ATR's NaN-warmup fill
        (`atr.fillna(valid_atr.iloc[0])`, whose fill value is computed over
        bars including position 0) makes a run's classification
        call-variant before position `atr_period`.

        Algorithm per call (see
        `pob_snd_zones_xauusd_v1.PobSndZonesXauusd._detect_zones_cached`
        for the fully-annotated original this was replicated from,
        including why raw pre-merge runs — not post-merge output — must be
        cached: a run that's still last-in-frame can keep growing on a
        later call and flip from "too short to be its own leg" to "a leg",
        which would retroactively invalidate an earlier merge decision if
        that decision had been cached post-merge):
          1. Diff `t_ns` against the previous call's cached array for a
             contiguous prefix match. No match (cold start, session gap,
             non-contiguous jump) -> full recompute, reseed the cache.
          2. Translate the previous call's cached RAW (pre-merge) runs into
             this call's positions; keep a contiguous prefix satisfying
             `atr_period <= start` (ATR warmup) and `end <= overlap_len - 2`
             (excludes the old window's own last position — still
             open/growing as of that call).
          3. Re-run classify+group only over the head (before the cached
             prefix) and tail (after it — newly-appended bars plus the old
             window's still-growing final run).
          4. Splice head + cached raw runs + tail, coalesce any same-class
             seam, then run the weak-run merge-loop and zone-building
             (`_build_zones_from_runs`, including retest/break/flip)
             fresh, in full, over the spliced raw list every call.

        Retest/break/flip tracking (`_build_zones_from_runs`) is NOT
        cached — it's an O(window) scan per zone that must see the full
        current window every call, same as the M5 retest tracking in the
        XAUUSD reference.

        Bit-identical to `_detect_zones(opens, highs, lows, closes, atr,
        params)` on every call — proven by
        `tests/unit/strategies/test_trend_structure_v3.py::test_incremental_cache_matches_full_recompute_every_step`.
        """
        n = len(closes)
        valid_atr = atr.dropna()
        if valid_atr.empty:
            self._zone_cache = None
            return []
        atr_filled = atr.fillna(valid_atr.iloc[0]).to_numpy()

        base_mult = params["base_body_atr_mult"]
        leg_mult = params["leg_travel_atr_mult"]
        max_base = int(params["max_base_candles"])
        atr_period = int(params["atr_period"])

        classes = _classify_bars(closes, opens, atr_filled, base_mult)

        candidates: list[list[int]] = []
        cache = self._zone_cache
        if cache is not None and n:
            old_t = cache["t_ns"]
            if len(old_t):
                p = int(np.searchsorted(old_t, t_ns[0]))
                if 0 <= p < len(old_t):
                    overlap_len = min(len(old_t) - p, n)
                    if np.array_equal(old_t[p : p + overlap_len], t_ns[:overlap_len]):
                        # Exclude any run touching the OLD window's own last
                        # position (index `overlap_len - 1` here) — that run
                        # was still open/growing as of the old call.
                        for cls, s_ns, e_ns in cache["raw_runs"]:
                            s = int(np.searchsorted(t_ns, s_ns))
                            e = int(np.searchsorted(t_ns, e_ns))
                            ok = (
                                s < len(t_ns)
                                and e < len(t_ns)
                                and t_ns[s] == s_ns
                                and t_ns[e] == e_ns
                                and atr_period <= s
                                and e <= overlap_len - 2
                            )
                            if not ok:
                                # Cached runs are position-ordered, so once
                                # we've started collecting a contiguous
                                # trustworthy block, the first one that no
                                # longer fits marks its end; before that,
                                # keep skipping runs too close to position 0
                                # / the ATR warmup edge.
                                if candidates:
                                    break
                                continue
                            candidates.append([cls, s, e])

        if candidates:
            head_runs = _build_runs_from(classes, 0, stop=candidates[0][1])
            tail_runs = _build_runs_from(classes, candidates[-1][2] + 1)
            raw_runs = _coalesce_adjacent_runs(head_runs + candidates + tail_runs)
        else:
            raw_runs = _build_runs_from(classes, 0)

        is_leg = _make_is_leg(closes, opens, atr_filled, leg_mult)
        # `_merge_weak_runs` mutates its input in place — always give it a
        # fresh copy so `raw_runs` (what gets cached) stays pre-merge.
        merged_runs = _merge_weak_runs([list(r) for r in raw_runs], is_leg, max_base)
        zones = _build_zones_from_runs(
            merged_runs, is_leg, opens, highs, lows, closes, atr_filled, max_base, params
        )

        self._zone_cache = {
            "t_ns": t_ns.copy(),
            "raw_runs": [[cls, int(t_ns[s]), int(t_ns[e])] for cls, s, e in raw_runs],
        }
        return zones

    def evaluate(self, ctx: MarketContext) -> Signal | None:
        params = self.spec.params
        df = ctx.candles.get(self.spec.entry_timeframe)
        wing = int(params["pivot_wing"])
        atr_period = int(params["atr_period"])
        lookback = int(params["zone_lookback_bars"])
        min_bars = max(lookback, atr_period * 2 + 10, wing * 2 + 30, MIN_HISTORY)
        if df is None or len(df) < min_bars:
            return None

        opens = df["open"].to_numpy()[-lookback:]
        highs = df["high"].to_numpy()[-lookback:]
        lows = df["low"].to_numpy()[-lookback:]
        closes = df["close"].to_numpy()[-lookback:]
        t_ns = pd.DatetimeIndex(df["time"]).as_unit("ns").asi8[-lookback:]

        swings = _zigzag_swings(highs, lows, wing)
        if len(swings) < 5:
            return None

        # A fractal at index i only confirms once `wing` bars have closed to
        # its right — only act on the bar that confirmation lands on.
        last_index, last_price, last_kind = swings[-1]
        if last_index != len(closes) - 1 - wing:
            return None

        prior_index, prior_price, prior_kind = swings[-3]
        if prior_kind != last_kind:
            return None
        leg_start_idx, sl_ref_price, sl_ref_kind = swings[-2]
        _, context_reference, context_kind = swings[-4]
        if context_kind != sl_ref_kind:
            return None

        if last_kind == "high" and last_price > prior_price:
            # Only a HH inside an established uptrend: the low right before
            # it (swings[-2]) must itself be a higher low than the one
            # before that (swings[-4]) — both legs of the zigzag agree.
            if sl_ref_price <= context_reference:
                return None
            direction, label = Direction.BUY, StructureLabel.HH
        elif last_kind == "low" and last_price < prior_price:
            # Symmetric: the high right before this LL must be a lower high.
            if sl_ref_price >= context_reference:
                return None
            direction, label = Direction.SELL, StructureLabel.LL
        else:
            return None

        atr = _atr(highs, lows, closes, atr_period)
        atr_val = atr.iloc[-1]
        if pd.isna(atr_val) or atr_val <= 0:
            return None
        atr_val = float(atr_val)
        if abs(last_price - prior_price) < atr_val * params["min_swing_atr_mult"]:
            return None  # fresh extreme barely beat the prior one — noise, not a new leg

        # SL anchor: the RBR/DBD/RBD/DBR base that actually launched this
        # fresh leg — i.e. formed at/after the last opposite-kind swing
        # (`leg_start_idx`), not some unrelated older zone.
        zones = self._detect_zones_cached(opens, highs, lows, closes, t_ns, atr, params)
        demand = direction == Direction.BUY
        close = float(closes[-1])
        candidate = None
        for z in reversed(zones):
            if z["broken_idx"] is not None:
                continue
            if (z["kind"] == ZoneKind.DEMAND) != demand:
                continue
            if z["base_start"] < leg_start_idx:
                continue  # not the base this fresh leg launched from
            proximal = z["price_high"] if demand else z["price_low"]
            dist = (close - proximal) if demand else (proximal - close)
            if dist < 0:
                continue  # price hasn't actually cleared this zone yet
            if (z["price_high"] - z["price_low"]) > params["max_base_atr_mult"] * atr_val:
                continue  # sloppy/wide base — lower-quality S&D structure
            candidate = z
            break
        if candidate is None:
            return None  # no RBR/DBD/RBD/DBR base under this leg — no valid SL anchor

        base_height = candidate["price_high"] - candidate["price_low"]
        sl_points = max(base_height * params["sl_base_mult"], atr_val * params["min_sl_atr_mult"])
        if sl_points <= 0:
            return None

        # TP: always the nearest unmitigated old high/old low — no fixed-RR
        # fallback. If price has already run past every recent extreme,
        # there's nothing left to follow, so skip rather than guess a
        # distance.
        target = _target_swing(swings, close, direction)
        if target is None:
            return None
        target_price, target_idx = target
        tp_points = abs(target_price - close)
        if tp_points <= 0:
            return None

        confidence = 0.55
        if candidate["flipped"]:
            confidence -= 0.05
        confidence = min(max(confidence, 0.0), 0.9)
        if confidence < params["min_confidence"]:
            return None

        window_times = df["time"].iloc[-lookback:].reset_index(drop=True)
        zone = PriceZone(
            kind=candidate["kind"],
            price_low=candidate["price_low"],
            price_high=candidate["price_high"],
            time_start=window_times.iloc[candidate["base_start"]],
            time_end=window_times.iloc[len(closes) - 1],
        )
        target_label = StructureLabel.HH if direction == Direction.BUY else StructureLabel.LL
        structure: tuple[StructurePoint, ...] = (
            StructurePoint(time=window_times.iloc[last_index], price=last_price, label=label),
            StructurePoint(
                time=window_times.iloc[target_idx], price=target_price, label=target_label
            ),
        )

        reason = (
            f"{label.value} at {last_price:.5f} (bar {last_index}) beat prior swing "
            f"{prior_price:.5f} (bar {prior_index}) by >= {params['min_swing_atr_mult']}xATR, "
            f"aligned with prior {'HL' if label is StructureLabel.HH else 'LH'}; "
            f"sl_zone={candidate['pattern']}"
            f"[{candidate['price_low']:.5f},{candidate['price_high']:.5f}] "
            f"sl=base_height({base_height:.5f}) "
            f"tp=old_{'high' if direction == Direction.BUY else 'low'}"
            f"@{target_price:.5f}(bar {target_idx}) "
            f"lines: entry={close:.5f} sl_pts={sl_points:.5f} tp_pts={tp_points:.5f}"
        )
        return Signal(
            direction=direction,
            sl_points=float(sl_points),
            tp_points=float(tp_points),
            confidence=float(confidence),
            reason=reason,
            zone=zone,
            pattern=candidate["pattern"],
            structure=structure,
        )
