"""RBR/DBR demand-zone swing strategy for XAUUSD (M15 entries, H1+H4 trend),
long-only.

Same leg-in/base/leg-out zone detection and zone-flip logic as
`rbr_dbd_zones_scalp_xauusd.py` (see that module's docstring for the full
mechanics), retimed for a higher-timeframe swing entry and restricted to the
buy side only:

  - Only ZoneKind.DEMAND retests are traded — RBR (uptrend continuation) and
    DBR (downtrend-to-uptrend reversal), including a demand zone produced by
    a bullish flip of a formerly-supply rectangle. DBD/RBD supply zones are
    still detected (needed to find flips into demand) but never traded.
  - Entry timeframe M15, trend confirmation from H1 *and* H4 both — a higher
    bar than the scalp variant's single M5 filter, since a swing hold is
    meant to ride an established higher-timeframe trend, not a single-TF
    blip.

TP/SL: identical rule to the scalp variant — SL is the zone base's height
(floored at a small ATR multiple); TP is the nearest unmitigated swing high
still above price, found via the same zigzag-fractal detector, with a capped
RR fallback when no such swing exists yet (deep breakout into new territory).

v2 refinements, from a 228-trade backtest of this exact variant (XAUUSD
2025-03..2026-07, v1 profit_factor 0.89, avg_r -0.058):

  - Splitting by zone pattern showed continuation RBR retests losing hard
    (120 trades, 15.0% win, -0.30R avg) while reversal DBR and bullish-flip
    retests were profitable (DBR +0.30R, DBD_flip +0.30R) — RBR alone
    accounted for -36R of the run's drag. By the time price pulls back into
    a demand zone deep into an already-extended uptrend, the move is often
    closer to exhaustion than continuation; RBR isn't dropped outright (the
    trader asked for all four entry types), but it now has to clear the same
    tightened base-width/confirmation-candle filters below rather than a
    laxer bar.
  - Entry-candle type breakdown: `bullish_body_candle` was 12.7% win/-0.27R
    versus engulfing (21.2%/+0.19R) and pin bar (18.6%/-0.05R) — dropped as a
    valid entry trigger.
  - Base-zone width in ATR terms: the widest tercile lost (-0.09 to -0.33R)
    while narrow bases made +0.26R — added `max_base_atr_mult` to skip wide,
    sloppy bases.
  - `min_confirmations` was nominally 1 of {H1, H4}, but 222 of 228 trades
    already had both agree; the 6 that didn't were 0% win. Raised to 2 to
    make "confirmed by H1 and H4" an explicit requirement instead of an
    accident of the data.

A second backtest of that fixed version (161 trades) then showed pin bar was
still weak even alone: bullish_pin_bar averaged -0.09R (17.9% win) versus
bullish_engulfing at +0.20R (22.4% win) — restricting confirmation to
engulfing-only lifted overall PF from 0.99 to 1.40 (avg_r +0.20, n=49), and
even the previously-worst RBR bucket came back to roughly breakeven (PF
0.99) instead of dragging the whole book down. Pin bar is no longer accepted
as an entry trigger.

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

# XAUUSD point size (configs/symbols/xauusd.yaml) — converts ctx.spread_points
# (raw broker points) into a price distance so the spread cost can be added
# to the TP floor below (same formula SpreadGate applies at the broker gate:
# tp >= min_rr * (sl + spread)), instead of relying on fallback_rr/min_rr_floor
# headroom over sl_points alone to happen to clear live spread.
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
    kind_needed = "high" if direction == Direction.BUY else "low"
    for index, price, kind in reversed(swings):
        if kind != kind_needed:
            continue
        if direction == Direction.BUY and price > close:
            return price, index
        if direction == Direction.SELL and price < close:
            return price, index
    return None


def _detect_zones(
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    atr: pd.Series,
    params: dict,
) -> list[dict]:
    n = len(closes)
    valid_atr = atr.dropna()
    if valid_atr.empty:
        return []
    atr_filled = atr.fillna(valid_atr.iloc[0]).to_numpy()

    base_mult = params["base_body_atr_mult"]
    leg_mult = params["leg_travel_atr_mult"]
    max_base = int(params["max_base_candles"])

    cls = np.where(
        np.abs(closes - opens) <= base_mult * atr_filled,
        0,
        np.where(closes >= opens, 1, -1),
    )

    change = np.flatnonzero(cls[1:] != cls[:-1]) + 1
    starts = np.concatenate(([0], change))
    ends = np.append(change - 1, n - 1)
    runs: list[list[int]] = [
        [int(cls[s]), int(s), int(e)] for s, e in zip(starts, ends, strict=True)
    ]

    def is_leg(run: list[int]) -> bool:
        cls_, start, end = run
        return cls_ != 0 and abs(closes[end] - opens[start]) >= leg_mult * atr_filled[end]

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


class RbrDbdZonesSwingXauusd:
    def __init__(self) -> None:
        self.spec = StrategySpec(
            name="rbr_dbd_zones_swing_xauusd",
            version=1,
            symbols=("XAUUSD",),
            entry_timeframe="M15",
            confirmation_timeframes=("H1", "H4"),
            params={
                "atr_period": 14,
                # Per-symbol retune 2026-07-19 (2025-03:2026-07 sweep):
                # PF 1.38->2.24, 49->58 trades
                "base_body_atr_mult": 0.65,
                "leg_travel_atr_mult": 0.8,
                "max_base_candles": 3,
                "zone_lookback_bars": 200,
                "pivot_wing": 3,
                "retest_max_age_bars": 3,
                "entry_max_dist_atr_mult": 3.0,
                "max_base_atr_mult": 2.0,
                "engulf_min_body_ratio": 0.6,
                "pin_bar_max_body_ratio": 0.35,
                "pin_bar_min_wick_mult": 2.0,
                "mtf_min_body_ratio": 0.4,
                "confirm_lookback": 8,
                "min_confirmations": 2,
                "sl_base_mult": 1.0,
                "min_sl_atr_mult": 0.3,
                "fallback_rr": 2.2,
                "min_rr_floor": 1.7,
                "flip_break_body_atr_mult": 1.3,
                "min_confidence": 0.5,
                "trend_timeframe": "H1",
                "trend_fast_period": 20,
                "trend_slow_period": 50,
            },
        )

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

        atr = _atr(highs, lows, closes, atr_period)
        atr_val = atr.iloc[-1]
        if pd.isna(atr_val) or atr_val <= 0:
            return None
        atr_val = float(atr_val)

        zones = _detect_zones(opens, highs, lows, closes, atr, params)
        last_i = len(closes) - 1

        # Entry-candle direction first: engulfing-only (pin bar / body candle
        # both underperformed engulfing badly), long-only — then follow the
        # higher-timeframe trend.
        pattern, side = _classify_pattern(opens, highs, lows, closes, last_i, params)
        if pattern is None or "engulfing" not in pattern or side != "up":
            return None
        direction = Direction.BUY

        trend = _trend_direction(ctx, params)
        if trend is not None and trend != "up":
            return None  # counter-trend setup — engine HTF veto would kill it anyway

        # Scan every fresh demand zone, most recent first — a fresh zone that
        # fails a later filter (e.g. distance) must not mask a valid older
        # one on the same bar.
        close = float(closes[last_i])
        candidate = None
        for z in reversed(zones):
            if z["kind"] != ZoneKind.DEMAND:
                continue  # long-only: never trade supply-side retests
            if z["broken_idx"] is not None or z["retest_idx"] is None:
                continue
            if last_i - z["retest_idx"] > int(params["retest_max_age_bars"]):
                continue
            if (z["price_high"] - z["price_low"]) > params["max_base_atr_mult"] * atr_val:
                continue  # sloppy/wide base — lower-quality S&D structure
            dist = close - z["price_high"]
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

        continuation = candidate["pattern"].rstrip("_flip") == "RBR"
        confidence = (0.5 if continuation else 0.45) + 0.15 * confirmations
        if "engulfing" in pattern:
            confidence += 0.05
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
            time_end=window_times.iloc[last_i],
        )
        structure: tuple[StructurePoint, ...] = ()
        if target is not None and "time" in df.columns:
            structure = (
                StructurePoint(
                    time=window_times.iloc[target[1]], price=target[0], label=StructureLabel.HH
                ),
            )

        retest_age = last_i - candidate["retest_idx"]
        reason = (
            f"{candidate['pattern']}-retest pattern={pattern} trend={trend or 'n/a'} "
            f"zone_rect=[{candidate['price_low']:.2f},{candidate['price_high']:.2f}] "
            f"retest_age={retest_age} htf_confirms={confirmations}/2 "
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
