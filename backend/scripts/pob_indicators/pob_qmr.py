"""PoB QMR (Quasimodo Reversal) — pp.89-92 of "The Property of Bystra".

The classic Quasimodo structure: swing sequence H -> L -> HH -> LL (sell) or
L -> H -> LL -> HH (buy), where the 3rd swing ("head") extends past the 1st
and the 4th extends past the 2nd on the opposite side. Entry = a confirming
candle on the retest of the neckline (the 1st point's level) after the 4th
swing forms. Draws the neckline (`neckline`), the head/extreme swing points
(`head_marker`/`extreme_marker`), and the retest entry (`entry_marker_up`/
`entry_marker_down`).

QM2P (same structure + a head trendline the retest must also touch) and QMM
(same structure, but the reversal fails and price continues the original
trend instead) are their own, separate indicators — reversal-only here.

Ported from `_find_qm_structure`/`_classify_pattern` in
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


def _find_qm_structure(raw_points: list) -> dict | None:
    if len(raw_points) < 4:
        return None
    p0, p1, p2, p3 = raw_points[-4:]
    kinds = (p0[2], p1[2], p2[2], p3[2])
    if kinds == ("high", "low", "high", "low") and p2[1] > p0[1] and p3[1] < p1[1]:
        reversal_direction = "sell"
    elif kinds == ("low", "high", "low", "high") and p2[1] < p0[1] and p3[1] > p1[1]:
        reversal_direction = "buy"
    else:
        return None
    return {
        "neckline_idx": p0[0],
        "neckline_price": p0[1],
        "head_idx": p2[0],
        "head_price": p2[1],
        "extreme_idx": p3[0],
        "extreme_price": p3[1],
        "reversal_direction": reversal_direction,
    }


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


def _qm_head_trendline_touches(
    qm: dict, df: pd.DataFrame, i: int, atr_val: float, params: dict
) -> bool:
    line = _fit_trendline(
        [(qm["neckline_idx"], qm["neckline_price"]), (qm["head_idx"], qm["head_price"])]
    )
    if line is None:
        return False
    tolerance = atr_val * params["trendline_tolerance_atr_mult"]
    return _touches_trendline(df, *line, i, tolerance)


class PobQmrIndicator:
    def compute(self, candles: pd.DataFrame, params: dict) -> dict[str, list[float | None]]:
        p = {
            "atr_period": int(params.get("atr_period", 14)),
            "swing_lookback": int(params.get("swing_lookback", 3)),
            "sr_tolerance_atr_mult": float(params.get("sr_tolerance_atr_mult", 0.25)),
            "engulf_min_body_ratio": float(params.get("engulf_min_body_ratio", 0.6)),
            "pin_bar_max_body_ratio": float(params.get("pin_bar_max_body_ratio", 0.35)),
            "pin_bar_min_wick_mult": float(params.get("pin_bar_min_wick_mult", 2.0)),
            "trendline_tolerance_atr_mult": float(params.get("trendline_tolerance_atr_mult", 0.15)),
            "entry_search_bars": int(params.get("entry_search_bars", 60)),
        }

        df = candles.reset_index(drop=True)
        n = len(df)
        neckline: list[float | None] = [None] * n
        head_marker: list[float | None] = [None] * n
        extreme_marker: list[float | None] = [None] * n
        entry_marker_up: list[float | None] = [None] * n
        entry_marker_down: list[float | None] = [None] * n
        if n == 0:
            return self._empty()

        atr = _atr(df, p["atr_period"])
        lookback = p["swing_lookback"]
        is_high, is_low = _swing_flags(df, lookback)
        raw_points = _swing_points_list(df, is_high, is_low)

        for k in range(3, len(raw_points)):
            group = raw_points[k - 3 : k + 1]
            qm = _find_qm_structure(group)
            if qm is None:
                continue
            extreme_idx = qm["extreme_idx"]
            atr_val = atr.iloc[extreme_idx]
            if pd.isna(atr_val) or atr_val <= 0:
                continue
            if _qm_head_trendline_touches(qm, df, extreme_idx, atr_val, p):
                continue  # that's QM2P's variant, not plain QMR

            tolerance = atr_val * p["sr_tolerance_atr_mult"] * 2
            rev_dir = qm["reversal_direction"]
            expected_side = "up" if rev_dir == "buy" else "down"
            horizon = min(n - 1, extreme_idx + p["entry_search_bars"])
            for i in range(extreme_idx + 1, horizon + 1):
                if abs(df["close"].iloc[i] - qm["neckline_price"]) > tolerance:
                    continue
                pattern, side = _classify_pattern(df, i, p)
                if pattern is None or side != expected_side:
                    continue

                for t in range(qm["neckline_idx"], i + 1):
                    neckline[t] = qm["neckline_price"]
                head_marker[qm["head_idx"]] = qm["head_price"]
                extreme_marker[extreme_idx] = qm["extreme_price"]
                if rev_dir == "buy":
                    entry_marker_up[i] = float(df["low"].iloc[i])
                else:
                    entry_marker_down[i] = float(df["high"].iloc[i])
                break

        return {
            "neckline": neckline,
            "head_marker": head_marker,
            "extreme_marker": extreme_marker,
            "entry_marker_up": entry_marker_up,
            "entry_marker_down": entry_marker_down,
        }

    @staticmethod
    def _empty() -> dict[str, list[float | None]]:
        return {
            "neckline": [],
            "head_marker": [],
            "extreme_marker": [],
            "entry_marker_up": [],
            "entry_marker_down": [],
        }
