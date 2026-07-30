"""RBR/DBD/RBD/DBR zone-retest scalp strategy for Volatility 75 Index — M1
entry, no engine HTF veto (`spec.htf_veto=False`; the engine no longer applies
its automatic next-timeframe-up trend veto to this bot at all).

Forked from `rbr_dbd_zones_scalp_vix75_v1.py` (same zone-detection engine,
same SL/TP mechanics — see that module for the full derivation). The one
structural change: the hard M5 trend veto ("counter-trend setup -> return
None") is replaced with a *soft* trend-alignment term inside the confidence
score (`counter_trend_penalty`). Two things motivated this:

  1. Live monitoring on 2026-07-19 showed the bot's own M5 trend filter and
     the (then-existing) engine H1/H4 veto disagreeing with each other often
     enough that a well-formed, in-range, freshly-retested zone sat unusable
     for hours because ONE of the two independent trend gates opposed it.
     After the engine veto became per-bot (`Timeframe.next_up(entry_timeframe)`
     — for an M1 bot, that's M5, the same timeframe/EMA periods this
     strategy's own filter already uses), the two gates became literally
     redundant for M1 bots. Turning the engine veto off here (`htf_veto=False`)
     and keeping only this strategy's own scoring removes the redundancy
     without reintroducing the multi-timeframe conflict problem.
  2. A hard trend veto throws away the zone-quality signal entirely on a
     borderline call: a continuation pattern (RBR/DBD) with 2/2 MTF
     confirmations and a fresh engulfing retest is a fundamentally different
     "counter-trend" setup than a reversal pattern with a stale retest and no
     confirmations — a hard veto can't tell them apart, a scored penalty can.

Zone validity — what "memorized" distinguishes a tradeable zone from a dead
one, restated explicitly here (all independently necessary, tuned via a
24-combo grid sweep — `retest_max_age_bars` x `entry_max_dist_atr_mult` x
`counter_trend_penalty` — run across three full separate months of VIX75 M1
history (2026-05, 2026-06, 2026-07 individually, not concatenated) so the
picked values aren't a single-period fit. Every one of the 24 combos was
profitable in all 3 months; the values below are the Pareto-best cell —
most trades AND best cross-period floor (min profit factor), not merely the
single highest average:
  - unbroken: a strong opposite-direction candle already closing through it
    invalidates it outright (or flips its polarity — see `_detect_zones`).
  - fresh retest: price actually touched the zone's proximal edge within the
    last `retest_max_age_bars` (10) M1 bars. A zone nobody has come back to
    test yet isn't "invalid", it just isn't due — this is re-checked every
    bar, so it becomes eligible the instant a touch happens. 10 (vs the
    original 2) was the widest value swept and still the best on every axis
    (trade count, avg PF, worst-period PF) — the sweep didn't find a ceiling
    within the tested range.
  - in range: within `entry_max_dist_atr_mult` (4.0, also the widest value
    swept) x ATR of the proximal edge — a zone price is nowhere near is not
    a live decision, however well-formed.
  - tight base: `price_high - price_low <= max_base_atr_mult x ATR` — a
    sloppy/wide base is lower-quality S&D structure (this was true on the
    XAUUSD derivation this strategy was ported from and re-confirmed here;
    not re-swept, already validated).
  - entry trigger: an engulfing candle at the proximal edge, classified
    before zone matching so a fresh-but-misaligned zone never masks a valid
    aligned one on the same bar.
  - RR floor: TP (nearest unmitigated opposite swing, or a capped RR
    fallback) must clear `min_rr_floor x SL`.
  - trend alignment is scored, never gated: `counter_trend_penalty=0.0` won
    the sweep outright — at retest=10/dist=4.0 it beat every non-zero
    penalty on trade count (1175 vs <=881) AND on both average PF (1.82) and
    worst-period PF (1.63, the best worst-case of all 24 combos). A stronger
    penalty (up to 1.0, effectively a hard veto again) squeezed out a
    marginally higher average PF (1.87) at less than half the trade count —
    rejected as contrary to "always trade M1" and barely better on quality.

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

# Volatility 75 Index point size (configs/symbols/volatility 75 index.yaml) —
# converts ctx.spread_points (raw broker points) into a price distance so the
# spread cost can be added to the TP floor below (same formula SpreadGate
# applies at the broker gate: tp >= min_rr * (sl + spread)), instead of
# relying on fallback_rr/min_rr_floor headroom over sl_points alone to
# happen to clear live spread.
POINT_VALUE = 0.01


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


def _is_bullish_engulfing(opens: np.ndarray, closes: np.ndarray, i: int) -> bool:
    if i < 1:
        return False
    prev_o, prev_c = opens[i - 1], closes[i - 1]
    o, c = opens[i], closes[i]
    if not (prev_c < prev_o and c > o):
        return False
    return bool(o <= prev_c and c >= prev_o)


def _is_bearish_engulfing(opens: np.ndarray, closes: np.ndarray, i: int) -> bool:
    if i < 1:
        return False
    prev_o, prev_c = opens[i - 1], closes[i - 1]
    o, c = opens[i], closes[i]
    if not (prev_c > prev_o and c < o):
        return False
    return bool(o >= prev_c and c <= prev_o)


def _body_candle_side(
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    i: int,
    min_body_ratio: float,
) -> tuple[bool, str]:
    rng = highs[i] - lows[i]
    if rng <= 0:
        return False, ""
    if abs(closes[i] - opens[i]) / rng < min_body_ratio:
        return False, ""
    return True, ("up" if closes[i] > opens[i] else "down")


def _is_pin_bar(
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    i: int,
    max_body_ratio: float,
    min_wick_body_mult: float,
) -> tuple[bool, str]:
    rng = highs[i] - lows[i]
    if rng <= 0:
        return False, ""
    o, h, lo, c = opens[i], highs[i], lows[i], closes[i]
    body = abs(c - o)
    if body / rng > max_body_ratio:
        return False, ""
    body_floor = max(body, rng * 0.05)
    lower_wick = min(o, c) - lo
    upper_wick = h - max(o, c)
    if lower_wick >= min_wick_body_mult * body_floor and lower_wick > upper_wick:
        return True, "up"
    if upper_wick >= min_wick_body_mult * body_floor and upper_wick > lower_wick:
        return True, "down"
    return False, ""


def _classify_pattern(
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    i: int,
    params: dict,
) -> tuple[str | None, str | None]:
    if _is_bullish_engulfing(opens, closes, i):
        return "bullish_engulfing", "up"
    if _is_bearish_engulfing(opens, closes, i):
        return "bearish_engulfing", "down"
    is_pin, pin_side = _is_pin_bar(
        opens, highs, lows, closes, i,
        params["pin_bar_max_body_ratio"], params["pin_bar_min_wick_mult"],
    )
    if is_pin:
        return f"{'bullish' if pin_side == 'up' else 'bearish'}_pin_bar", pin_side
    strong, side = _body_candle_side(opens, highs, lows, closes, i, params["engulf_min_body_ratio"])
    if strong:
        return f"{'bullish' if side == 'up' else 'bearish'}_body_candle", side
    return None, None


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


def _mtf_confirms(ctx: MarketContext, tf: str, direction: Direction, params: dict) -> bool:
    df = ctx.candles.get(tf)
    lookback = int(params["confirm_lookback"])
    if df is None or len(df) < lookback + 2:
        return False
    opens = df["open"].to_numpy()
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    closes = df["close"].to_numpy()
    start_i = len(df) - lookback
    for i in range(start_i, len(df)):
        if direction == Direction.BUY:
            if _is_bullish_engulfing(opens, closes, i):
                return True
            strong, side = _body_candle_side(
                opens, highs, lows, closes, i, params["mtf_min_body_ratio"]
            )
            if strong and side == "up":
                return True
        else:
            if _is_bearish_engulfing(opens, closes, i):
                return True
            strong, side = _body_candle_side(
                opens, highs, lows, closes, i, params["mtf_min_body_ratio"]
            )
            if strong and side == "down":
                return True
    return False


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
    below price for a sell. Recomputed fresh every bar, so a target found
    right after a zone flip already belongs to the newly forming trend."""
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
    to keep it in sync with `RbrDbdZonesScalpVix75Noveto._detect_zones_cached`."""
    return np.where(
        np.abs(closes - opens) <= base_mult * atr_filled,
        0,
        np.where(closes >= opens, 1, -1),
    )


def _build_runs_from(classes: np.ndarray, start: int, stop: int | None = None) -> list[list[int]]:
    """Group `classes[start:stop]` into consecutive-same-class runs, as
    [cls, start, end] triples of absolute positions. Vectorized (diff +
    flatnonzero) to match this file's existing numpy-array style — used both
    for the full recompute and the head/tail segments in
    `RbrDbdZonesScalpVix75Noveto._detect_zones_cached`."""
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
    """Re-join directly-adjacent same-class runs at a splice seam (used
    when a cached run-list prefix is stitched to freshly-built head/tail
    segments in `RbrDbdZonesScalpVix75Noveto._detect_zones_cached`). A
    from-scratch `_build_runs_from` pass never produces two adjacent
    same-class runs, so any that appear at a seam are a splicing artifact,
    not a real boundary — the weak-run merge-loop's 3-run window assumes
    that invariant holds."""
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
    one leg. Mutates and returns `runs`. Cheap even when `runs` includes an
    already-final cached prefix: re-scanning entries that can't merge again
    is what makes the incremental cache exact rather than approximate — see
    `RbrDbdZonesScalpVix75Noveto._detect_zones_cached`."""
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
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    max_base: int,
) -> list[dict]:
    """Zone geometry only (pattern/kind/price bounds/base_start/conf_idx/
    leg_out_end) — retest/break tracking and the zone-flip extension are a
    separate step (`_track_zone_lifecycle`) since they depend on the full
    current window, not just the runs."""
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

        zones.append(
            {
                "pattern": pattern,
                "kind": ZoneKind.DEMAND if leg_out_up else ZoneKind.SUPPLY,
                "price_high": price_high,
                "price_low": price_low,
                "base_start": base_start,
                "conf_idx": conf_idx,
                "leg_out_end": leg_out[2],
            }
        )
    return zones


