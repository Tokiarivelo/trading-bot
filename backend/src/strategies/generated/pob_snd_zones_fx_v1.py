"""PoB S&D zone-retest strategy for Volatility 75 Index.

Trades the "only 4 types of Entry Point" from the Property of Bystra notes:
RBR / DBR demand zones (buy the retest) and DBD / RBD supply zones (sell the
retest). Zone detection is a faithful port of the frontend `snd` chart
indicator (`frontend/src/features/chart/indicators.ts`, `sndZones()`), so
what this bot trades is exactly what the chart overlay draws:

  - every candle is base-class (body <= base_body_atr_mult * ATR, any color)
    or a directional momentum bar; consecutive same-class bars form runs;
  - weak same-direction runs split by a short pause merge into one run;
  - a run is a *leg* when its net travel >= leg_travel_atr_mult * ATR;
  - a zone is each adjacent pair of legs with 1..max_base_candles candles
    between them, confirmed by the first leg-out close clearing the base
    band; the band is those between-candles' high/low;
  - the first candle back in the band after the leg-out is the retest; a
    close through the far side breaks (voids) the zone.

Entry only on a fresh retest (within retest_max_age_bars of the last bar) of
an unbroken zone, with a confirming candle on the entry bar (engulfing >
pin bar > body candle, per the PDF's confirmation doctrine) plus at least
min_confirmations higher-timeframe engulf/body confirmations ("switch to a
higher TF, look for engulf" — SNRC formula). Stop goes beyond the zone's far
edge; target is a fixed reward:risk multiple.

FX flavor (XAUUSD/XAGUSD): confirmation runs on H1/H4 — the deep-history
frames for metals — and, per the XAUUSD 2026-06:2026-07 tuning matrix,
trades continuation zones only, aligned with the H1 EMA(50) trend, with
wider stops (gold's wicks) and a higher reward:risk. Best backtest on that
window is PF 0.95 — near break-even, NOT yet profitable; treat this as a
starting point for further refinement, not a finished edge.
"""

import numpy as np
import pandas as pd

from src.strategies.domain.models import (
    Direction,
    MarketContext,
    PriceZone,
    Signal,
    StrategySpec,
    ZoneKind,
)

# Point size per traded symbol (configs/symbols/*.yaml) — converts
# ctx.spread_points (raw broker points) into a price distance so
# reward_risk_ratio below is applied to (sl + spread), not sl alone — the
# same floor SpreadGate enforces at the broker gate (tp >= min_rr * (sl + spread)).
# This strategy trades both XAUUSD and XAGUSD, whose point sizes differ.
POINT_VALUES = {"XAUUSD": 0.01, "XAGUSD": 0.001}


def _true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    return pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def _atr(df: pd.DataFrame, period: int) -> pd.Series:
    return _true_range(df).rolling(period, min_periods=period).mean()


def _is_bullish_engulfing(df: pd.DataFrame, i: int) -> bool:
    if i < 1:
        return False
    prev_o, prev_c = df["open"].iloc[i - 1], df["close"].iloc[i - 1]
    o, c = df["open"].iloc[i], df["close"].iloc[i]
    if not (prev_c < prev_o and c > o):
        return False
    return o <= prev_c and c >= prev_o


def _is_bearish_engulfing(df: pd.DataFrame, i: int) -> bool:
    if i < 1:
        return False
    prev_o, prev_c = df["open"].iloc[i - 1], df["close"].iloc[i - 1]
    o, c = df["open"].iloc[i], df["close"].iloc[i]
    if not (prev_c > prev_o and c < o):
        return False
    return o >= prev_c and c <= prev_o


def _body_candle_side(df: pd.DataFrame, i: int, min_body_ratio: float) -> tuple[bool, str]:
    rng = df["high"].iloc[i] - df["low"].iloc[i]
    if rng <= 0:
        return False, ""
    if abs(df["close"].iloc[i] - df["open"].iloc[i]) / rng < min_body_ratio:
        return False, ""
    return True, ("up" if df["close"].iloc[i] > df["open"].iloc[i] else "down")


def _is_pin_bar(
    df: pd.DataFrame, i: int, max_body_ratio: float, min_wick_body_mult: float
) -> tuple[bool, str]:
    rng = df["high"].iloc[i] - df["low"].iloc[i]
    if rng <= 0:
        return False, ""
    o, h, lo, c = df["open"].iloc[i], df["high"].iloc[i], df["low"].iloc[i], df["close"].iloc[i]
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


