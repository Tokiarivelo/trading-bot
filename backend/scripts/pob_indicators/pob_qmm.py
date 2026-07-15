"""PoB QMM (Quasimodo Manipulation) — pp.129, 161 of "The Property of Bystra".

Same H -> L -> HH -> LL (or mirror) Quasimodo structure as QMR, but the
reversal *fails*: instead of a confirming reversal candle at the neckline,
price prints a small RBR/DBR base right there and continues the *original*
pre-head trend — the author's "manipulation" read of a QMR that didn't hold.
Draws the neckline (`neckline`), the head/extreme swing points
(`head_marker`/`extreme_marker`), and the manipulation-continuation entry
(`entry_marker_up`/`entry_marker_down`, in the ORIGINAL trend's direction,
opposite of what a QMR reversal would have called). Plain QMR and QM2P
(genuine reversals) are their own, separate indicators.

Ported from `_find_qm_structure`/`_find_qmm_base`/`_classify_pattern` in
`backend/src/strategies/generated/pob_price_action_snd for vix75_v1.py`,
scanning the full history (every past occurrence, not just the most recent)
with no multi-timeframe confirmation or risk gating — those stay strategy
concerns, not chart-annotation ones.
"""

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
        reversal_direction, manipulation_direction = "sell", "buy"
    elif kinds == ("low", "high", "low", "high") and p2[1] < p0[1] and p3[1] > p1[1]:
        reversal_direction, manipulation_direction = "buy", "sell"
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
        "manipulation_direction": manipulation_direction,
    }


def _find_qmm_base(
    df: pd.DataFrame, qm: dict, i: int, atr_val: float, params: dict
) -> dict | None:
    """QM Manipulation (p.129, p.161): the QMR reversal fails — instead of
    confirming at the neckline, price prints a small RBR/DBR base right
    there and continues the *original* pre-head trend."""
    base_len = int(params["impulse_lookback_bars"])
    if i - base_len < 0:
        return None
    base_slice = df.iloc[i - base_len : i]
    if (_range(base_slice) > atr_val * params["base_range_atr_mult"]).any():
        return None
    tolerance = atr_val * params["sr_tolerance_atr_mult"] * 2
    if abs(base_slice["close"].iloc[-1] - qm["neckline_price"]) > tolerance:
        return None
    pattern, side = _classify_pattern(df, i, params)
    manip_side = "up" if qm["manipulation_direction"] == "buy" else "down"
    if pattern is None or side != manip_side:
        return None
    return {"pattern": pattern}


class PobQmmIndicator:
    def compute(self, candles: pd.DataFrame, params: dict) -> dict[str, list[float | None]]:
        p = {
            "atr_period": int(params.get("atr_period", 14)),
            "swing_lookback": int(params.get("swing_lookback", 3)),
            "sr_tolerance_atr_mult": float(params.get("sr_tolerance_atr_mult", 0.25)),
            "engulf_min_body_ratio": float(params.get("engulf_min_body_ratio", 0.6)),
            "pin_bar_max_body_ratio": float(params.get("pin_bar_max_body_ratio", 0.35)),
            "pin_bar_min_wick_mult": float(params.get("pin_bar_min_wick_mult", 2.0)),
            "impulse_lookback_bars": int(params.get("impulse_lookback_bars", 3)),
            "base_range_atr_mult": float(params.get("base_range_atr_mult", 1.0)),
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

            manip_dir = qm["manipulation_direction"]
            horizon = min(n - 1, extreme_idx + p["entry_search_bars"])
            for i in range(extreme_idx + 1, horizon + 1):
                manip = _find_qmm_base(df, qm, i, atr_val, p)
                if manip is None:
                    continue

                for t in range(qm["neckline_idx"], i + 1):
                    neckline[t] = qm["neckline_price"]
                head_marker[qm["head_idx"]] = qm["head_price"]
                extreme_marker[extreme_idx] = qm["extreme_price"]
                if manip_dir == "buy":
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
