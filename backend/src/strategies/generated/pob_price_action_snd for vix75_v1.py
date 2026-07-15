import numpy as np
import pandas as pd

from src.strategies.domain.models import (
    Direction,
    MarketContext,
    PriceZone,
    Signal,
    StrategySpec,
    StructureLabel,
    StructurePoint,
    ZoneKind,
)


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


def _body(df: pd.DataFrame) -> pd.Series:
    return (df["close"] - df["open"]).abs()


def _range(df: pd.DataFrame) -> pd.Series:
    return df["high"] - df["low"]


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
    """Rejection candle: a small body pinned near one end of the bar's range
    with a long opposite wick — the standard SnD zone-rejection confirmation
    alongside engulfing and body candles."""
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
    """The confirming candlestick pattern at bar `i`, strongest match first
    (engulfing > pin bar > plain body/momentum candle), and the side it
    implies. Returns (None, None) when nothing recognized matches."""
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


def _swing_points_list(
    sr_slice: pd.DataFrame, is_high: pd.Series, is_low: pd.Series
) -> list[tuple[int, float, str]]:
    """Chronological `(index, price, "high"|"low")` swing points — shared by
    `_classify_structure` (HH/LH/HL/LL labeling) and the trendline/Quasimodo
    pattern detectors below, so both read the exact same swing sequence."""
    points: list[tuple[int, float, str]] = []
    for i in range(len(sr_slice)):
        if is_high.iloc[i]:
            points.append((i, float(sr_slice["high"].iloc[i]), "high"))
        elif is_low.iloc[i]:
            points.append((i, float(sr_slice["low"].iloc[i]), "low"))
    points.sort(key=lambda p: p[0])
    return points


def _classify_structure(
    sr_slice: pd.DataFrame,
    is_high: pd.Series,
    is_low: pd.Series,
    max_points: int,
    margin: float = 0.0,
) -> tuple[StructurePoint, ...]:
    """Labels each swing point in chronological order against the previous
    swing of the same type (HH/LH for swing highs, HL/LL for swing lows) —
    the reversal-vs-continuation read the strategy's own spec calls for.
    Informational only: exposed for chart drawing, not used to gate entries,
    so it can't starve signal generation the way the old impulse-move check
    did.

    `margin` (an absolute price distance, e.g. `atr_val * some_fraction`)
    requires a swing to clearly clear the prior one by more than noise before
    it's called "higher" — without it, two swings a fraction of a point apart
    (essentially a retest) flip unpredictably between HH/LH or HL/LL."""
    points = _swing_points_list(sr_slice, is_high, is_low)

    structure: list[StructurePoint] = []
    last_high: float | None = None
    last_low: float | None = None
    for idx, price, kind in points:
        if kind == "high":
            if last_high is not None:
                label = StructureLabel.HH if price > last_high + margin else StructureLabel.LH
                point = StructurePoint(time=sr_slice["time"].iloc[idx], price=price, label=label)
                structure.append(point)
            last_high = price
        else:
            if last_low is not None:
                label = StructureLabel.HL if price > last_low + margin else StructureLabel.LL
                point = StructurePoint(time=sr_slice["time"].iloc[idx], price=price, label=label)
                structure.append(point)
            last_low = price
    return tuple(structure[-max_points:])


def _count_sr_touches(
    df: pd.DataFrame,
    level_low: float,
    level_high: float,
    is_high: pd.Series,
    is_low: pd.Series,
    tolerance: float,
) -> int:
    mid = (level_low + level_high) / 2
    touches = 0
    for i in range(len(df)):
        high_touch = is_high.iloc[i] and abs(df["high"].iloc[i] - mid) <= tolerance
        low_touch = is_low.iloc[i] and abs(df["low"].iloc[i] - mid) <= tolerance
        if high_touch or low_touch:
            touches += 1
    return touches


def _fit_trendline(points: list[tuple[int, float]]) -> tuple[float, float] | None:
    """Least-squares slope/intercept (`price = slope*index + intercept`)
    through swing-point `(index, price)` pairs — the trendline fit shared by
    CK1-3, QMC, QM2P, and Hybrid's break/channel detection below. `None` for
    fewer than 2 points or points that share the same index."""
    if len(points) < 2:
        return None
    xs = np.array([p[0] for p in points], dtype=float)
    ys = np.array([p[1] for p in points], dtype=float)
    if np.all(xs == xs[0]):
        return None
    slope, intercept = np.polyfit(xs, ys, 1)
    return float(slope), float(intercept)


def _trendline_value_at(slope: float, intercept: float, i: int) -> float:
    return slope * i + intercept


