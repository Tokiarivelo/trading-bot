"""PoB Blindspot 2 — p.152 of "The Property of Bystra".

Same failed-engulfing + significant-break + retest shape as Blindspot 1,
plus a trendline confluence at the retest (fit through the last 2 same-side
swing points before the break) for extra confidence. The author still
distrusts this family regardless of the addition ("not all types of swaps
can be trusted") — this indicator only draws where the geometry occurred;
it carries no confidence/risk gating of its own (a strategy concern, not a
chart-annotation one). Draws the failed-engulfing/break candle
(`break_marker`), the confluence trendline (`trendline`), and the retest
entry (`entry_marker_up`/`entry_marker_down`). Plain Blindspot 1 (no
trendline) is its own, separate indicator.

Ported from `_find_blindspot`/`_classify_pattern` in
`backend/src/strategies/generated/pob_price_action_snd for vix75_v1.py`,
scanning the full history (every past occurrence, not just the most recent).
"""

import numpy as np
import pandas as pd


def _range(df: pd.DataFrame) -> pd.Series:
    return df["high"] - df["low"]


def _body(df: pd.DataFrame) -> pd.Series:
    return (df["close"] - df["open"]).abs()


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


def _swing_points_list(df: pd.DataFrame, is_high: pd.Series, is_low: pd.Series) -> list:
    points: list[tuple[int, float, str]] = []
    for i in range(len(df)):
        if is_high.iloc[i]:
            points.append((i, float(df["high"].iloc[i]), "high"))
        elif is_low.iloc[i]:
            points.append((i, float(df["low"].iloc[i]), "low"))
    points.sort(key=lambda p: p[0])
    return points


def _fit_trendline(points: list) -> tuple[float, float] | None:
    if len(points) < 2:
        return None
    xs = np.array([p[0] for p in points], dtype=float)
    ys = np.array([p[1] for p in points], dtype=float)
    if np.all(xs == xs[0]):
        return None
    slope, intercept = np.polyfit(xs, ys, 1)
    return float(slope), float(intercept)


def _touches_trendline(
    df: pd.DataFrame, slope: float, intercept: float, i: int, tolerance: float
) -> bool:
    line_val = slope * i + intercept
    return bool(
        abs(df["high"].iloc[i] - line_val) <= tolerance
        or abs(df["low"].iloc[i] - line_val) <= tolerance
    )


def _find_blindspot_at(
    df: pd.DataFrame, raw_points: list, atr: pd.Series, j: int, params: dict
) -> dict | None:
    """Try a Blindspot match where `j` is the failed-engulfing candle."""
    is_bull = _is_bullish_engulfing(df, j)
    is_bear = _is_bearish_engulfing(df, j)
    if not (is_bull or is_bear):
        return None

    n = len(df)
    horizon = min(n - 1, j + int(params["entry_search_bars"]))
    ref_low, ref_high = df["low"].iloc[j], df["high"].iloc[j]
    later_closes = df["close"].iloc[j + 1 : horizon + 1]
    if is_bull and (later_closes < ref_low).any():
        direction, break_level = "sell", ref_low
    elif is_bear and (later_closes > ref_high).any():
        direction, break_level = "buy", ref_high
    else:
        return None

    for i in range(j + 1, horizon + 1):
        atr_val = atr.iloc[i]
        if pd.isna(atr_val) or atr_val <= 0:
            continue
        tolerance = atr_val * params["sr_tolerance_atr_mult"] * 2
        if abs(df["close"].iloc[i] - break_level) > tolerance:
            continue
        pattern, side = _classify_pattern(df, i, params)
        expected_side = "up" if direction == "buy" else "down"
        if pattern is None or side != expected_side:
            continue

        trend_side = "low" if direction == "buy" else "high"
        same_side = [pt for pt in raw_points if pt[2] == trend_side and pt[0] <= j]
        has_trendline = False
        line = None
        line_points = None
        if len(same_side) >= 2:
            candidate_line = _fit_trendline([(pt[0], pt[1]) for pt in same_side[-2:]])
            if candidate_line:
                trend_tol = atr_val * params["trendline_tolerance_atr_mult"]
                if _touches_trendline(df, *candidate_line, i, trend_tol):
                    has_trendline = True
                    line = candidate_line
                    line_points = same_side[-2:]

        return {
            "direction": direction,
            "pattern": pattern,
            "break_level": break_level,
            "has_trendline": has_trendline,
            "entry_idx": i,
            "line": line,
            "line_points": line_points,
        }
    return None


class PobBlindspot2Indicator:
    def compute(self, candles: pd.DataFrame, params: dict) -> dict[str, list[float | None]]:
        p = {
            "atr_period": int(params.get("atr_period", 14)),
            "swing_lookback": int(params.get("swing_lookback", 3)),
            "sr_tolerance_atr_mult": float(params.get("sr_tolerance_atr_mult", 0.25)),
            "engulf_min_body_ratio": float(params.get("engulf_min_body_ratio", 0.6)),
            "pin_bar_max_body_ratio": float(params.get("pin_bar_max_body_ratio", 0.35)),
            "pin_bar_min_wick_mult": float(params.get("pin_bar_min_wick_mult", 2.0)),
            "trendline_tolerance_atr_mult": float(params.get("trendline_tolerance_atr_mult", 0.15)),
            "entry_search_bars": int(params.get("entry_search_bars", 20)),
        }

        df = candles.reset_index(drop=True)
        n = len(df)
        break_marker: list[float | None] = [None] * n
        trendline: list[float | None] = [None] * n
        entry_marker_up: list[float | None] = [None] * n
        entry_marker_down: list[float | None] = [None] * n
        if n == 0:
            return {
                "break_marker": break_marker,
                "trendline": trendline,
                "entry_marker_up": entry_marker_up,
                "entry_marker_down": entry_marker_down,
            }

        atr = _atr(df, p["atr_period"])
        lookback = p["swing_lookback"]
        is_high, is_low = _swing_flags(df, lookback)
        raw_points = _swing_points_list(df, is_high, is_low)

        for j in range(1, n - 1):
            found = _find_blindspot_at(df, raw_points, atr, j, p)
            if found is None or not found["has_trendline"]:
                continue
            i = found["entry_idx"]
            break_marker[j] = found["break_level"]
            slope, intercept = found["line"]
            line_start = found["line_points"][0][0]
            for t in range(line_start, i + 1):
                trendline[t] = slope * t + intercept
            if found["direction"] == "buy":
                entry_marker_up[i] = float(df["low"].iloc[i])
            else:
                entry_marker_down[i] = float(df["high"].iloc[i])

        return {
            "break_marker": break_marker,
            "trendline": trendline,
            "entry_marker_up": entry_marker_up,
            "entry_marker_down": entry_marker_down,
        }
