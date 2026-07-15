"""PoB Body/Momentum Candle confirmation — "confirmation can also be in the
body candle, as long as the price does not touch the 'end of the trend'"
(per "The Property of Bystra"), the fallback confirmation when a bar isn't
a clean engulfing or pin bar but still has a strong directional body.

Marks every qualifying momentum candle on whichever timeframe/symbol the
chart is showing. Draws `body_candle_marker_up`/`body_candle_marker_down`.

Ported from `_body_candle_side` in
`backend/src/strategies/generated/pob_price_action_snd for vix75_v1.py`.
"""

import pandas as pd


def _range(df: pd.DataFrame) -> pd.Series:
    return df["high"] - df["low"]


def _body(df: pd.DataFrame) -> pd.Series:
    return (df["close"] - df["open"]).abs()


def _body_candle_side(df: pd.DataFrame, i: int, min_body_ratio: float) -> tuple[bool, str]:
    rng = _range(df).iloc[i]
    if rng <= 0:
        return False, ""
    if _body(df).iloc[i] / rng < min_body_ratio:
        return False, ""
    return True, ("up" if df["close"].iloc[i] > df["open"].iloc[i] else "down")


class PobBodyCandleIndicator:
    def compute(self, candles: pd.DataFrame, params: dict) -> dict[str, list[float | None]]:
        min_body_ratio = float(params.get("engulf_min_body_ratio", 0.6))
        df = candles.reset_index(drop=True)
        n = len(df)
        up: list[float | None] = [None] * n
        down: list[float | None] = [None] * n
        for i in range(n):
            strong, side = _body_candle_side(df, i, min_body_ratio)
            if not strong:
                continue
            if side == "up":
                up[i] = float(df["low"].iloc[i])
            else:
                down[i] = float(df["high"].iloc[i])
        return {"body_candle_marker_up": up, "body_candle_marker_down": down}