def _touches_trendline(
    df: pd.DataFrame, slope: float, intercept: float, i: int, tolerance: float
) -> bool:
    line_val = _trendline_value_at(slope, intercept, i)
    return bool(
        abs(df["high"].iloc[i] - line_val) <= tolerance
        or abs(df["low"].iloc[i] - line_val) <= tolerance
    )


def _count_ck_confluence(
    raw_points: list[tuple[int, float, str]], sr_slice: pd.DataFrame, atr_val: float, params: dict
) -> int:
    """CK1/CK2 confluence (pp.176-201): how many of the two possible
    trendlines — one through the last 2 swing highs, one through the last 2
    swing lows — the current bar is touching. CK1 = 1 line, CK2 = both
    (Align/Cross both count as 2 here, per the plan's scoping). This never
    gates a signal, only adds to its confidence: 'Any setup + CK1/CK2/CK3'."""
    cur_i = len(sr_slice) - 1
    tolerance = atr_val * params["trendline_tolerance_atr_mult"]
    highs = [(p[0], p[1]) for p in raw_points if p[2] == "high"]
    lows = [(p[0], p[1]) for p in raw_points if p[2] == "low"]

    touched = 0
    for pts in (highs[-2:], lows[-2:]):
        line = _fit_trendline(pts)
        if line and _touches_trendline(sr_slice, *line, cur_i, tolerance):
            touched += 1
    return touched


def _htf_has_solid_engulf(ctx: MarketContext, direction: Direction, params: dict) -> bool:
    """CK3's extra requirement over CK2: a near-full-body engulfing candle on
    some confirmation timeframe — stricter than the plain engulfing check
    `_mtf_confirms` already does, since here the body itself must fill most
    of the bar's range, not just clear the prior candle."""
    for tf in ctx.candles:
        tf_df = ctx.candles.get(tf)
        if tf_df is None or len(tf_df) < 2:
            continue
        i = len(tf_df) - 1
        is_engulf = (
            _is_bullish_engulfing(tf_df, i)
            if direction == Direction.BUY
            else _is_bearish_engulfing(tf_df, i)
        )
        if not is_engulf:
            continue
        strong, side = _body_candle_side(tf_df, i, params["ck3_solid_body_ratio"])
        if strong and side == ("up" if direction == Direction.BUY else "down"):
            return True
    return False


def _find_qm_structure(raw_points: list[tuple[int, float, str]]) -> dict | None:
    """Quasimodo H/L/HH/LL structure — the last 4 alternating swing points
    where the 3rd extends beyond the 1st and the 4th extends beyond the 2nd
    on the opposite side (QMR Formula pp.90-91). Returns the neckline (the
    1st point) and the head (the 3rd point, HH/LL) for QM2P's trendline, plus
    both the reversal direction (QMR) and its opposite (QMM, when the
    reversal fails). `None` unless the last 4 swings actually form this
    shape — a broken alternation (e.g. two lows in a row) is treated as 'no
    pattern' rather than guessed at."""
    if len(raw_points) < 4:
        return None
    p0, p1, p2, p3 = raw_points[-4:]
    kinds = (p0[2], p1[2], p2[2], p3[2])
    if kinds == ("high", "low", "high", "low") and p2[1] > p0[1] and p3[1] < p1[1]:
        reversal_direction = Direction.SELL
    elif kinds == ("low", "high", "low", "high") and p2[1] < p0[1] and p3[1] > p1[1]:
        reversal_direction = Direction.BUY
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
        "manipulation_direction": Direction.BUY
        if reversal_direction == Direction.SELL
        else Direction.SELL,
    }


def _qm_head_trendline_touches(
    qm: dict, sr_slice: pd.DataFrame, atr_val: float, params: dict
) -> bool:
    """QM2P (p.120): QMR + a trendline through the two points framing the
    head (the neckline point and the head extreme) that the neckline retest
    also has to touch/break — the extra confluence that upgrades a QMR
    reversal from 'high' risk to 'medium'."""
    line = _fit_trendline(
        [(qm["neckline_idx"], qm["neckline_price"]), (qm["head_idx"], qm["head_price"])]
    )
    if line is None:
        return False
    tolerance = atr_val * params["trendline_tolerance_atr_mult"]
    return _touches_trendline(sr_slice, *line, len(sr_slice) - 1, tolerance)