def _classify_pattern(df: pd.DataFrame, i: int, params: dict) -> tuple[str | None, str | None]:
    """Confirming candlestick pattern at bar `i`, strongest match first
    (engulfing > pin bar > plain body candle) — same ladder as the existing
    vix75 strategy so both bots read candles identically."""
    if _is_bullish_engulfing(df, i):
        return "bullish_engulfing", "up"
    if _is_bearish_engulfing(df, i):
        return "bearish_engulfing", "down"
    is_pin, pin_side = _is_pin_bar(
        df, i, params["pin_bar_max_body_ratio"], params["pin_bar_min_wick_mult"]
    )
    if is_pin:
        return f"{'bullish' if pin_side == 'up' else 'bearish'}_pin_bar", pin_side
    strong, side = _body_candle_side(df, i, params["engulf_min_body_ratio"])
    if strong:
        return f"{'bullish' if side == 'up' else 'bearish'}_body_candle", side
    return None, None


def _mtf_confirms(ctx: MarketContext, tf: str, direction: Direction, params: dict) -> bool:
    df = ctx.candles.get(tf)
    lookback = int(params["confirm_lookback"])
    if df is None or len(df) < lookback + 2:
        return False
    start_i = len(df) - lookback
    for i in range(start_i, len(df)):
        if direction == Direction.BUY:
            if _is_bullish_engulfing(df, i):
                return True
            strong, side = _body_candle_side(df, i, params["mtf_min_body_ratio"])
            if strong and side == "up":
                return True
        else:
            if _is_bearish_engulfing(df, i):
                return True
            strong, side = _body_candle_side(df, i, params["mtf_min_body_ratio"])
            if strong and side == "down":
                return True
    return False


def _classify_bars(
    closes: np.ndarray, opens: np.ndarray, atr_filled: np.ndarray, base_mult: float
) -> np.ndarray:
    """Vectorized per-bar classification: 0 = base (small body, either
    color); +1/-1 = directional momentum bar. Same rule the scalar
    `classify(i)` used before this was split out for
    `PobSndZonesFx._detect_zones_cached` — keep the two in sync."""
    body = np.abs(closes - opens)
    return np.where(body <= base_mult * atr_filled, 0, np.where(closes >= opens, 1, -1))


def _build_runs_from(classes: np.ndarray, start: int, stop: int | None = None) -> list[list[int]]:
    """Group `classes[start:stop]` into consecutive-same-class runs, as
    mutable [cls, start, end] triples of absolute positions."""
    end_pos = len(classes) if stop is None else stop
    runs: list[list[int]] = []
    for i in range(start, end_pos):
        cls = int(classes[i])
        if runs and runs[-1][0] == cls:
            runs[-1][2] = i
        else:
            runs.append([cls, i, i])
    return runs


def _coalesce_adjacent_runs(runs: list[list[int]]) -> list[list[int]]:
    """Re-join directly-adjacent same-class runs at a splice seam (used
    when a cached run-list prefix is stitched to freshly-built head/tail
    segments in `PobSndZonesFx._detect_zones_cached`). A from-scratch
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
        cls, start, end = run
        return cls != 0 and abs(closes[end] - opens[start]) >= leg_mult * atr_filled[end]

    return is_leg


def _merge_weak_runs(runs: list[list[int]], is_leg, max_base: int) -> list[list[int]]:
    """Fixed-point pass absorbing a short same-color-bracketed base run into
    one leg (see the `_detect_zones` module docstring). Mutates and returns
    `runs`. Cheap even when `runs` includes an already-final cached prefix:
    re-scanning entries that can't merge again is what makes the
    incremental cache exact rather than approximate — see
    `PobSndZonesFx._detect_zones_cached`."""
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
    leg_out_end) — retest/break tracking is a separate step
    (`_track_retest_and_break`) since it depends on the full current
    window, not just the runs."""
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
        # Confirmation: first leg-out candle whose close actually departs the
        # base band — a momentum run that never clears the base is still
        # consolidation, not a zone.
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


