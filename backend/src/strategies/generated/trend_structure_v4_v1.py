"""Trend-structure v4: v2's fresh-swing trigger and fixed TP:SL, with v3's
zone-anchored SL swapped in for the naive opposite-kind swing pivot.

`trend_structure_v3` tried the full `rbr_dbd_zones_scalp_xauusd_v1.py` merge —
zone-anchored SL *and* a structural TP (nearest unmitigated old high/low)
instead of the fixed `TP_RR=2.2`. A same-day XAUUSD 2026-04:2026-07 backtest
comparison showed that regressed badly against v2 (101 trades, PF 0.95,
avg_r -0.015, ending balance *below* the 10k start) versus v2's 561 trades,
PF 2.60, avg_r +0.16. The structural-TP change is what did the damage: the
nearest unmitigated swing is very often much closer than a 2.2x SL multiple
would reach, so v3's real payoff per trade collapsed even though its entries
(the part actually being complained about) were sounder.

v4 isolates the part of v3 that was actually the complaint: `trend_structure`
v1/v2 anchor SL to whatever opposite-kind zigzag pivot happens to sit between
the two confirming swings, which is frequently a *stale* extreme from well
before the current leg (see the trade that prompted this: v1/v2 anchored SL
to a swing low near the bottom of an old, already-mitigated base, when the
base that actually launched the current leg — an RBR/DBD/RBD/DBR — sat much
closer to entry, further reducing risk per trade for the same stop validity).
v4 keeps that zone-anchored SL (identical `_detect_zones` geometry, same
"base must have formed at/after the last opposite-kind swing" rule, no
non-zone SL fallback — skip the trade rather than guess) but reverts TP to
v1/v2's fixed `TP_RR=2.2`, since that's the part the backtest shows earning
its keep.

Net effect versus v2: same entries, a *tighter, more honestly-placed* SL
(so the same stop-loss cash risk buys a larger position / more margin before
invalidation — see reason string for the concrete zone), same TP multiple.
Versus v3: same SL improvement without the TP regression.

No live/backtest track record yet beyond the one comparison above — validate
further with `/backtest/run` before activating.

Sandbox-safe: only `numpy`/`pandas` — no I/O, no broker access.
"""

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

MIN_HISTORY = 60  # room for ATR(14) warmup plus at least 5 alternating swing pivots
# Must clear every symbol's configs/symbols/<sym>.yaml min_rr (highest: XAGUSD
# at 1.8) with headroom — see breakout_v1.py for the same constraint.
TP_RR = 2.2


def _true_range_values(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> np.ndarray:
    tr = highs - lows
    if len(tr) > 1:
        gap_high = np.abs(highs[1:] - closes[:-1])
        gap_low = np.abs(lows[1:] - closes[:-1])
        tr[1:] = np.maximum(tr[1:], np.maximum(gap_high, gap_low))
    return tr


def _atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int) -> pd.Series:
    tr = pd.Series(_true_range_values(highs, lows, closes))
    return tr.rolling(period, min_periods=period).mean()


def _swing_flags(highs: np.ndarray, lows: np.ndarray, wing: int) -> tuple[np.ndarray, np.ndarray]:
    n = len(highs)
    is_high = np.zeros(n, dtype=bool)
    is_low = np.zeros(n, dtype=bool)
    window = 2 * wing + 1
    if n >= window:
        window_max = np.lib.stride_tricks.sliding_window_view(highs, window).max(axis=1)
        window_min = np.lib.stride_tricks.sliding_window_view(lows, window).min(axis=1)
        is_high[wing : n - wing] = highs[wing : n - wing] == window_max
        is_low[wing : n - wing] = lows[wing : n - wing] == window_min
    return is_high, is_low


def _push_swing(swings: list[tuple[int, float, str]], index: int, price: float, kind: str) -> None:
    if swings and swings[-1][2] == kind:
        _, prev_price, _ = swings[-1]
        if (kind == "high" and price > prev_price) or (kind == "low" and price < prev_price):
            swings[-1] = (index, price, kind)
        return
    swings.append((index, price, kind))