def _find_qmm_base(sr_slice: pd.DataFrame, qm: dict, atr_val: float, params: dict) -> dict | None:
    """QM Manipulation (p.129, p.161): the QMR reversal fails — instead of
    confirming at the neckline, price prints a small RBR/DBR base right
    there and continues the *original* pre-head trend. Reuses the same
    compression check `_find_base` uses for the SNRC bases, anchored at the
    neckline instead of scanned backward from the last bar."""
    last_i = len(sr_slice) - 1
    base_len = int(params["impulse_lookback_bars"])
    if last_i - base_len < 0:
        return None
    base_slice = sr_slice.iloc[last_i - base_len : last_i]
    if (_range(base_slice) > atr_val * params["base_range_atr_mult"]).any():
        return None
    tolerance = atr_val * params["sr_tolerance_atr_mult"] * 2
    if abs(base_slice["close"].iloc[-1] - qm["neckline_price"]) > tolerance:
        return None
    pattern, side = _classify_pattern(sr_slice, last_i, params)
    manip_side = "up" if qm["manipulation_direction"] == Direction.BUY else "down"
    if pattern is None or side != manip_side:
        return None
    return {"pattern": pattern}


def _find_qmc(
    raw_points: list[tuple[int, float, str]], sr_slice: pd.DataFrame, atr_val: float, params: dict
) -> dict | None:
    """QMC — 3 drives continuation (p.107): a trendline fit through the two
    most recent same-side swing extremes ('make sure LL is at the 2nd
    drive'), which the current bar is now touching for a 3rd time, in the
    direction of the prevailing trend (unlike QMR/QM2P/QMM, this is a
    continuation setup, not a reversal)."""
    cur_i = len(sr_slice) - 1
    tolerance = atr_val * params["trendline_tolerance_atr_mult"]
    lows = [p for p in raw_points if p[2] == "low"]
    highs = [p for p in raw_points if p[2] == "high"]

    if len(lows) >= 2 and lows[-1][1] < lows[-2][1]:
        line = _fit_trendline([(lows[-2][0], lows[-2][1]), (lows[-1][0], lows[-1][1])])
        if line and _touches_trendline(sr_slice, *line, cur_i, tolerance):
            pattern, side = _classify_pattern(sr_slice, cur_i, params)
            if pattern is not None and side == "up":
                return {
                    "direction": Direction.BUY,
                    "pattern": pattern,
                    "structural_idx": lows[-1][0],
                    "structural_price": lows[-1][1],
                }
    if len(highs) >= 2 and highs[-1][1] > highs[-2][1]:
        line = _fit_trendline([(highs[-2][0], highs[-2][1]), (highs[-1][0], highs[-1][1])])
        if line and _touches_trendline(sr_slice, *line, cur_i, tolerance):
            pattern, side = _classify_pattern(sr_slice, cur_i, params)
            if pattern is not None and side == "down":
                return {
                    "direction": Direction.SELL,
                    "pattern": pattern,
                    "structural_idx": highs[-1][0],
                    "structural_price": highs[-1][1],
                }
    return None


def _find_hybrid(
    raw_points: list[tuple[int, float, str]], sr_slice: pd.DataFrame, atr_val: float, params: dict
) -> dict | None:
    """Hybrid 1/2 (pp.28-43): an established, clean trendline through >= 3
    same-side swings breaks, and price retests a fresh compression zone
    printed right at the break for entry — the Danger Zone validity check
    (pp.28-43) on that prior trend (see below). Hybrid 2 additionally
    requires a second, more recent trendline on the opposite side (a
    channel) that the same bar also touches."""
    last_i = len(sr_slice) - 1
    tolerance = atr_val * params["trendline_tolerance_atr_mult"]
    min_pts = int(params["hybrid_min_trendline_points"])

    for side, break_up in (("high", False), ("low", True)):
        same_side = [p for p in raw_points if p[2] == side]
        if len(same_side) < min_pts:
            continue
        pts = [(p[0], p[1]) for p in same_side[-min_pts:]]
        line = _fit_trendline(pts)
        if line is None:
            continue
        slope, intercept = line
        # A real trend has a slope sign matching the side (a falling
        # resistance line above a downtrend's highs breaks upward; a rising
        # support line below an uptrend's lows breaks downward) — otherwise
        # there's no established trend here to break.
        if break_up and slope >= 0:
            continue
        if not break_up and slope <= 0:
            continue

        line_val = _trendline_value_at(slope, intercept, last_i)
        close = sr_slice["close"].iloc[last_i]
        broke = close > line_val + tolerance if break_up else close < line_val - tolerance
        if not broke:
            continue

        direction = Direction.BUY if break_up else Direction.SELL
        pattern, psid = _classify_pattern(sr_slice, last_i, params)
        expected_side = "up" if break_up else "down"
        if pattern is None or psid != expected_side:
            continue

        # Danger Zone (pp.28-43): a validity check on the *prior* trend's
        # formation ("if the price has touched Danger Zone, this setup is
        # invalid"), not a stop-loss level for the new trade. The direct
        # reading — did price retrace back toward the trendline's origin at
        # any point during formation — needs the pre-origin history this
        # window doesn't always carry, so this uses a conservative, always-
        # computable proxy instead: the points that make up the trendline
        # itself must be strictly monotonic (each one genuinely more extreme
        # than the last). A choppy/retraced formation fails this the same
        # way it would fail the diagram's literal check.
        trend_prices = [p[1] for p in pts]
        pairs = list(zip(trend_prices, trend_prices[1:], strict=False))
        is_clean_trend = all(a > b for a, b in pairs) if break_up else all(a < b for a, b in pairs)
        if not is_clean_trend:
            continue

        origin_idx = same_side[-min_pts][0]
        opposite_side = "low" if side == "high" else "high"
        opposite_pool = [p for p in raw_points if p[2] == opposite_side and p[0] > origin_idx]
        is_hybrid2 = False
        if len(opposite_pool) >= 2:
            channel = _fit_trendline([(p[0], p[1]) for p in opposite_pool[-2:]])
            if channel and _touches_trendline(sr_slice, *channel, last_i, tolerance):
                is_hybrid2 = True

        # The stop sits at the most recent same-side swing (the zone the
        # break/retest actually happened at) — the Danger Zone check above is
        # a validity gate on the *prior* trend, not where this trade's own
        # stop belongs, same distinction SNRC draws with its local-base anchor.
        retest_idx, retest_price = same_side[-1][0], same_side[-1][1]
        return {
            "setup": "Hybrid2" if is_hybrid2 else "Hybrid1",
            "direction": direction,
            "risk": "medium" if is_hybrid2 else "high",
            "pattern": pattern,
            "structural_idx": retest_idx,
            "structural_price": retest_price,
        }
    return None


