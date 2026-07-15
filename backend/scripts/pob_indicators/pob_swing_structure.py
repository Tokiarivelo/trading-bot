"""PoB Swing Structure (HH/HL/LH/LL) confirmation — the market-structure
read every Quasimodo/Hybrid/SNRC setup in "The Property of Bystra" is built
on top of.

Labels each swing point against the previous swing of the same type: a
swing high that clears the prior high is HH (higher high), otherwise LH
(lower high); a swing low that clears the prior low is HL (higher low),
otherwise LL (lower low). Draws `hh_marker`/`hl_marker`/`lh_marker`/
`ll_marker` at each swing's price.

Ported from `_swing_flags`/`_swing_points_list`/`_classify_structure` in
`backend/src/strategies/generated/pob_price_action_snd for vix75_v1.py`.
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


class PobSwingStructureIndicator:
    def compute(self, candles: pd.DataFrame, params: dict) -> dict[str, list[float | None]]:
        atr_period = int(params.get("atr_period", 14))
        swing_lookback = int(params.get("swing_lookback", 3))
        margin_mult = float(params.get("structure_margin_atr_mult", 0.1))

        df = candles.reset_index(drop=True)
        n = len(df)
        hh_marker: list[float | None] = [None] * n
        hl_marker: list[float | None] = [None] * n
        lh_marker: list[float | None] = [None] * n
        ll_marker: list[float | None] = [None] * n
        if n == 0:
            return {
                "hh_marker": hh_marker,
                "hl_marker": hl_marker,
                "lh_marker": lh_marker,
                "ll_marker": ll_marker,
            }

        atr = _atr(df, atr_period)
        is_high, is_low = _swing_flags(df, swing_lookback)
        raw_points = _swing_points_list(df, is_high, is_low)

        last_high: float | None = None
        last_low: float | None = None
        for idx, price, kind in raw_points:
            atr_val = atr.iloc[idx]
            margin = 0.0 if pd.isna(atr_val) or atr_val <= 0 else atr_val * margin_mult
            if kind == "high":
                if last_high is not None:
                    if price > last_high + margin:
                        hh_marker[idx] = price
                    else:
                        lh_marker[idx] = price
                last_high = price
            else:
                if last_low is not None:
                    if price > last_low + margin:
                        hl_marker[idx] = price
                    else:
                        ll_marker[idx] = price
                last_low = price

        return {
            "hh_marker": hh_marker,
            "hl_marker": hl_marker,
            "lh_marker": lh_marker,
            "ll_marker": ll_marker,
        }