def _zigzag_swings(highs: np.ndarray, lows: np.ndarray, wing: int) -> list[tuple[int, float, str]]:
    is_high, is_low = _swing_flags(highs, lows, wing)
    swings: list[tuple[int, float, str]] = []
    for i in np.flatnonzero(is_high | is_low):
        index = int(i)
        if is_high[index]:
            _push_swing(swings, index, float(highs[index]), "high")
        if is_low[index]:
            _push_swing(swings, index, float(lows[index]), "low")
    return swings


def _detect_zones(
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    atr: pd.Series,
    params: dict,
) -> list[dict]:
    """RBR/DBD/RBD/DBR zones over the window, each with an optional flipped
    counterpart appended when a strong candle invalidates it. Identical
    detector to `trend_structure_v3_v1.py` / `rbr_dbd_zones_scalp_xauusd_v1.py`.

    Zone dict fields: pattern, kind, price_high, price_low, base_start,
    conf_idx, leg_out_end, retest_idx, broken_idx, flipped (bool).
    """
    n = len(closes)
    valid_atr = atr.dropna()
    if valid_atr.empty:
        return []
    atr_filled = atr.fillna(valid_atr.iloc[0]).to_numpy()

    base_mult = params["base_body_atr_mult"]
    leg_mult = params["leg_travel_atr_mult"]
    max_base = int(params["max_base_candles"])

    cls = np.where(
        np.abs(closes - opens) <= base_mult * atr_filled,
        0,
        np.where(closes >= opens, 1, -1),
    )

    change = np.flatnonzero(cls[1:] != cls[:-1]) + 1
    starts = np.concatenate(([0], change))
    ends = np.append(change - 1, n - 1)
    runs: list[list[int]] = [
        [int(cls[s]), int(s), int(e)] for s, e in zip(starts, ends, strict=True)
    ]

    def is_leg(run: list[int]) -> bool:
        cls_, start, end = run
        return cls_ != 0 and abs(closes[end] - opens[start]) >= leg_mult * atr_filled[end]

    merged = True
    while merged:
        merged = False
        for k in range(len(runs) - 2):
            d1, pause, d2 = runs[k], runs[k + 1], runs[k + 2]
            if d1[0] == 0 or pause[0] != 0 or d2[0] != d1[0]:
                continue
            if pause[2] - pause[1] + 1 > max_base:
                continue
            if is_leg(d1) and is_leg(d2):
                continue
            runs[k : k + 3] = [[d1[0], d1[1], d2[2]]]
            merged = True
            break

    legs = [r for r in runs if is_leg(r)]

    def _scan_retest_break(demand: bool, scan_start: int, price_low: float, price_high: float):
        if demand:
            touched = lows[scan_start:] <= price_high
            broke = closes[scan_start:] < price_low
        else:
            touched = highs[scan_start:] >= price_low
            broke = closes[scan_start:] > price_high
        touch_hits = np.flatnonzero(touched)
        break_hits = np.flatnonzero(broke)
        broken_idx = int(break_hits[0]) + scan_start if len(break_hits) else None
        retest_idx = None
        if len(touch_hits):
            first_touch = int(touch_hits[0]) + scan_start
            if broken_idx is None or first_touch <= broken_idx:
                retest_idx = first_touch
        return retest_idx, broken_idx

    zones: list[dict] = []
    for k in range(len(legs) - 1):
        leg_in, leg_out = legs[k], legs[k + 1]
        base_start = leg_in[2] + 1
        base_end = leg_out[1] - 1
        base_count = base_end - base_start + 1
        if base_count < 1 or base_count > max_base:
            continue

        price_high = float(highs[base_start : base_end + 1].max())
        price_low = float(lows[base_start : base_end + 1].min())

        leg_out_up = leg_out[0] == 1
        conf_idx = None
        for j in range(leg_out[1], leg_out[2] + 1):
            cleared = (closes[j] > price_high) if leg_out_up else (closes[j] < price_low)
            if cleared:
                conf_idx = j
                break
        if conf_idx is None:
            continue

        if leg_in[0] == 1:
            pattern = "RBR" if leg_out_up else "RBD"
        else:
            pattern = "DBR" if leg_out_up else "DBD"
        demand = leg_out_up

        scan_start = leg_out[2] + 1
        retest_idx, broken_idx = _scan_retest_break(demand, scan_start, price_low, price_high)

        zones.append(
            {
                "pattern": pattern,
                "kind": ZoneKind.DEMAND if demand else ZoneKind.SUPPLY,
                "price_high": price_high,
                "price_low": price_low,
                "base_start": base_start,
                "conf_idx": conf_idx,
                "leg_out_end": leg_out[2],
                "retest_idx": retest_idx,
                "broken_idx": broken_idx,
                "flipped": False,
            }
        )

        if broken_idx is not None:
            break_body = abs(closes[broken_idx] - opens[broken_idx])
            if break_body >= params["flip_break_body_atr_mult"] * atr_filled[broken_idx]:
                flip_demand = not demand
                flip_scan_start = broken_idx + 1
                if flip_scan_start < n:
                    f_retest, f_broken = _scan_retest_break(
                        flip_demand, flip_scan_start, price_low, price_high
                    )
                    zones.append(
                        {
                            "pattern": f"{pattern}_flip",
                            "kind": ZoneKind.DEMAND if flip_demand else ZoneKind.SUPPLY,
                            "price_high": price_high,
                            "price_low": price_low,
                            "base_start": base_start,
                            "conf_idx": broken_idx,
                            "leg_out_end": broken_idx,
                            "retest_idx": f_retest,
                            "broken_idx": f_broken,
                            "flipped": True,
                        }
                    )
    return zones