def _find_blindspot(
    raw_points: list[tuple[int, float, str]], sr_slice: pd.DataFrame, atr_val: float, params: dict
) -> dict | None:
    """Blindspot 1/2 (pp.139-160): a failed engulfing candle, followed later
    by a candle that closes beyond it (the 'significant break'), entry at a
    retest of that break level. The author explicitly distrusts this family
    ('not all types of swaps can be trusted') — always tagged high risk, even
    with the Blindspot 2 trendline addition, unlike the other setups' 'medium'
    upgrade tier."""
    n = len(sr_slice)
    last_i = n - 1
    lookback = int(params["blindspot_lookback_bars"])
    if last_i - lookback < 1:
        return None

    for j in range(last_i - lookback, last_i):
        is_bull = _is_bullish_engulfing(sr_slice, j)
        is_bear = _is_bearish_engulfing(sr_slice, j)
        if not (is_bull or is_bear):
            continue
        ref_low, ref_high = sr_slice["low"].iloc[j], sr_slice["high"].iloc[j]
        later_closes = sr_slice["close"].iloc[j + 1 : last_i]
        if is_bull and (later_closes < ref_low).any():
            direction, break_level = Direction.SELL, ref_low
        elif is_bear and (later_closes > ref_high).any():
            direction, break_level = Direction.BUY, ref_high
        else:
            continue

        tolerance = atr_val * params["sr_tolerance_atr_mult"] * 2
        if abs(sr_slice["close"].iloc[last_i] - break_level) > tolerance:
            continue
        pattern, side = _classify_pattern(sr_slice, last_i, params)
        expected_side = "up" if direction == Direction.BUY else "down"
        if pattern is None or side != expected_side:
            continue

        trend_side = "low" if direction == Direction.BUY else "high"
        same_side = [p for p in raw_points if p[2] == trend_side]
        has_trendline = False
        if len(same_side) >= 2:
            line = _fit_trendline([(p[0], p[1]) for p in same_side[-2:]])
            if line:
                trend_tol = atr_val * params["trendline_tolerance_atr_mult"]
                has_trendline = _touches_trendline(sr_slice, *line, last_i, trend_tol)

        return {
            "setup": "Blindspot2" if has_trendline else "Blindspot1",
            "direction": direction,
            "risk": "high",
            "pattern": pattern,
            "structural_idx": j,
            "structural_price": break_level,
        }
    return None


_HIGH_RISK_SETUPS = frozenset({"QMR", "QMM", "Hybrid1", "Blindspot1", "Blindspot2"})
_MEDIUM_RISK_SETUPS = frozenset({"QM2P", "QMC", "Hybrid2"})


