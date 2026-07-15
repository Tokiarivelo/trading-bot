"""PoB QMC (Quasimodo Continuation, "3 drives") — p.107 of "The Property of
Bystra".

Unlike QMR/QM2P/QMM (reversal-category), QMC is a continuation setup: a
trendline fit through the two most recent same-side swing extremes ("make
sure LL is at the 2nd drive"), entry on the 3rd touch of that trendline, in
the direction of the prevailing trend. Draws the trendline (`trendline`),
the two drive points (`drive_marker`), and the 3rd-touch entry
(`entry_marker_up`/`entry_marker_down`).

Ported from `_find_qmc`/`_classify_pattern` in
`backend/src/strategies/generated/pob_price_action_snd for vix75_v1.py`,
scanning the full history (every past occurrence, not just the most recent)
with no multi-timeframe confirmation or risk gating — those stay strategy
concerns, not chart-annotation ones.
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


class PobQmcIndicator:
    def compute(self, candles: pd.DataFrame, params: dict) -> dict[str, list[float | None]]:
        p = {
            "atr_period": int(params.get("atr_period", 14)),
            "swing_lookback": int(params.get("swing_lookback", 3)),
            "engulf_min_body_ratio": float(params.get("engulf_min_body_ratio", 0.6)),
            "pin_bar_max_body_ratio": float(params.get("pin_bar_max_body_ratio", 0.35)),
            "pin_bar_min_wick_mult": float(params.get("pin_bar_min_wick_mult", 2.0)),
            "trendline_tolerance_atr_mult": float(params.get("trendline_tolerance_atr_mult", 0.15)),
            "entry_search_bars": int(params.get("entry_search_bars", 30)),
        }

        df = candles.reset_index(drop=True)
        n = len(df)
        trendline: list[float | None] = [None] * n
        drive_marker: list[float | None] = [None] * n
        entry_marker_up: list[float | None] = [None] * n
        entry_marker_down: list[float | None] = [None] * n
        if n == 0:
            return {
                "trendline": trendline,
                "drive_marker": drive_marker,
                "entry_marker_up": entry_marker_up,
                "entry_marker_down": entry_marker_down,
            }

        atr = _atr(df, p["atr_period"])
        lookback = p["swing_lookback"]
        is_high, is_low = _swing_flags(df, lookback)
        raw_points = _swing_points_list(df, is_high, is_low)
        lows = [pt for pt in raw_points if pt[2] == "low"]
        highs = [pt for pt in raw_points if pt[2] == "high"]

        for side_points, direction, expected_side in ((lows, "buy", "up"), (highs, "sell", "down")):
            for k in range(1, len(side_points)):
                p1, p2 = side_points[k - 1], side_points[k]
                is_2nd_drive_deeper = p2[1] < p1[1] if direction == "buy" else p2[1] > p1[1]
                if not is_2nd_drive_deeper:
                    continue
                line = _fit_trendline([(p1[0], p1[1]), (p2[0], p2[1])])
                if line is None:
                    continue
                atr_val = atr.iloc[p2[0]]
                if pd.isna(atr_val) or atr_val <= 0:
                    continue
                tolerance = atr_val * p["trendline_tolerance_atr_mult"]
                horizon = min(n - 1, p2[0] + p["entry_search_bars"])
                for i in range(p2[0] + 1, horizon + 1):
                    if not _touches_trendline(df, *line, i, tolerance):
                        continue
                    pattern, side = _classify_pattern(df, i, p)
                    if pattern is None or side != expected_side:
                        continue

                    for t in range(p1[0], i + 1):
                        trendline[t] = line[0] * t + line[1]
                    drive_marker[p1[0]] = p1[1]
                    drive_marker[p2[0]] = p2[1]
                    if direction == "buy":
                        entry_marker_up[i] = float(df["low"].iloc[i])
                    else:
                        entry_marker_down[i] = float(df["high"].iloc[i])
                    break

        return {
            "trendline": trendline,
            "drive_marker": drive_marker,
            "entry_marker_up": entry_marker_up,
            "entry_marker_down": entry_marker_down,
        }
