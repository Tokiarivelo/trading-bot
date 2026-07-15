"""PoB SNRC2 ("sibling" of SNRC1) — pp.58 of "The Property of Bystra".

Same base+breakout geometry as SNRC1, but the breakout is in the OPPOSITE
direction from the leg before the base (RBD after a rally, DBR after a
drop) — a reversal-off-a-tested-zone setup rather than a continuation one.
Draws the base zone (`zone_high`/`zone_low`) and an arrow at the breakout/
entry bar (`entry_marker_up`/`entry_marker_down`).

Ported from the pure detection functions in
`backend/src/strategies/generated/pob_price_action_snd for vix75_v1.py`
(`_find_base`/`_classify_pattern`), generalized to scan the *entire* candle
history so every past occurrence is drawn, not just the most recent one —
an indicator is chart annotation, not a live trading decision, so it has no
multi-timeframe confirmation or risk/confidence gating; those stay strategy
concerns.
"""

import pandas as pd


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


def _body(df: pd.DataFrame) -> pd.Series:
    return (df["close"] - df["open"]).abs()


def _range(df: pd.DataFrame) -> pd.Series:
    return df["high"] - df["low"]


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
    rng = _range(df).iloc[i]
    if rng <= 0:
        return False, ""
    if _body(df).iloc[i] / rng < min_body_ratio:
        return False, ""
    return True, ("up" if df["close"].iloc[i] > df["open"].iloc[i] else "down")


def _is_pin_bar(
    df: pd.DataFrame, i: int, max_body_ratio: float, min_wick_body_mult: float
) -> tuple[bool, str]:
    rng = _range(df).iloc[i]
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


def _find_base_at(df: pd.DataFrame, atr_val: float, last_idx: int, params: dict) -> dict | None:
    impulse_bars = int(params["impulse_lookback_bars"])
    for base_len in range(2, int(params["base_max_bars"]) + 1):
        base_start = last_idx - base_len
        base_end = last_idx - 1
        if base_start - impulse_bars < 0:
            continue
        base_slice = df.iloc[base_start : base_end + 1]
        if (_range(base_slice) > atr_val * params["base_range_atr_mult"]).any():
            continue
        pre_slice = df.iloc[base_start - impulse_bars : base_start]
        pre_move = pre_slice["close"].iloc[-1] - pre_slice["close"].iloc[0]
        if abs(pre_move) < atr_val * params["impulse_min_atr_mult"]:
            continue
        return {
            "base_start": base_start,
            "base_high": float(base_slice["high"].max()),
            "base_low": float(base_slice["low"].min()),
            "leg_before": "up" if pre_move > 0 else "down",
        }
    return None


def _swing_flags(df: pd.DataFrame, lookback: int) -> tuple[pd.Series, pd.Series]:
    highs, lows = df["high"], df["low"]
    is_high = pd.Series(False, index=df.index)
    is_low = pd.Series(False, index=df.index)
    n = len(df)
    for i in range(lookback, n - lookback):
        window_h = highs.iloc[i - lookback : i + lookback + 1]
        window_l = lows.iloc[i - lookback : i + lookback + 1]
        if highs.iloc[i] == window_h.max():
            is_high.iloc[i] = True
        if lows.iloc[i] == window_l.min():
            is_low.iloc[i] = True
    return is_high, is_low


def _count_sr_touches(
    df: pd.DataFrame,
    level_low: float,
    level_high: float,
    is_high: pd.Series,
    is_low: pd.Series,
    tolerance: float,
) -> int:
    mid = (level_low + level_high) / 2
    touches = 0
    for i in range(len(df)):
        high_touch = is_high.iloc[i] and abs(df["high"].iloc[i] - mid) <= tolerance
        low_touch = is_low.iloc[i] and abs(df["low"].iloc[i] - mid) <= tolerance
        if high_touch or low_touch:
            touches += 1
    return touches


def _has_strong_sr(
    df: pd.DataFrame,
    base_start: int,
    base_low: float,
    base_high: float,
    atr_val: float,
    params: dict,
) -> bool:
    """'Strong Support or Resistance' (SNRC1 Formula p.45): the base zone
    must sit at a level swing points already touched repeatedly before this
    base formed — a windowed, bounded check (only run on the rare bar where
    a base+breakout candidate has already matched) so it stays cheap even
    scanned across a full history."""
    window_start = max(0, base_start - int(params["sr_lookback_bars"]))
    sr_slice = df.iloc[window_start:base_start].reset_index(drop=True)
    lookback = int(params["swing_lookback"])
    if len(sr_slice) <= 2 * lookback + 1:
        return False
    is_high, is_low = _swing_flags(sr_slice, lookback)
    tolerance = atr_val * params["sr_tolerance_atr_mult"]
    touches = _count_sr_touches(sr_slice, base_low, base_high, is_high, is_low, tolerance)
    return touches >= int(params["sr_min_touches"])