def _confidence_cap_for(reason: str, params: dict) -> float:
    """The confidence ceiling a signal's own risk tier already used, keyed
    off the leading setup tag in `reason` — so CK confluence (which only
    ever *adds* confidence) can't push a 'high risk' reversal setup's
    confidence back above the cap that made it high risk in the first place.
    Blindspot 2 stays in the high-risk set: the author distrusts this family
    regardless of the trendline addition (pp.139-160)."""
    setup_tag = reason.split(" ", 1)[0]
    if setup_tag in _HIGH_RISK_SETUPS:
        return params["reversal_confidence_cap"]
    if setup_tag in _MEDIUM_RISK_SETUPS:
        return params["reversal_confidence_cap_confirmed"]
    return 0.95


def _find_base(df: pd.DataFrame, atr: pd.Series, params: dict) -> dict | None:
    n = len(df)
    last_idx = n - 1
    current_atr = atr.iloc[last_idx]
    if pd.isna(current_atr) or current_atr <= 0:
        return None

    impulse_bars = int(params["impulse_lookback_bars"])
    for base_len in range(2, int(params["base_max_bars"]) + 1):
        base_start = last_idx - base_len
        base_end = last_idx - 1
        if base_start - impulse_bars < 0:
            continue

        base_slice = df.iloc[base_start : base_end + 1]
        # Base-bar range vs current ATR: VIX75's median M5 bar range is ~= its
        # own ATR(14) (unlike calmer FX pairs where a base is visibly tighter
        # than ATR), so a 0.6x cap matched almost no real bars and starved
        # _find_base of any candidates. 1.0x keeps this a real compression
        # filter while actually firing on this instrument.
        if (_range(base_slice) > current_atr * params["base_range_atr_mult"]).any():
            continue

        pre_slice = df.iloc[base_start - impulse_bars : base_start]
        pre_move = pre_slice["close"].iloc[-1] - pre_slice["close"].iloc[0]
        if abs(pre_move) < current_atr * params["impulse_min_atr_mult"]:
            continue

        return {
            "base_start": base_start,
            "base_high": base_slice["high"].max(),
            "base_low": base_slice["low"].min(),
            "leg_before": "up" if pre_move > 0 else "down",
        }
    return None


def _danger_zone_breached(
    df: pd.DataFrame,
    base_low: float,
    base_high: float,
    direction: Direction,
    atr_val: float,
    mult: float,
    from_idx: int,
) -> bool:
    if direction == Direction.BUY:
        return bool((df["low"].iloc[from_idx:] < base_low - atr_val * mult).any())
    return bool((df["high"].iloc[from_idx:] > base_high + atr_val * mult).any())


def _mtf_confirms(ctx: MarketContext, tf: str, direction: Direction, params: dict) -> bool:
    df = ctx.candles.get(tf)
    lookback = int(params["confirm_lookback"])
    if df is None or len(df) < lookback + 2:
        return False
    start_i = len(df) - lookback
    for i in range(start_i, len(df)):
        if direction == Direction.BUY:
            if _is_bullish_engulfing(df, i):
                return True
            strong, side = _body_candle_side(df, i, params["mtf_min_body_ratio"])
            if strong and side == "up":
                return True
        else:
            if _is_bearish_engulfing(df, i):
                return True
            strong, side = _body_candle_side(df, i, params["mtf_min_body_ratio"])
            if strong and side == "down":
                return True
    return False


