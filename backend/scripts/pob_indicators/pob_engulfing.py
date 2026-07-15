"""PoB Engulfing Candle confirmation — "the best confirmation is in the
Engulfing Candle Body" (per "The Property of Bystra").

Marks every bullish and bearish engulfing candle on whichever timeframe/
symbol the chart is showing. This is the standalone confirmation building
block the PDF calls for switching timeframes to check: apply it on M15/M30/
H1/H4 by hand the same way the strategy's multi-timeframe confirmation
does internally. Draws `engulfing_marker_up`/`engulfing_marker_down`.

Ported from `_is_bullish_engulfing`/`_is_bearish_engulfing` in
`backend/src/strategies/generated/pob_price_action_snd for vix75_v1.py`.
"""

import pandas as pd


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


class PobEngulfingIndicator:
    def compute(self, candles: pd.DataFrame, params: dict) -> dict[str, list[float | None]]:
        df = candles.reset_index(drop=True)
        n = len(df)
        up: list[float | None] = [None] * n
        down: list[float | None] = [None] * n
        for i in range(1, n):
            if _is_bullish_engulfing(df, i):
                up[i] = float(df["low"].iloc[i])
            elif _is_bearish_engulfing(df, i):
                down[i] = float(df["high"].iloc[i])
        return {"engulfing_marker_up": up, "engulfing_marker_down": down}