def _danger_zone_breached_at(
    df: pd.DataFrame,
    base_low: float,
    base_high: float,
    direction: str,
    atr_val: float,
    mult: float,
    from_idx: int,
) -> bool:
    if direction == "up":
        return bool((df["low"].iloc[from_idx:] < base_low - atr_val * mult).any())
    return bool((df["high"].iloc[from_idx:] > base_high + atr_val * mult).any())


class PobSnrc2Indicator:
    def compute(self, candles: pd.DataFrame, params: dict) -> dict[str, list[float | None]]:
        p = {
            "atr_period": int(params.get("atr_period", 14)),
            "base_max_bars": int(params.get("base_max_bars", 4)),
            "impulse_lookback_bars": int(params.get("impulse_lookback_bars", 3)),
            "base_range_atr_mult": float(params.get("base_range_atr_mult", 1.0)),
            "impulse_min_atr_mult": float(params.get("impulse_min_atr_mult", 1.0)),
            "sr_lookback_bars": int(params.get("sr_lookback_bars", 100)),
            "sr_tolerance_atr_mult": float(params.get("sr_tolerance_atr_mult", 0.25)),
            "sr_min_touches": int(params.get("sr_min_touches", 2)),
            "danger_zone_atr_mult": float(params.get("danger_zone_atr_mult", 0.5)),
            "engulf_min_body_ratio": float(params.get("engulf_min_body_ratio", 0.6)),
            "pin_bar_max_body_ratio": float(params.get("pin_bar_max_body_ratio", 0.35)),
            "pin_bar_min_wick_mult": float(params.get("pin_bar_min_wick_mult", 2.0)),
            "swing_lookback": int(params.get("swing_lookback", 3)),
        }

        df = candles.reset_index(drop=True)
        n = len(df)
        zone_high: list[float | None] = [None] * n
        zone_low: list[float | None] = [None] * n
        entry_marker_up: list[float | None] = [None] * n
        entry_marker_down: list[float | None] = [None] * n
        if n == 0:
            return {
                "zone_high": zone_high,
                "zone_low": zone_low,
                "entry_marker_up": entry_marker_up,
                "entry_marker_down": entry_marker_down,
            }

        atr = _atr(df, p["atr_period"])
        min_bars = p["base_max_bars"] + p["impulse_lookback_bars"] + 5

        for i in range(min_bars, n):
            atr_val = atr.iloc[i]
            if pd.isna(atr_val) or atr_val <= 0:
                continue
            base = _find_base_at(df, atr_val, i, p)
            if base is None:
                continue
            pattern, side = _classify_pattern(df, i, p)
            if pattern is None:
                continue
            breakout_up = side == "up"
            leg_before = base["leg_before"]
            # SNRC2 = reversal off a tested zone: breakout is OPPOSITE the
            # impulse leg before the base (RBD after a rally, DBR after a
            # drop). SNRC1 (same direction, continuation) is its own
            # indicator.
            is_snrc2 = (leg_before == "up" and not breakout_up) or (
                leg_before == "down" and breakout_up
            )
            if not is_snrc2:
                continue

            base_low, base_high = base["base_low"], base["base_high"]
            if not _has_strong_sr(df, base["base_start"], base_low, base_high, atr_val, p):
                continue
            direction = "up" if breakout_up else "down"
            if _danger_zone_breached_at(
                df,
                base_low,
                base_high,
                direction,
                atr_val,
                p["danger_zone_atr_mult"],
                base["base_start"],
            ):
                continue

            for k in range(base["base_start"], i + 1):
                zone_high[k] = base_high
                zone_low[k] = base_low
            if breakout_up:
                entry_marker_up[i] = float(df["low"].iloc[i])
            else:
                entry_marker_down[i] = float(df["high"].iloc[i])

        return {
            "zone_high": zone_high,
            "zone_low": zone_low,
            "entry_marker_up": entry_marker_up,
            "entry_marker_down": entry_marker_down,
        }