class PobPriceActionSnd:
    def __init__(self) -> None:
        self.spec = StrategySpec(
            name="pob_price_action_snd",
            version=1,
            symbols=("Volatility 75 Index",),
            entry_timeframe="M5",
            confirmation_timeframes=("M15", "M30", "H1", "H4"),
            params={
                "swing_lookback": 3,
                "base_max_bars": 4,
                "impulse_lookback_bars": 3,
                "base_range_atr_mult": 1.0,
                "impulse_min_atr_mult": 1.0,
                "sr_lookback_bars": 100,
                "sr_tolerance_atr_mult": 0.25,
                "sr_min_touches": 2,
                "danger_zone_atr_mult": 0.5,
                "engulf_min_body_ratio": 0.6,
                "mtf_min_body_ratio": 0.4,
                "pin_bar_max_body_ratio": 0.35,
                "pin_bar_min_wick_mult": 2.0,
                "structure_max_points": 8,
                "structure_margin_atr_mult": 0.1,
                "confirm_lookback": 6,
                "min_confirmations": 2,
                "atr_period": 14,
                "sl_atr_mult": 1.2,
                "reward_risk_ratio": 1.8,
                "min_confidence": 0.5,
                # Reversal-category setups (Hybrid/QM/Blindspot, pp.28-161) —
                # opt-in only. The author himself treats these as high risk
                # ("I always FAST Hybrid 1 setup"), and this file backs a
                # live-assigned bot, so new signal types must not change what
                # it already trades until reviewed on a backtest. See the
                # `pob_price_action_snd`-extension plan for the reasoning.
                "enable_reversal_setups": False,
                # CK1/CK2/CK3 confluence (pp.176-203) — purely additive
                # (confidence boost only, never gates a signal), so this is
                # safe on by default for both SNRC and reversal setups.
                "enable_ck_confluence": True,
                "trendline_tolerance_atr_mult": 0.15,
                "ck3_solid_body_ratio": 0.75,
                "hybrid_min_trendline_points": 3,
                "blindspot_lookback_bars": 15,
                "reversal_min_confirmations_bonus": 1,
                "reversal_confidence_cap": 0.6,
                "reversal_confidence_cap_confirmed": 0.75,
            },
        )

    def evaluate(self, ctx: MarketContext) -> Signal | None:
        params = self.spec.params
        df = ctx.candles.get(self.spec.entry_timeframe)
        min_bars = int(params["sr_lookback_bars"]) + int(params["base_max_bars"]) + 10
        if df is None or len(df) < min_bars:
            return None

        atr = _atr(df, int(params["atr_period"]))
        atr_val = atr.iloc[-1]
        if pd.isna(atr_val) or atr_val <= 0:
            return None

        signal = self._evaluate_snrc(df, atr, atr_val, ctx, params)
        if signal is None and params.get("enable_reversal_setups"):
            signal = self._evaluate_reversal(df, atr_val, ctx, params)
        if signal is not None and params.get("enable_ck_confluence"):
            signal = self._apply_ck_confluence(signal, ctx, df, atr_val, params)
        return signal

    def _evaluate_snrc(
        self,
        df: pd.DataFrame,
        atr: pd.Series,
        atr_val: float,
        ctx: MarketContext,
        params: dict,
    ) -> Signal | None:
        """SNRC1/SNRC2 continuation setups — unchanged from the original
        implementation (only moved into its own method), so it keeps working
        as a pure regression guard against the reversal-setup additions."""
        base = _find_base(df, atr, params)
        if base is None:
            return None

        last_i = len(df) - 1
        pattern, side = _classify_pattern(df, last_i, params)
        if pattern is None:
            return None
        breakout_up = side == "up"
        breakout_down = side == "down"

        leg_before = base["leg_before"]
        base_high, base_low = base["base_high"], base["base_low"]

        # Reversal-only setups (Hybrid/QM/Blindspot) are the author's high-risk
        # "FAST"-skip category; only structurally confirmed rally/drop-base
        # entries at a tested support/resistance line are traded here.
        if leg_before == "up" and breakout_up:
            direction, setup = Direction.BUY, "SNRC1-RBR"
        elif leg_before == "down" and breakout_down:
            direction, setup = Direction.SELL, "SNRC1-DBD"
        elif leg_before == "up" and breakout_down:
            direction, setup = Direction.SELL, "SNRC2-RBD"
        elif leg_before == "down" and breakout_up:
            direction, setup = Direction.BUY, "SNRC2-DBR"
        else:
            return None

        sr_window_end = base["base_start"]
        sr_window_start = max(0, sr_window_end - int(params["sr_lookback_bars"]))
        sr_slice = df.iloc[sr_window_start:sr_window_end].reset_index(drop=True)
        tolerance = atr_val * params["sr_tolerance_atr_mult"]
        strong_sr = False
        structure: tuple[StructurePoint, ...] = ()
        if len(sr_slice) > 2 * int(params["swing_lookback"]) + 1:
            is_high, is_low = _swing_flags(sr_slice, int(params["swing_lookback"]))
            touches = _count_sr_touches(sr_slice, base_low, base_high, is_high, is_low, tolerance)
            strong_sr = touches >= int(params["sr_min_touches"])
            max_points = int(params["structure_max_points"])
            structure_margin = atr_val * params["structure_margin_atr_mult"]
            structure = _classify_structure(
                sr_slice, is_high, is_low, max_points, margin=structure_margin
            )
        if not strong_sr:
            return None

        danger_mult = params["danger_zone_atr_mult"]
        if _danger_zone_breached(
            df, base_low, base_high, direction, atr_val, danger_mult, base["base_start"]
        ):
            return None

        confirmations = sum(
            1
            for tf in self.spec.confirmation_timeframes
            if _mtf_confirms(ctx, tf, direction, params)
        )
        if confirmations < int(params["min_confirmations"]):
            return None

        confidence = 0.5 if setup.startswith("SNRC1") else 0.45
        confidence += 0.1 * confirmations
        confidence = min(confidence, 0.95)
        if confidence < params["min_confidence"]:
            return None

        entry_price = df["close"].iloc[last_i]
        if direction == Direction.BUY:
            structural_level = base_low - atr_val * params["danger_zone_atr_mult"]
            structural_dist = entry_price - structural_level
        else:
            structural_level = base_high + atr_val * params["danger_zone_atr_mult"]
            structural_dist = structural_level - entry_price

        sl_points = max(structural_dist, atr_val * params["sl_atr_mult"])
        tp_points = sl_points * params["reward_risk_ratio"]

        if direction == Direction.BUY:
            sl_price = entry_price - sl_points
            tp_price = entry_price + tp_points
        else:
            sl_price = entry_price + sl_points
            tp_price = entry_price - tp_points

        zone = PriceZone(
            kind=ZoneKind.DEMAND if direction == Direction.BUY else ZoneKind.SUPPLY,
            price_low=float(base_low),
            price_high=float(base_high),
            time_start=df["time"].iloc[base["base_start"]],
            time_end=df["time"].iloc[last_i],
        )

        n_confirm_tfs = len(self.spec.confirmation_timeframes)
        reason = (
            f"{setup} pattern={pattern} zone_rect=[{base_low:.2f},{base_high:.2f}] "
            f"leg_before={leg_before} strong_sr_touches_ok "
            f"mtf_confirms={confirmations}/{n_confirm_tfs} "
            f"danger_zone_clear lines: entry={entry_price:.2f} sl={sl_price:.2f} tp={tp_price:.2f}"
        )

        return Signal(
            direction=direction,
            sl_points=float(sl_points),
            tp_points=float(tp_points),
            confidence=float(confidence),
            reason=reason,
            zone=zone,
            pattern=pattern,
            structure=structure,
        )

    def _find_reversal_match(
        self,
        raw_points: list[tuple[int, float, str]],
        sr_slice: pd.DataFrame,
        atr_val: float,
        params: dict,
    ) -> dict | None:
        """Try each reversal-category detector in turn, first match wins:
        QMR/QM2P/QMM (a shared H/L/HH/LL structure, pp.89-138) first since
        QMC/Hybrid/Blindspot all reuse the same swing-point list without
        depending on that structure existing. Each returns
        `{setup, direction, risk, pattern, structural_idx, structural_price}`."""
        qm = _find_qm_structure(raw_points)
        if qm is not None:
            cur_i = len(sr_slice) - 1
            neckline_tolerance = atr_val * params["sr_tolerance_atr_mult"] * 2
            at_neckline = (
                abs(sr_slice["close"].iloc[cur_i] - qm["neckline_price"]) <= neckline_tolerance
            )
            if at_neckline:
                pattern, side = _classify_pattern(sr_slice, cur_i, params)
                rev_dir = qm["reversal_direction"]
                rev_side = "up" if rev_dir == Direction.BUY else "down"
                if pattern is not None and side == rev_side:
                    is_qm2p = _qm_head_trendline_touches(qm, sr_slice, atr_val, params)
                    return {
                        "setup": "QM2P" if is_qm2p else "QMR",
                        "direction": rev_dir,
                        "risk": "medium" if is_qm2p else "high",
                        "pattern": pattern,
                        # Stop belongs beyond the head (QMR Formula p.90) —
                        # the neckline retest is the entry, not the invalidation.
                        "structural_idx": qm["head_idx"],
                        "structural_price": qm["head_price"],
                    }
                manip = _find_qmm_base(sr_slice, qm, atr_val, params)
                if manip is not None:
                    return {
                        "setup": "QMM",
                        "direction": qm["manipulation_direction"],
                        "risk": "high",
                        "pattern": manip["pattern"],
                        "structural_idx": qm["neckline_idx"],
                        "structural_price": qm["neckline_price"],
                    }

        qmc = _find_qmc(raw_points, sr_slice, atr_val, params)
        if qmc is not None:
            return {
                "setup": "QMC",
                "direction": qmc["direction"],
                "risk": "medium",
                "pattern": qmc["pattern"],
                "structural_idx": qmc["structural_idx"],
                "structural_price": qmc["structural_price"],
            }

        hybrid = _find_hybrid(raw_points, sr_slice, atr_val, params)
        if hybrid is not None:
            return hybrid

        return _find_blindspot(raw_points, sr_slice, atr_val, params)

    def _evaluate_reversal(
        self, df: pd.DataFrame, atr_val: float, ctx: MarketContext, params: dict
    ) -> Signal | None:
        """QMR/QM2P/QMM, QMC, Hybrid 1/2, and Blindspot 1/2 (pp.28-161) — only
        tried when SNRC1/SNRC2 found nothing, and only when
        `enable_reversal_setups` is on. Risk-tiered per the author's own
        distinction between the setups he skips outright ('high') and the
        ones he'll take once they carry extra trendline/MTF confluence
        ('medium') — both tiers still pass the existing MTF-confirmation gate,
        just with a higher bar (`reversal_min_confirmations_bonus`) and a
        lower confidence ceiling than SNRC's."""
        last_i = len(df) - 1
        window_start = max(0, last_i + 1 - int(params["sr_lookback_bars"]))
        sr_slice = df.iloc[window_start : last_i + 1].reset_index(drop=True)
        lookback = int(params["swing_lookback"])
        if len(sr_slice) <= 2 * lookback + 1:
            return None

        is_high, is_low = _swing_flags(sr_slice, lookback)
        raw_points = _swing_points_list(sr_slice, is_high, is_low)
        max_points = int(params["structure_max_points"])
        structure_margin = atr_val * params["structure_margin_atr_mult"]
        structure = _classify_structure(
            sr_slice, is_high, is_low, max_points, margin=structure_margin
        )

        found = self._find_reversal_match(raw_points, sr_slice, atr_val, params)
        if found is None:
            return None

        direction = found["direction"]
        confirmations = sum(
            1
            for tf in self.spec.confirmation_timeframes
            if _mtf_confirms(ctx, tf, direction, params)
        )
        min_confirm = int(params["min_confirmations"]) + int(
            params["reversal_min_confirmations_bonus"]
        )
        if confirmations < min_confirm:
            return None

        cap = (
            params["reversal_confidence_cap"]
            if found["risk"] == "high"
            else params["reversal_confidence_cap_confirmed"]
        )
        confidence = min(0.4 + 0.1 * confirmations, cap)
        if confidence < params["min_confidence"]:
            return None

        cur_i = len(sr_slice) - 1
        entry_price = sr_slice["close"].iloc[cur_i]
        structural_price = found["structural_price"]
        buffer = atr_val * params["danger_zone_atr_mult"]
        if direction == Direction.BUY:
            structural_level = structural_price - buffer
            structural_dist = entry_price - structural_level
        else:
            structural_level = structural_price + buffer
            structural_dist = structural_level - entry_price

        sl_points = max(structural_dist, atr_val * params["sl_atr_mult"])
        tp_points = sl_points * params["reward_risk_ratio"]
        if direction == Direction.BUY:
            sl_price = entry_price - sl_points
            tp_price = entry_price + tp_points
        else:
            sl_price = entry_price + sl_points
            tp_price = entry_price - tp_points

        n_confirm_tfs = len(self.spec.confirmation_timeframes)
        reason = (
            f"{found['setup']} risk={found['risk']} pattern={found['pattern']} "
            f"mtf_confirms={confirmations}/{n_confirm_tfs} "
            f"lines: entry={entry_price:.2f} sl={sl_price:.2f} tp={tp_price:.2f}"
        )
        return Signal(
            direction=direction,
            sl_points=float(sl_points),
            tp_points=float(tp_points),
            confidence=float(confidence),
            reason=reason,
            pattern=found["pattern"],
            structure=structure,
        )

    def _apply_ck_confluence(
        self, signal: Signal, ctx: MarketContext, df: pd.DataFrame, atr_val: float, params: dict
    ) -> Signal:
        """Layer CK1/CK2/CK3 confluence (pp.176-203) onto whichever signal
        fired above, SNRC or reversal — 'Any setup + CK1/CK2/CK3'. Additive
        only: it can raise `confidence` (still capped at the ceiling the
        signal was already built with) and annotate `reason`, never reject a
        signal the setup-specific pipeline already accepted."""
        last_i = len(df) - 1
        window_start = max(0, last_i + 1 - int(params["sr_lookback_bars"]))
        sr_slice = df.iloc[window_start : last_i + 1].reset_index(drop=True)
        lookback = int(params["swing_lookback"])
        if len(sr_slice) <= 2 * lookback + 1:
            return signal
        is_high, is_low = _swing_flags(sr_slice, lookback)
        raw_points = _swing_points_list(sr_slice, is_high, is_low)
        lines_touched = _count_ck_confluence(raw_points, sr_slice, atr_val, params)
        if lines_touched == 0:
            return signal

        ck_tag = "CK1"
        if lines_touched >= 2:
            ck_tag = "CK3" if _htf_has_solid_engulf(ctx, signal.direction, params) else "CK2"
        cap = _confidence_cap_for(signal.reason, params)
        boosted = min(signal.confidence + 0.05 * lines_touched, cap)
        return Signal(
            direction=signal.direction,
            sl_points=signal.sl_points,
            tp_points=signal.tp_points,
            confidence=float(boosted),
            reason=f"{signal.reason} {ck_tag}_confluence={lines_touched}",
            zone=signal.zone,
            pattern=signal.pattern,
            structure=signal.structure,
        )