def _scan_retest_break(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    demand: bool,
    scan_start: int,
    price_low: float,
    price_high: float,
) -> tuple[int | None, int | None]:
    """First bar back in the band after `scan_start` (retest_idx) and first
    bar CLOSING through the far side (broken_idx). Shared by a zone's own
    retest/break scan and, when a zone flips polarity, the flipped
    counterpart's own scan from its own `scan_start` — see
    `_track_zone_lifecycle`."""
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


def _track_zone_lifecycle(
    zones: list[dict],
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    atr_filled: np.ndarray,
    params: dict,
) -> list[dict]:
    """For each zone-geometry dict from `_build_zones_from_runs`, scan
    forward for its retest_idx/broken_idx and, when a strong candle breaks
    it (body >= flip_break_body_atr_mult * ATR), append its flipped
    counterpart with its own independent retest/break scan from just past
    the break — same "if zone break with a long candle and close outside
    of it, it becomes a sell/buy zone" rule the original inline loop
    applied. Returns a NEW list (geometry dicts are not mutated), in the
    same order the original single-pass loop produced: each zone
    immediately followed by its flip, if any.

    O(window) vectorized scan per zone/flip regardless of what the run/zone
    cache holds — this step is NOT cached, same reasoning as the M5 retest
    tracking in `pob_snd_zones_xauusd_v1.py` and `_track_retest_and_break`
    in `pob_snd_zones_vix75_v1.py`: it must see the full current window
    every call.
    """
    n = len(closes)
    out: list[dict] = []
    for z in zones:
        demand = z["kind"] == ZoneKind.DEMAND
        scan_start = z["leg_out_end"] + 1
        retest_idx, broken_idx = _scan_retest_break(
            highs, lows, closes, demand, scan_start, z["price_low"], z["price_high"]
        )
        zone = dict(z)
        zone["retest_idx"] = retest_idx
        zone["broken_idx"] = broken_idx
        zone["flipped"] = False
        out.append(zone)

        if broken_idx is not None:
            break_body = abs(closes[broken_idx] - opens[broken_idx])
            if break_body >= params["flip_break_body_atr_mult"] * atr_filled[broken_idx]:
                flip_demand = not demand
                flip_scan_start = broken_idx + 1
                if flip_scan_start < n:
                    f_retest, f_broken = _scan_retest_break(
                        highs, lows, closes, flip_demand, flip_scan_start,
                        z["price_low"], z["price_high"],
                    )
                    out.append(
                        {
                            "pattern": f"{z['pattern']}_flip",
                            "kind": ZoneKind.DEMAND if flip_demand else ZoneKind.SUPPLY,
                            "price_high": z["price_high"],
                            "price_low": z["price_low"],
                            "base_start": z["base_start"],
                            "conf_idx": broken_idx,
                            "leg_out_end": broken_idx,
                            "retest_idx": f_retest,
                            "broken_idx": f_broken,
                            "flipped": True,
                        }
                    )
    return out