def _track_retest_and_break(
    zone: dict, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, n: int
) -> tuple[int | None, int | None]:
    """First bar back in the band after the leg-out (retest_idx) and first
    bar CLOSING through the far side (broken_idx), scanned from just after
    the leg-out run — its own early candles' wicks still overlap the base
    and aren't a return. Split out of `_detect_zones` so both the full
    recompute and `_detect_zones_cached` share it; this is an O(window)
    scan per zone regardless of what's cached, so it's NOT part of the
    incremental cache — it runs fresh every call, same as the M5 retest
    tracking in the `pob_snd_zones_xauusd_v1.py` reference this pattern was
    replicated from."""
    demand = zone["kind"] == ZoneKind.DEMAND
    price_high = zone["price_high"]
    price_low = zone["price_low"]
    retest_idx = None
    broken_idx = None
    for j in range(zone["leg_out_end"] + 1, n):
        touched = (lows[j] <= price_high) if demand else (highs[j] >= price_low)
        if retest_idx is None and touched:
            retest_idx = j
        broke = (closes[j] < price_low) if demand else (closes[j] > price_high)
        if broke:
            broken_idx = j
            break
    return retest_idx, broken_idx


def _detect_zones(df: pd.DataFrame, atr: pd.Series, params: dict) -> list[dict]:
    """RBR/DBD/RBD/DBR zones over `df` — port of the frontend `sndZones()`.

    Returns chronological zone dicts:
      pattern ("RBR"|"DBD"|"RBD"|"DBR"), kind (ZoneKind), price_high,
      price_low, base_start / conf_idx / leg_out_end (integer positions in
      `df`), retest_idx (first bar back in the band after the leg-out, or
      None), broken_idx (first bar CLOSING through the far side, or None).

    Pure full recompute, O(n) classify + O(runs^2)-ish merge every call —
    this is the stateless ground truth. `PobSndZonesFx` uses the
    incremental, cache-backed `_detect_zones_cached` for its own
    (repeatedly-called, sliding-window) `evaluate()` instead; this function
    stays untouched and is available for any other one-shot use / direct
    testing.
    """
    n = len(df)
    valid_atr = atr.dropna()
    if valid_atr.empty:
        return []
    # Pad the ATR warmup bars with the first available value so early
    # candles still classify (same padding the chart indicator does).
    atr_filled = atr.fillna(valid_atr.iloc[0]).to_numpy()

    opens = df["open"].to_numpy()
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    closes = df["close"].to_numpy()

    base_mult = params["base_body_atr_mult"]
    leg_mult = params["leg_travel_atr_mult"]
    max_base = int(params["max_base_candles"])

    classes = _classify_bars(closes, opens, atr_filled, base_mult)
    runs = _build_runs_from(classes, 0)
    is_leg = _make_is_leg(closes, opens, atr_filled, leg_mult)
    runs = _merge_weak_runs(runs, is_leg, max_base)
    zones = _build_zones_from_runs(runs, is_leg, highs, lows, closes, max_base)
    for z in zones:
        z["retest_idx"], z["broken_idx"] = _track_retest_and_break(z, highs, lows, closes, n)
    return zones


