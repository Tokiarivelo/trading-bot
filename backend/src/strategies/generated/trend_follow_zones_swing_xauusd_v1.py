"""Trend-follow zone strategy for XAUUSD (M15 entries, H1+H4 trend filter) —
swing tier.

Merges two existing families instead of extending either in isolation:

  - `trend_structure_v2.py`'s entry trigger: a *freshly confirmed* zigzag
    swing extreme (HH for a buy, LL for a sell) whose two most recent
    same-kind legs both agree with the new direction ("structural
    alignment") and which beats the prior same-kind swing by at least
    `min_swing_atr_mult` x ATR ("minimum amplitude" — not a 1-tick technical
    new extreme). This is "follow the newly forming trend": the signal fires
    exactly on the bar the fresh pivot confirms, not on every bar the trend
    happens to still be intact.
  - `rbr_dbd_zones_swing_xauusd_v1.py`'s zone geometry (`_detect_zones`,
    the same leg-in/base/leg-out RBR/DBD/RBD/DBR detector) to find the
    specific zone that launched the *current* leg — i.e. the base between
    the last opposite-kind swing (`swings[-2]`, where the fresh leg started)
    and now — and anchor SL to that zone's base height, exactly like the
    zone-retest strategies do.

What's different from both parents, per the trader's brief:

  - No fixed RR multiple anywhere (`trend_structure_v2` used `TP_RR=2.2`
    unconditionally; `rbr_dbd_zones_*` fell back to a fixed `fallback_rr`
    whenever no swing target existed, gated by a `min_rr_floor`). Here TP is
    *always* the nearest unmitigated opposite-side swing — the last old high
    still above price for a buy, the last old low still below price for a
    sell — found via the same `_target_swing` used by the zone strategies.
    If no such swing exists yet, there is nothing to follow, so the signal is
    skipped rather than inventing a distance. The broker's own `SpreadGate`
    (`configs/symbols/xauusd.yaml` `min_rr`) still vetoes any trade whose
    resulting RR is too thin — that's a downstream safety net, not something
    duplicated here as an artificial floor.
  - SL is mandatory zone-based: if no unbroken RBR/DBD/RBD/DBR base is found
    under the current leg (`base_start >= leg_start_idx`, i.e. the zone
    actually launched this specific swing, not some unrelated older one),
    the signal is skipped — there is no non-zone SL fallback.
  - There is no live post-entry trail: `Strategy.evaluate()` is a stateless
    one-shot call with no callback once a position is open (see
    `backend/src/engine/application/position_manager.py` — the only
    post-entry logic is engine-level breakeven-at-+1R and a 4h time-stop,
    both out of scope for strategy code per project rules). "Close when
    price meets the old high/low" is realized as a normal broker TP order
    placed exactly at that swing price at entry time — MT5 closes the
    position itself when price reaches it.

New strategy, no live/backtest track record yet — validate with
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


def _trend_direction(ctx: MarketContext, params: dict) -> str | None:
    """EMA fast-vs-slow trend on `trend_timeframe`; None while history is
    insufficient (skip the filter rather than block every trade)."""
    df = ctx.candles.get(str(params["trend_timeframe"]))
    slow = int(params["trend_slow_period"])
    if df is None or len(df) < slow + 1:
        return None
    closes = df["close"]
    fast_ema = closes.ewm(span=int(params["trend_fast_period"]), adjust=False).mean().iloc[-1]
    slow_ema = closes.ewm(span=slow, adjust=False).mean().iloc[-1]
    if fast_ema > slow_ema:
        return "up"
    if fast_ema < slow_ema:
        return "down"
    return None


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
    so `TrendFollowZonesSwingXauusd._detect_zones_cached` can reuse it —
    keep the two in sync (same rule as `pob_snd_zones_xauusd_v1`)."""
    body = np.abs(closes - opens)
    return np.where(body <= base_mult * atr_filled, 0, np.where(closes >= opens, 1, -1))


