"""PoB Pin Bar confirmation — a rejection candle (small body pinned near one
end of the bar's range with a long opposite wick), the standard SnD
zone-rejection confirmation alongside engulfing and body candles in "The
Property of Bystra".

Marks every bullish/bearish pin bar on whichever timeframe/symbol the chart
is showing — apply it by hand on a higher timeframe the same way the
strategy's multi-timeframe confirmation checks it internally. Draws
`pin_bar_marker_up`/`pin_bar_marker_down`.

Ported from `_is_pin_bar` in
`backend/src/strategies/generated/pob_price_action_snd for vix75_v1.py`.
"""

import pandas as pd


def _range(df: pd.DataFrame) -> pd.Series:
    return df["high"] - df["low"]


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


class PobPinBarIndicator:
    def compute(self, candles: pd.DataFrame, params: dict) -> dict[str, list[float | None]]:
        max_body_ratio = float(params.get("pin_bar_max_body_ratio", 0.35))
        min_wick_mult = float(params.get("pin_bar_min_wick_mult", 2.0))
        df = candles.reset_index(drop=True)
        n = len(df)
        up: list[float | None] = [None] * n
        down: list[float | None] = [None] * n
        for i in range(n):
            is_pin, side = _is_pin_bar(df, i, max_body_ratio, min_wick_mult)
            if not is_pin:
                continue
            if side == "up":
                up[i] = float(df["low"].iloc[i])
            else:
                down[i] = float(df["high"].iloc[i])
        return {"pin_bar_marker_up": up, "pin_bar_marker_down": down}
