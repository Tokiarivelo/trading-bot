"""PoB CK1/CK2/CK3 confluence — pp.176-203 of "The Property of Bystra".

Generic trendline-touch confluence, layerable onto *any* setup ("Any setup
+ CK1/CK2/CK3"): CK1 = the current bar touching a trendline fit through the
last 2 swing highs OR the last 2 swing lows; CK2 = touching both at once
(Align/Cross both count as 2 here). Draws `ck1_marker` (1 line touched) and
`ck2_marker` (both lines touched) at the price of the touching bar.

CK3 (CK2 + a solid engulfing candle on a higher timeframe) needs
multi-timeframe data an indicator doesn't have — switch the chart to a
higher timeframe and check this indicator plus the Engulfing Candle
indicator there together, the same manual-confirmation workflow the PDF
itself describes.

Ported from `_count_ck_confluence`/`_fit_trendline`/`_touches_trendline` in
`backend/src/strategies/generated/pob_price_action_snd for vix75_v1.py`,
scanning the full history.
"""

import numpy as np
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


class PobCkConfluenceIndicator:
    def compute(self, candles: pd.DataFrame, params: dict) -> dict[str, list[float | None]]:
        atr_period = int(params.get("atr_period", 14))
        swing_lookback = int(params.get("swing_lookback", 3))
        tolerance_mult = float(params.get("trendline_tolerance_atr_mult", 0.15))

        df = candles.reset_index(drop=True)
        n = len(df)
        ck1_marker: list[float | None] = [None] * n
        ck2_marker: list[float | None] = [None] * n
        if n == 0:
            return {"ck1_marker": ck1_marker, "ck2_marker": ck2_marker}

        atr = _atr(df, atr_period)
        is_high, is_low = _swing_flags(df, swing_lookback)
        raw_points = _swing_points_list(df, is_high, is_low)
        highs_seen: list[tuple[int, float]] = []
        lows_seen: list[tuple[int, float]] = []
        point_idx = 0

        for i in range(n):
            while point_idx < len(raw_points) and raw_points[point_idx][0] <= i:
                idx, price, kind = raw_points[point_idx]
                (highs_seen if kind == "high" else lows_seen).append((idx, price))
                point_idx += 1

            atr_val = atr.iloc[i]
            if pd.isna(atr_val) or atr_val <= 0:
                continue
            tolerance = atr_val * tolerance_mult

            touched = 0
            for pts in (highs_seen[-2:], lows_seen[-2:]):
                line = _fit_trendline(pts)
                if line and _touches_trendline(df, *line, i, tolerance):
                    touched += 1

            if touched == 1:
                ck1_marker[i] = float(df["close"].iloc[i])
            elif touched >= 2:
                ck2_marker[i] = float(df["close"].iloc[i])

        return {"ck1_marker": ck1_marker, "ck2_marker": ck2_marker}