def _build_runs_from(classes: np.ndarray, start: int, stop: int | None = None) -> list[list[int]]:
    """Group `classes[start:stop]` into consecutive-same-class runs, as
    [cls, start, end] triples of absolute positions — vectorized (matches
    this module's existing style, unlike the plain-Python-loop version in
    `pob_snd_zones_xauusd_v1`)."""
    end_pos = len(classes) if stop is None else stop
    if end_pos <= start:
        return []
    seg = classes[start:end_pos]
    change = np.flatnonzero(seg[1:] != seg[:-1]) + 1
    starts = np.concatenate(([0], change)) + start
    ends = np.concatenate((change - 1, [len(seg) - 1])) + start
    return [[int(classes[s]), int(s), int(e)] for s, e in zip(starts, ends, strict=True)]


def _coalesce_adjacent_runs(runs: list[list[int]]) -> list[list[int]]:
    """Re-join directly-adjacent same-class runs at a splice seam (used
    when a cached run-list prefix is stitched to freshly-built head/tail
    segments in `TrendFollowZonesSwingXauusd._detect_zones_cached`) — see
    `pob_snd_zones_xauusd_v1._coalesce_adjacent_runs` for the full
    rationale."""
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
    one leg. Mutates and returns `runs` — see
    `pob_snd_zones_xauusd_v1._merge_weak_runs` for why re-scanning an
    already-final cached prefix is what keeps the incremental cache exact."""
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
    """RBR/DBD/RBD/DBR zones from a run list, each with an optional flipped
    counterpart appended when a strong candle invalidates it. Retest/break
    scanning and flip generation are cheap vectorized scans over the full
    window and run fresh every call — never cached — only the run
    classification/grouping that produced `runs` is ever cached (see
    `TrendFollowZonesSwingXauusd._detect_zones_cached`).

    Zone dict fields: pattern, kind, price_high, price_low, base_start,
    conf_idx, leg_out_end, retest_idx, broken_idx, flipped (bool).
    """
    n = len(closes)
    legs = [r for r in runs if is_leg(r)]

    def _scan_retest_break(demand: bool, scan_start: int, price_low: float, price_high: float):
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
        retest_idx, broken_idx = _scan_retest_break(demand, scan_start, price_low, price_high)

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
                        flip_demand, flip_scan_start, price_low, price_high
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
    detector to `rbr_dbd_zones_swing_xauusd_v1.py` — see that module for the
    full mechanics.

    Pure full recompute every call — the stateless ground truth.
    `TrendFollowZonesSwingXauusd.evaluate()` uses the incremental,
    cache-backed `_detect_zones_cached` instead for its own
    (repeatedly-called, sliding-window) zone detection; this function stays
    untouched for any other one-shot use.
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


class TrendFollowZonesSwingXauusd:
    def __init__(self) -> None:
        self.spec = StrategySpec(
            name="trend_follow_zones_swing_xauusd",
            version=1,
            symbols=("XAUUSD",),
            entry_timeframe="M15",
            confirmation_timeframes=("H1", "H4"),
            params={
                "pivot_wing": 3,
                "atr_period": 14,
                "min_swing_atr_mult": 0.5,
                "zone_lookback_bars": 200,
                "base_body_atr_mult": 0.65,
                "leg_travel_atr_mult": 0.8,
                "max_base_candles": 3,
                "max_base_atr_mult": 2.0,
                "sl_base_mult": 1.0,
                "min_sl_atr_mult": 0.3,
                "flip_break_body_atr_mult": 1.3,
                "min_confidence": 0.5,
                "trend_timeframe": "H1",
                "trend_fast_period": 20,
                "trend_slow_period": 50,
            },
        )
        # Incremental zone-detection cache for `_detect_zones_cached`, keyed
        # on the window's own bar timestamps (int64 ns) — there is no
        # zone-TF resample step here (unlike `pob_snd_zones_xauusd_v1`):
        # `evaluate()` hands this a raw trailing slice of the entry
        # timeframe (`zone_lookback_bars` M15 candles, oldest dropped /
        # newest appended each call), so each position's own bar timestamp
        # is the stable identifier instead of a resampled bucket's end
        # time. None until the first successful detection; reset to None
        # whenever a call can't produce a usable ATR.
        self._zone_cache: dict[str, object] | None = None

    def _detect_zones_cached(
        self,
        times_ns: np.ndarray,
        opens: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        atr: pd.Series,
        params: dict,
    ) -> list[dict]:
        """Incremental, bit-identical replacement for module-level
        `_detect_zones(opens, highs, lows, closes, atr, params)`,
        exploiting that `evaluate()` calls this with a *sliding* trailing
        window (`zone_lookback_bars` M15 candles) every time — see
        `__init__`. Same design as
        `pob_snd_zones_xauusd_v1.PobSndZonesXauusd._detect_zones_cached`
        (see that docstring for the full four-step design and the
        pre-merge-vs-post-merge correctness argument), adapted for a
        window that is a raw trailing slice rather than a resampled zone
        frame:

        Stability invariant this relies on: unlike a resampled bucket,
        every position here is a genuine, complete M15 candle regardless
        of where it falls in the window — there is no "partial bucket"
        risk. What IS call-dependent is `_true_range_values`: position 0
        of any window has no predecessor inside the array, so its TR is
        just `high[0] - low[0]` (no gap-vs-prior-close term), whereas that
        SAME absolute bar, once the window has slid forward and it's no
        longer position 0, gets a gap-aware TR against its true
        predecessor. So a bar's classification is only call-invariant once
        it's no longer position 0 — exactly mirroring the resampled
        version's "position 0 may be a truncated bucket" case. The rolling
        ATR pushes that boundary out further, the same way: `_atr`'s
        `rolling(period, min_periods=period)` needs `atr_period` bars of
        lookback, and the NaN warmup is filled with the first valid value
        (`atr.fillna(valid_atr.iloc[0])`) — itself computed from bars
        including position 0 — so classification only becomes
        call-invariant from position `atr_period` onward, not position 1.

        Retest/break tracking and flip-zone generation
        (`_build_zones_from_runs`'s `_scan_retest_break` + the flip block)
        are NOT cached — they're cheap vectorized scans over the current
        window's full tail and must see every newly-appended bar, so they
        run fresh, in full, every call, exactly like the merge-loop and
        leg/zone-building. Only the run classification/grouping upstream
        of that is ever cached.

        Bit-identical to `_detect_zones(opens, highs, lows, closes, atr,
        params)` on every call — proven by
        `tests/unit/strategies/test_trend_follow_zones_swing_xauusd.py::test_incremental_cache_matches_full_recompute_every_step`.
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
            old_times = cache["times"]
            if len(old_times):
                p = int(np.searchsorted(old_times, times_ns[0]))
                if 0 <= p < len(old_times):
                    overlap_len = min(len(old_times) - p, n)
                    if np.array_equal(old_times[p : p + overlap_len], times_ns[:overlap_len]):
                        for cls, s_t, e_t in cache["raw_runs"]:
                            s = int(np.searchsorted(times_ns, s_t))
                            e = int(np.searchsorted(times_ns, e_t))
                            ok = (
                                s < len(times_ns)
                                and e < len(times_ns)
                                and times_ns[s] == s_t
                                and times_ns[e] == e_t
                                and atr_period <= s
                                and e <= overlap_len - 2
                            )
                            if not ok:
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
            "times": times_ns.copy(),
            "raw_runs": [[cls, int(times_ns[s]), int(times_ns[e])] for cls, s, e in raw_runs],
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
        times_ns = pd.DatetimeIndex(df["time"]).as_unit("ns").asi8[-lookback:]

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

        trend = _trend_direction(ctx, params)
        expected = "up" if direction == Direction.BUY else "down"
        if trend is not None and trend != expected:
            return None  # counter-trend — engine HTF veto would kill it anyway

        # SL anchor: the RBR/DBD/RBD/DBR base that actually launched this
        # fresh leg — i.e. formed at/after the last opposite-kind swing
        # (`leg_start_idx`), not some unrelated older zone.
        zones = self._detect_zones_cached(times_ns, opens, highs, lows, closes, atr, params)
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
        if trend is not None:
            confidence += 0.1
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
            f"trend={trend or 'n/a'} "
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