def _detect_zones(
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    atr: pd.Series,
    params: dict,
) -> list[dict]:
    """RBR/DBD/RBD/DBR zones over the window, each with an optional flipped
    counterpart appended when a strong candle invalidates it.

    Zone dict fields: pattern, kind, price_high, price_low, base_start,
    conf_idx, leg_out_end, retest_idx, broken_idx, flipped (bool).

    Pure full recompute, O(n) classify + O(runs^2)-ish merge every call —
    this is the stateless ground truth. `RbrDbdZonesScalpVix75Noveto` uses
    the incremental, cache-backed `_detect_zones_cached` for its own
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
    zones = _build_zones_from_runs(runs, is_leg, highs, lows, closes, max_base)
    return _track_zone_lifecycle(zones, opens, highs, lows, closes, atr_filled, params)


class RbrDbdZonesScalpVix75Noveto:
    def __init__(self) -> None:
        self.spec = StrategySpec(
            name="rbr_dbd_zones_scalp_vix75_noveto",
            version=1,
            symbols=("Volatility 75 Index",),
            entry_timeframe="M1",
            confirmation_timeframes=("M5",),
            params={
                "atr_period": 14,
                "base_body_atr_mult": 0.8,
                "leg_travel_atr_mult": 0.8,
                "max_base_candles": 3,
                "zone_lookback_bars": 200,
                "pivot_wing": 3,
                "retest_max_age_bars": 10,
                "entry_max_dist_atr_mult": 4.0,
                "max_base_atr_mult": 2.0,
                "engulf_min_body_ratio": 0.6,
                "pin_bar_max_body_ratio": 0.35,
                "pin_bar_min_wick_mult": 2.0,
                "mtf_min_body_ratio": 0.4,
                "confirm_lookback": 6,
                "min_confirmations": 1,
                "sl_base_mult": 1.0,
                "min_sl_atr_mult": 0.3,
                "fallback_rr": 2.0,
                "min_rr_floor": 1.7,
                "flip_break_body_atr_mult": 1.2,
                "min_confidence": 0.5,
                "trend_timeframe": "M5",
                "trend_fast_period": 20,
                "trend_slow_period": 50,
                # Soft trend term (replaces the old hard veto): subtracted
                # from confidence when the entry direction disagrees with
                # trend_timeframe's EMA fast/slow read. 0 disables it
                # entirely — the sweep picked 0.0 (see module docstring).
                "counter_trend_penalty": 0.0,
            },
            htf_veto=False,
        )
        # Incremental zone-detection cache for `_detect_zones_cached`, keyed
        # on the window's own entry-timeframe bar timestamps (int64 ns)
        # rather than position — positions are meaningless across calls
        # because `evaluate()` hands this strategy a fixed-size TRAILING
        # window (`zone_lookback_bars`) that slides forward each call
        # (oldest bar dropped, newest appended) with a fresh 0-based index
        # every time. None until the first successful detection; reset to
        # None whenever a call can't produce a usable ATR (mirrors
        # `_detect_zones` returning `[]` early). Same design as
        # `pob_snd_zones_xauusd_v1.PobSndZonesXauusd._detect_zones_cached`
        # / `pob_snd_zones_vix75_v1.PobSndZonesVix75._detect_zones_cached`,
        # adapted for a window that's raw entry-timeframe bars (no zone-TF
        # resample step): every position's OHLC is that bar's own value and
        # is invariant across calls regardless of where the window starts —
        # only the ATR warmup band (position < atr_period) and the old
        # window's own still-growing last run are excluded from reuse.
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
        `_detect_zones(opens, highs, lows, closes, atr, params)` — same
        design as `pob_snd_zones_vix75_v1.PobSndZonesVix75._detect_zones_cached`
        (see that docstring for the fully-annotated original this was
        replicated from), adapted for this family's zone-flip extension:
        zone geometry/run caching is unaffected by flips (flips are derived
        AFTER the cached run/zone step, from `broken_idx`, never fed back
        into it), so `_track_zone_lifecycle` — which computes retest/break
        AND builds any flip counterpart — runs fresh every call over
        whatever zone geometry the (possibly-partially-cached) run list
        produces, exactly like `_track_retest_and_break` does in the vix75
        reference, just extended to also emit flips.

        `t_ns` is the window's own bar timestamps (int64 ns), positionally
        aligned 1:1 with opens/highs/lows/closes, ascending. No zone-TF
        resample step here — the window is raw entry-timeframe bars — so
        every position's OHLC is that bar's own value and is invariant
        across calls regardless of where the window starts; only the
        rolling ATR's NaN-warmup fill (computed over bars including
        position 0) makes a run's classification call-variant before
        position `atr_period`, and a run that's still the window's own last
        position may still be growing (see the vix75/xauusd references for
        why raw PRE-MERGE runs, never post-merge output, must be cached —
        `is_leg()` depends only on a run's own start/end, so a still-growing
        run can flip from "too short to be its own leg" to "a leg",
        retroactively invalidating an earlier merge decision if that
        decision was cached post-merge instead).

        Bit-identical to `_detect_zones(opens, highs, lows, closes, atr,
        params)` on every call — proven by
        `tests/unit/strategies/test_rbr_dbd_zones_scalp_vix75_noveto.py::test_incremental_cache_matches_full_recompute_every_step`.
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
        zones = _build_zones_from_runs(merged_runs, is_leg, highs, lows, closes, max_base)
        zones = _track_zone_lifecycle(zones, opens, highs, lows, closes, atr_filled, params)

        self._zone_cache = {
            "t_ns": t_ns.copy(),
            "raw_runs": [[cls, int(t_ns[s]), int(t_ns[e])] for cls, s, e in raw_runs],
        }
        return zones

    def evaluate(self, ctx: MarketContext) -> Signal | None:
        params = self.spec.params
        df = ctx.candles.get(self.spec.entry_timeframe)
        atr_period = int(params["atr_period"])
        pivot_wing = int(params["pivot_wing"])
        min_bars = max(int(params["zone_lookback_bars"]), atr_period * 2 + 10, pivot_wing * 2 + 30)
        if df is None or len(df) < min_bars:
            return None

        lookback = int(params["zone_lookback_bars"])
        opens = df["open"].to_numpy()[-lookback:]
        highs = df["high"].to_numpy()[-lookback:]
        lows = df["low"].to_numpy()[-lookback:]
        closes = df["close"].to_numpy()[-lookback:]
        t_ns = pd.DatetimeIndex(df["time"]).as_unit("ns").asi8[-lookback:]

        atr = _atr(highs, lows, closes, atr_period)
        atr_val = atr.iloc[-1]
        if pd.isna(atr_val) or atr_val <= 0:
            return None
        atr_val = float(atr_val)

        zones = self._detect_zones_cached(opens, highs, lows, closes, t_ns, atr, params)
        last_i = len(closes) - 1

        # Entry-candle direction first: engulfing-only (pin bar / body candle
        # both underperformed engulfing badly), then score against the trend.
        pattern, side = _classify_pattern(opens, highs, lows, closes, last_i, params)
        if pattern is None or "engulfing" not in pattern:
            return None
        demand = side == "up"
        direction = Direction.BUY if demand else Direction.SELL

        trend = _trend_direction(ctx, params)
        trend_aligned = trend is None or trend == side

        # Scan every fresh zone for one matching the entry candle's
        # direction, most recent first — a fresh-but-misaligned zone must not
        # mask a valid aligned one on the same bar.
        close = float(closes[last_i])
        candidate = None
        for z in reversed(zones):
            if z["broken_idx"] is not None or z["retest_idx"] is None:
                continue
            if (z["kind"] == ZoneKind.DEMAND) != demand:
                continue
            if last_i - z["retest_idx"] > int(params["retest_max_age_bars"]):
                continue
            if (z["price_high"] - z["price_low"]) > params["max_base_atr_mult"] * atr_val:
                continue  # sloppy/wide base — lower-quality S&D structure
            proximal = z["price_high"] if demand else z["price_low"]
            dist = (close - proximal) if demand else (proximal - close)
            if dist > params["entry_max_dist_atr_mult"] * atr_val:
                continue
            candidate = z
            break
        if candidate is None:
            return None

        confirmations = sum(
            1
            for tf in self.spec.confirmation_timeframes
            if _mtf_confirms(ctx, tf, direction, params)
        )
        if confirmations < int(params["min_confirmations"]):
            return None

        base_height = candidate["price_high"] - candidate["price_low"]
        sl_points = max(base_height * params["sl_base_mult"], atr_val * params["min_sl_atr_mult"])
        if sl_points <= 0:
            return None

        # Risk denominator includes spread so the floor below matches what
        # SpreadGate will actually require at the broker.
        spread_price = float(ctx.spread_points) * POINT_VALUE
        risk_points = sl_points + spread_price

        swings = _zigzag_swings(highs, lows, pivot_wing)
        target = _target_swing(swings, close, direction)
        if target is not None:
            target_price, target_idx = target
            tp_points = abs(target_price - close)
            tp_source = f"swing@{target_price:.5f}(bar {target_idx})"
        else:
            tp_points = risk_points * params["fallback_rr"]
            tp_source = "fallback_rr(no unmitigated swing)"

        if tp_points < params["min_rr_floor"] * risk_points:
            return None

        continuation = candidate["pattern"].rstrip("_flip") in ("RBR", "DBD")
        confidence = (0.5 if continuation else 0.45) + 0.1 * confirmations
        if "engulfing" in pattern:
            confidence += 0.05
        if candidate["flipped"]:
            confidence -= 0.05
        if not trend_aligned:
            confidence -= params["counter_trend_penalty"]
        confidence = min(max(confidence, 0.0), 0.9)
        if confidence < params["min_confidence"]:
            return None

        window_times = df["time"].iloc[-lookback:].reset_index(drop=True)
        zone = PriceZone(
            kind=candidate["kind"],
            price_low=candidate["price_low"],
            price_high=candidate["price_high"],
            time_start=window_times.iloc[candidate["base_start"]],
            time_end=window_times.iloc[last_i],
        )
        structure: tuple[StructurePoint, ...] = ()
        if target is not None and "time" in df.columns:
            label = StructureLabel.HH if direction == Direction.BUY else StructureLabel.LL
            structure = (
                StructurePoint(time=window_times.iloc[target[1]], price=target[0], label=label),
            )

        retest_age = last_i - candidate["retest_idx"]
        reason = (
            f"{candidate['pattern']}-retest pattern={pattern} trend={trend or 'n/a'} "
            f"trend_aligned={trend_aligned} "
            f"zone_rect=[{candidate['price_low']:.2f},{candidate['price_high']:.2f}] "
            f"retest_age={retest_age} mtf_confirms={confirmations} confidence={confidence:.2f} "
            f"sl=base_height({base_height:.2f}) tp={tp_source} "
            f"lines: entry={close:.2f} sl_pts={sl_points:.2f} tp_pts={tp_points:.2f}"
        )
        return Signal(
            direction=direction,
            sl_points=float(sl_points),
            tp_points=float(tp_points),
            confidence=float(confidence),
            reason=reason,
            zone=zone,
            pattern=pattern,
            structure=structure,
        )
