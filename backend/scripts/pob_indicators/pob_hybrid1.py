"""PoB Hybrid 1 — pp.28-33 of "The Property of Bystra".

An established, clean trendline through >= 3 same-side swings breaks, and
price retests a fresh compression zone printed right at the break for
entry. Draws the trendline (`trendline`), the origin/trend points
(`trend_marker`), and the break/retest entry (`entry_marker_up`/
`entry_marker_down`). Hybrid 2 (same break + a second, more recent
trendline on the opposite side also touched — the author's own "upgraded"
variant) is its own, separate indicator.

The author explicitly treats this family as high risk ("I always FAST
Hybrid 1 setup") — this indicator only draws where the geometry occurred on
the chart; it carries no confidence/risk gating of its own (that's a
strategy concern, not a chart-annotation one).

Ported from `_find_hybrid`/`_classify_pattern` in
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


def _find_hybrid_at(
    raw_points: list, df: pd.DataFrame, atr: pd.Series, group_end_k: int, params: dict
) -> dict | None:
    """Try a Hybrid break starting from the `min_trendline_points`-point
    group ending at `raw_points[group_end_k]`, on whichever side (high/low)
    that point belongs to."""
    anchor = raw_points[group_end_k]
    side = anchor[2]
    break_up = side == "low"  # a broken descending-lows line -> buy; a
    # broken ascending-highs line -> sell (see the strategy's own comment).
    min_pts = int(params["hybrid_min_trendline_points"])
    same_side = [pt for pt in raw_points[: group_end_k + 1] if pt[2] == side]
    if len(same_side) < min_pts:
        return None
    pts = same_side[-min_pts:]
    if pts[-1][0] != anchor[0]:
        return None  # only evaluate once per same-side point, at its own group

    line = _fit_trendline([(pt[0], pt[1]) for pt in pts])
    if line is None:
        return None
    slope, intercept = line
    if break_up and slope >= 0:
        return None
    if not break_up and slope <= 0:
        return None

    trend_prices = [pt[1] for pt in pts]
    pairs = list(zip(trend_prices, trend_prices[1:], strict=False))
    is_clean_trend = all(a > b for a, b in pairs) if break_up else all(a < b for a, b in pairs)
    if not is_clean_trend:
        return None

    origin_idx = pts[0][0]
    last_pt_idx = pts[-1][0]
    tolerance = None
    atr_val = atr.iloc[last_pt_idx]
    if pd.isna(atr_val) or atr_val <= 0:
        return None
    tolerance = atr_val * params["trendline_tolerance_atr_mult"]

    horizon = min(len(df) - 1, last_pt_idx + int(params["entry_search_bars"]))
    for i in range(last_pt_idx + 1, horizon + 1):
        line_val = slope * i + intercept
        close = df["close"].iloc[i]
        broke = close > line_val + tolerance if break_up else close < line_val - tolerance
        if not broke:
            continue
        pattern, psid = _classify_pattern(df, i, params)
        expected_side = "up" if break_up else "down"
        if pattern is None or psid != expected_side:
            continue

        opposite_side = "low" if side == "high" else "high"
        opposite_pool = [
            pt for pt in raw_points if pt[2] == opposite_side and pt[0] > origin_idx and pt[0] < i
        ]
        is_hybrid2 = False
        if len(opposite_pool) >= 2:
            channel = _fit_trendline([(pt[0], pt[1]) for pt in opposite_pool[-2:]])
            if channel and _touches_trendline(df, *channel, i, tolerance):
                is_hybrid2 = True

        return {
            "is_hybrid2": is_hybrid2,
            "direction": "buy" if break_up else "sell",
            "pattern": pattern,
            "line": line,
            "trend_points": pts,
            "entry_idx": i,
        }
    return None


class PobHybrid1Indicator:
    def compute(self, candles: pd.DataFrame, params: dict) -> dict[str, list[float | None]]:
        p = {
            "atr_period": int(params.get("atr_period", 14)),
            "swing_lookback": int(params.get("swing_lookback", 3)),
            "engulf_min_body_ratio": float(params.get("engulf_min_body_ratio", 0.6)),
            "pin_bar_max_body_ratio": float(params.get("pin_bar_max_body_ratio", 0.35)),
            "pin_bar_min_wick_mult": float(params.get("pin_bar_min_wick_mult", 2.0)),
            "trendline_tolerance_atr_mult": float(params.get("trendline_tolerance_atr_mult", 0.15)),
            "hybrid_min_trendline_points": int(params.get("hybrid_min_trendline_points", 3)),
            "entry_search_bars": int(params.get("entry_search_bars", 60)),
        }

        df = candles.reset_index(drop=True)
        n = len(df)
        trendline: list[float | None] = [None] * n
        trend_marker: list[float | None] = [None] * n
        entry_marker_up: list[float | None] = [None] * n
        entry_marker_down: list[float | None] = [None] * n
        if n == 0:
            return {
                "trendline": trendline,
                "trend_marker": trend_marker,
                "entry_marker_up": entry_marker_up,
                "entry_marker_down": entry_marker_down,
            }

        atr = _atr(df, p["atr_period"])
        lookback = p["swing_lookback"]
        is_high, is_low = _swing_flags(df, lookback)
        raw_points = _swing_points_list(df, is_high, is_low)

        for k in range(len(raw_points)):
            found = self._match(raw_points, df, atr, k, p)
            if found is None or found["is_hybrid2"]:
                continue
            slope, intercept = found["line"]
            i = found["entry_idx"]
            origin_idx = found["trend_points"][0][0]
            for t in range(origin_idx, i + 1):
                trendline[t] = slope * t + intercept
            for pt in found["trend_points"]:
                trend_marker[pt[0]] = pt[1]
            if found["direction"] == "buy":
                entry_marker_up[i] = float(df["low"].iloc[i])
            else:
                entry_marker_down[i] = float(df["high"].iloc[i])

        return {
            "trendline": trendline,
            "trend_marker": trend_marker,
            "entry_marker_up": entry_marker_up,
            "entry_marker_down": entry_marker_down,
        }

    @staticmethod
    def _match(raw_points, df, atr, k, p):
        return _find_hybrid_at(raw_points, df, atr, k, p)