class PobSndZonesFx:
    def __init__(self) -> None:
        self.spec = StrategySpec(
            name="pob_snd_zones_fx",
            version=1,
            symbols=("XAUUSD", "XAGUSD"),
            entry_timeframe="M5",
            confirmation_timeframes=("H1", "H4"),
            params={
                # Zone detection — MUST stay in sync with the frontend `snd`
                # indicator's DEFAULT_SND_PARAMS + dock period so the chart
                # rectangles match what the bot trades.
                "atr_period": 14,
                "base_body_atr_mult": 0.5,
                "leg_travel_atr_mult": 1.0,
                "max_base_candles": 3,
                "zone_lookback_bars": 200,
                # Entry gating.
                "retest_max_age_bars": 2,
                "entry_max_dist_atr_mult": 3.0,
                "engulf_min_body_ratio": 0.6,
                "pin_bar_max_body_ratio": 0.35,
                "pin_bar_min_wick_mult": 2.0,
                "mtf_min_body_ratio": 0.4,
                "confirm_lookback": 6,
                "min_confirmations": 1,
                # Refinement toggles (v2): demand the strongest entry
                # confirmation only, and/or trade only the continuation
                # zones (RBR/DBD) — reversal-turn zones (RBD/DBR) are the
                # weaker SNRC2 tier.
                "require_engulfing_entry": False,
                "continuation_only": True,
                # 0 disables; otherwise only trade zones aligned with the
                # first confirmation TF's EMA trend (close vs EMA(n)).
                "htf_trend_ema_period": 50,
                # Require the retest bar to CLOSE back outside the band in
                # the trade direction — proven rejection, not a hope-entry.
                "require_rejection_close": False,
                # Risk shape.
                "sl_zone_buffer_atr_mult": 1.0,
                "sl_atr_mult": 1.5,
                "reward_risk_ratio": 2.5,
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
        # step): every position's OHLC is that bar's own value and is
        # invariant across calls regardless of where the window starts —
        # only the ATR warmup band (position < atr_period) and the old
        # window's own still-growing last run are excluded from reuse.
        self._zone_cache: dict[str, object] | None = None

    def _detect_zones_cached(
        self, window: pd.DataFrame, atr: pd.Series, params: dict
    ) -> list[dict]:
        """Incremental, bit-identical replacement for module-level
        `_detect_zones(window, atr, params)`, exploiting that `evaluate()`
        calls this with a *sliding* window over the same M5 bar stream
        every time (see `__init__`). Unlike the XAUUSD reference
        (`pob_snd_zones_xauusd_v1.py`) this strategy has no zone-TF
        resample step — `window` is raw M5 bars — so every position's OHLC
        is that bar's own value and is invariant across calls regardless of
        where the window starts; only the rolling ATR's NaN-warmup fill
        (`atr.fillna(valid_atr.iloc[0])`, whose fill value is computed over
        bars including position 0) makes a run's classification
        call-variant before position `atr_period`.

        Algorithm per call (see the reference's `_detect_zones_cached`
        docstring for the fully-annotated original this was replicated
        from, including why raw pre-merge runs — not post-merge output —
        must be cached):
          1. Diff this call's bar timestamps against the previous call's
             cached array for a contiguous prefix match. No match (cold
             start, session gap, non-contiguous jump) -> full recompute,
             reseed the cache.
          2. Translate the previous call's cached RAW (pre-merge) runs into
             this call's positions; keep a contiguous prefix satisfying
             `atr_period <= start` (ATR warmup) and `end <= overlap_len -
             2` (excludes the old window's own last position — still
             open/growing as of that call).
          3. Re-run classify+group only over the head (before the cached
             prefix) and tail (after it — newly-appended bars plus the old
             window's still-growing final run).
          4. Splice head + cached raw runs + tail, coalesce any same-class
             seam, then run the weak-run merge-loop and zone-building
             fresh, in full, over the spliced raw list every call.

        Retest/break tracking (`_track_retest_and_break`) is NOT cached —
        it's an O(window) scan per zone that must see the full current
        window every call, same as the M5 retest tracking in the XAUUSD
        reference.

        Bit-identical to `_detect_zones(window, atr, params)` on every
        call — proven by
        `tests/unit/strategies/test_pob_snd_zones_fx.py::test_incremental_cache_matches_full_recompute_every_step`.
        """
        n = len(window)
        valid_atr = atr.dropna()
        if valid_atr.empty:
            self._zone_cache = None
            return []
        atr_filled = atr.fillna(valid_atr.iloc[0]).to_numpy()

        opens = window["open"].to_numpy()
        highs = window["high"].to_numpy()
        lows = window["low"].to_numpy()
        closes = window["close"].to_numpy()
        t_ns = pd.DatetimeIndex(window["time"]).as_unit("ns").asi8

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
        for z in zones:
            z["retest_idx"], z["broken_idx"] = _track_retest_and_break(z, highs, lows, closes, n)

        self._zone_cache = {
            "t_ns": t_ns.copy(),
            "raw_runs": [[cls, int(t_ns[s]), int(t_ns[e])] for cls, s, e in raw_runs],
        }
        return zones

    def evaluate(self, ctx: MarketContext) -> Signal | None:
        params = self.spec.params
        df = ctx.candles.get(self.spec.entry_timeframe)
        min_bars = int(params["atr_period"]) * 2 + 10
        if df is None or len(df) < min_bars:
            return None

        window = df.iloc[-int(params["zone_lookback_bars"]) :].reset_index(drop=True)
        atr = _atr(window, int(params["atr_period"]))
        atr_val = atr.iloc[-1]
        if pd.isna(atr_val) or atr_val <= 0:
            return None
        atr_val = float(atr_val)

        zones = self._detect_zones_cached(window, atr, params)
        last_i = len(window) - 1

        # Most recent live zone whose FIRST retest is happening right now
        # (within retest_max_age_bars of the last bar). A broken zone, a
        # zone never retested, or a stale retest all pass — no trade.
        candidate = None
        for z in reversed(zones):
            if params.get("continuation_only") and z["pattern"] not in ("RBR", "DBD"):
                continue
            if z["broken_idx"] is not None or z["retest_idx"] is None:
                continue
            if last_i - z["retest_idx"] > int(params["retest_max_age_bars"]):
                continue
            candidate = z
            break
        if candidate is None:
            return None

        demand = candidate["kind"] == ZoneKind.DEMAND
        direction = Direction.BUY if demand else Direction.SELL

        # Confirmation candle on the entry bar, in the zone's direction —
        # "the best confirmation is in the engulfing candle body".
        pattern, side = _classify_pattern(window, last_i, params)
        if pattern is None or side != ("up" if demand else "down"):
            return None
        if params.get("require_engulfing_entry") and "engulfing" not in pattern:
            return None

        close = float(window["close"].iloc[last_i])
        proximal = candidate["price_high"] if demand else candidate["price_low"]
        # Negative when the close is inside the band; the gate only rejects
        # closes that already ran too far past the zone to anchor a stop.
        dist = (close - proximal) if demand else (proximal - close)
        if dist > params["entry_max_dist_atr_mult"] * atr_val:
            return None

        if params.get("require_rejection_close") and dist <= 0:
            return None

        ema_period = int(params.get("htf_trend_ema_period", 0))
        if ema_period > 0:
            htf = ctx.candles.get(self.spec.confirmation_timeframes[0])
            if htf is None or len(htf) < ema_period:
                return None
            ema_last = htf["close"].ewm(span=ema_period, adjust=False).mean().iloc[-1]
            htf_close = htf["close"].iloc[-1]
            aligned = (htf_close > ema_last) if demand else (htf_close < ema_last)
            if not aligned:
                return None

        confirmations = sum(
            1
            for tf in self.spec.confirmation_timeframes
            if _mtf_confirms(ctx, tf, direction, params)
        )
        if confirmations < int(params["min_confirmations"]):
            return None

        # RBR/DBD are continuation entries (SNRC1); RBD/DBR mark the turn
        # (SNRC2) and start slightly lower, same weighting the existing
        # vix75 strategy uses.
        continuation = candidate["pattern"] in ("RBR", "DBD")
        confidence = (0.5 if continuation else 0.45) + 0.1 * confirmations
        if "engulfing" in pattern:
            confidence += 0.05
        confidence = min(confidence, 0.9)
        if confidence < params["min_confidence"]:
            return None

        if demand:
            structural_level = candidate["price_low"] - atr_val * params["sl_zone_buffer_atr_mult"]
            structural_dist = close - structural_level
        else:
            structural_level = candidate["price_high"] + atr_val * params["sl_zone_buffer_atr_mult"]
            structural_dist = structural_level - close
        sl_points = max(structural_dist, atr_val * params["sl_atr_mult"])
        spread_price = float(ctx.spread_points) * POINT_VALUES.get(ctx.symbol, 0.01)
        tp_points = (sl_points + spread_price) * params["reward_risk_ratio"]
        if demand:
            sl_price, tp_price = close - sl_points, close + tp_points
        else:
            sl_price, tp_price = close + sl_points, close - tp_points

        zone = PriceZone(
            kind=candidate["kind"],
            price_low=candidate["price_low"],
            price_high=candidate["price_high"],
            time_start=window["time"].iloc[candidate["base_start"]],
            time_end=window["time"].iloc[last_i],
        )
        n_confirm_tfs = len(self.spec.confirmation_timeframes)
        retest_age = last_i - candidate["retest_idx"]
        reason = (
            f"{candidate['pattern']}-retest pattern={pattern} "
            f"zone_rect=[{candidate['price_low']:.2f},{candidate['price_high']:.2f}] "
            f"retest_age={retest_age} mtf_confirms={confirmations}/{n_confirm_tfs} "
            f"dist_atr={dist / atr_val:.2f} zone_unbroken "
            f"lines: entry={close:.2f} sl={sl_price:.2f} tp={tp_price:.2f}"
        )
        return Signal(
            direction=direction,
            sl_points=float(sl_points),
            tp_points=float(tp_points),
            confidence=float(confidence),
            reason=reason,
            zone=zone,
            pattern=pattern,
        )