class TrendStructureV4:
    def __init__(self) -> None:
        self.spec = StrategySpec(
            name="trend_structure_v4",
            version=4,
            symbols=("XAUUSD", "XAGUSD", "BTCUSD"),
            entry_timeframe="M5",
            confirmation_timeframes=(),
            params={
                "pivot_wing": 3,
                "atr_period": 14,
                "min_swing_atr_mult": 0.5,
                "zone_lookback_bars": 200,
                "base_body_atr_mult": 0.5,
                "leg_travel_atr_mult": 0.7,
                "max_base_candles": 3,
                "max_base_atr_mult": 2.0,
                "sl_base_mult": 1.0,
                "min_sl_atr_mult": 0.3,
                "flip_break_body_atr_mult": 1.2,
                "tp_rr": TP_RR,
            },
        )

    def evaluate(self, ctx: MarketContext) -> Signal | None:
        params = self.spec.params
        df = ctx.candles.get(self.spec.entry_timeframe)
        wing = int(params["pivot_wing"])
        atr_period = int(params["atr_period"])
        lookback = int(params["zone_lookback_bars"])
        tp_rr = params["tp_rr"]
        min_bars = max(lookback, atr_period * 2 + 10, wing * 2 + 30, MIN_HISTORY)
        if df is None or len(df) < min_bars:
            return None

        opens = df["open"].to_numpy()[-lookback:]
        highs = df["high"].to_numpy()[-lookback:]
        lows = df["low"].to_numpy()[-lookback:]
        closes = df["close"].to_numpy()[-lookback:]

        swings = _zigzag_swings(highs, lows, wing)
        if len(swings) < 5:
            return None

        # A fractal at index i only confirms once `wing` bars have closed to
        # its right — only act on the bar that confirmation lands on.
        last_index, last_price, last_kind = swings[-1]
        if last_index != len(closes) - 1 - wing:
            return None

        prior_index, prior_price, prior_kind = swings[-3]
        if prior_kind != last_kind:
            return None
        leg_start_idx, sl_ref_price, sl_ref_kind = swings[-2]
        _, context_reference, context_kind = swings[-4]
        if context_kind != sl_ref_kind:
            return None

        if last_kind == "high" and last_price > prior_price:
            # Only a HH inside an established uptrend: the low right before
            # it (swings[-2]) must itself be a higher low than the one
            # before that (swings[-4]) — both legs of the zigzag agree.
            if sl_ref_price <= context_reference:
                return None
            direction, label = Direction.BUY, StructureLabel.HH
        elif last_kind == "low" and last_price < prior_price:
            # Symmetric: the high right before this LL must be a lower high.
            if sl_ref_price >= context_reference:
                return None
            direction, label = Direction.SELL, StructureLabel.LL
        else:
            return None

        atr = _atr(highs, lows, closes, atr_period)
        atr_val = atr.iloc[-1]
        if pd.isna(atr_val) or atr_val <= 0:
            return None
        atr_val = float(atr_val)
        if abs(last_price - prior_price) < atr_val * params["min_swing_atr_mult"]:
            return None  # fresh extreme barely beat the prior one — noise, not a new leg

        # SL anchor: the RBR/DBD/RBD/DBR base that actually launched this
        # fresh leg — i.e. formed at/after the last opposite-kind swing
        # (`leg_start_idx`), not some unrelated older zone. This is the one
        # change from v1/v2: they anchor SL to `sl_ref_price` (the raw
        # opposite-kind swing pivot) unconditionally, which can sit far below
        # (or above) the base that actually launched the current leg if an
        # older, already-mitigated swing happens to be more extreme.
        zones = _detect_zones(opens, highs, lows, closes, atr, params)
        demand = direction == Direction.BUY
        close = float(closes[-1])
        candidate = None
        for z in reversed(zones):
            if z["broken_idx"] is not None:
                continue
            if (z["kind"] == ZoneKind.DEMAND) != demand:
                continue
            if z["base_start"] < leg_start_idx:
                continue  # not the base this fresh leg launched from
            proximal = z["price_high"] if demand else z["price_low"]
            dist = (close - proximal) if demand else (proximal - close)
            if dist < 0:
                continue  # price hasn't actually cleared this zone yet
            if (z["price_high"] - z["price_low"]) > params["max_base_atr_mult"] * atr_val:
                continue  # sloppy/wide base — lower-quality S&D structure
            candidate = z
            break
        if candidate is None:
            return None  # no RBR/DBD/RBD/DBR base under this leg — no valid SL anchor

        base_height = candidate["price_high"] - candidate["price_low"]
        sl_points = max(base_height * params["sl_base_mult"], atr_val * params["min_sl_atr_mult"])
        if sl_points <= 0:
            return None
        entry_price = close
        tp_points = sl_points * tp_rr

        window_times = df["time"].iloc[-lookback:].reset_index(drop=True)
        zone = PriceZone(
            kind=candidate["kind"],
            price_low=candidate["price_low"],
            price_high=candidate["price_high"],
            time_start=window_times.iloc[candidate["base_start"]],
            time_end=window_times.iloc[len(closes) - 1],
        )
        structure: tuple[StructurePoint, ...] = (
            StructurePoint(time=window_times.iloc[last_index], price=last_price, label=label),
        )

        reason = (
            f"{label.value} at {last_price:.5f} (bar {last_index}) beat prior swing "
            f"{prior_price:.5f} (bar {prior_index}) by >= {params['min_swing_atr_mult']}xATR, "
            f"aligned with prior {'HL' if label is StructureLabel.HH else 'LH'}; "
            f"sl_zone={candidate['pattern']}"
            f"[{candidate['price_low']:.5f},{candidate['price_high']:.5f}] "
            f"sl=base_height({base_height:.5f}) tp={tp_rr}xRR "
            f"lines: entry={entry_price:.5f} sl_pts={sl_points:.5f} tp_pts={tp_points:.5f}"
        )
        return Signal(
            direction=direction,
            sl_points=float(sl_points),
            tp_points=float(tp_points),
            confidence=0.6,
            reason=reason,
            zone=zone,
            pattern=candidate["pattern"],
            structure=structure,
        )
