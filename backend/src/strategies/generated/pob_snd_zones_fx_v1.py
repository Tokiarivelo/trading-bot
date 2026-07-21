"""PoB S&D zone-retest strategy for Volatility 75 Index.

Trades the "only 4 types of Entry Point" from the Property of Bystra notes:
RBR / DBR demand zones (buy the retest) and DBD / RBD supply zones (sell the
retest). Zone detection is a faithful port of the frontend `snd` chart
indicator (`frontend/src/features/chart/indicators.ts`, `sndZones()`), so
what this bot trades is exactly what the chart overlay draws:

  - every candle is base-class (body <= base_body_atr_mult * ATR, any color)
    or a directional momentum bar; consecutive same-class bars form runs;
  - weak same-direction runs split by a short pause merge into one run;
  - a run is a *leg* when its net travel >= leg_travel_atr_mult * ATR;
  - a zone is each adjacent pair of legs with 1..max_base_candles candles
    between them, confirmed by the first leg-out close clearing the base
    band; the band is those between-candles' high/low;
  - the first candle back in the band after the leg-out is the retest; a
    close through the far side breaks (voids) the zone.

Entry only on a fresh retest (within retest_max_age_bars of the last bar) of
an unbroken zone, with a confirming candle on the entry bar (engulfing >
pin bar > body candle, per the PDF's confirmation doctrine) plus at least
min_confirmations higher-timeframe engulf/body confirmations ("switch to a
higher TF, look for engulf" — SNRC formula). Stop goes beyond the zone's far
edge; target is a fixed reward:risk multiple.

FX flavor (XAUUSD/XAGUSD): confirmation runs on H1/H4 — the deep-history
frames for metals — and, per the XAUUSD 2026-06:2026-07 tuning matrix,
trades continuation zones only, aligned with the H1 EMA(50) trend, with
wider stops (gold's wicks) and a higher reward:risk. Best backtest on that
window is PF 0.95 — near break-even, NOT yet profitable; treat this as a
starting point for further refinement, not a finished edge.
"""

import pandas as pd

from src.strategies.domain.models import (
    Direction,
    MarketContext,
    PriceZone,
    Signal,
    StrategySpec,
    ZoneKind,
)

# Point size per traded symbol (configs/symbols/*.yaml) — converts
# ctx.spread_points (raw broker points) into a price distance so
# reward_risk_ratio below is applied to (sl + spread), not sl alone — the
# same floor SpreadGate enforces at the broker gate (tp >= min_rr * (sl + spread)).
# This strategy trades both XAUUSD and XAGUSD, whose point sizes differ.
POINT_VALUES = {"XAUUSD": 0.01, "XAGUSD": 0.001}


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
    rng = df["high"].iloc[i] - df["low"].iloc[i]
    if rng <= 0:
        return False, ""
    if abs(df["close"].iloc[i] - df["open"].iloc[i]) / rng < min_body_ratio:
        return False, ""
    return True, ("up" if df["close"].iloc[i] > df["open"].iloc[i] else "down")


def _is_pin_bar(
    df: pd.DataFrame, i: int, max_body_ratio: float, min_wick_body_mult: float
) -> tuple[bool, str]:
    rng = df["high"].iloc[i] - df["low"].iloc[i]
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
    """Confirming candlestick pattern at bar `i`, strongest match first
    (engulfing > pin bar > plain body candle) — same ladder as the existing
    vix75 strategy so both bots read candles identically."""
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


def _detect_zones(df: pd.DataFrame, atr: pd.Series, params: dict) -> list[dict]:
    """RBR/DBD/RBD/DBR zones over `df` — port of the frontend `sndZones()`.

    Returns chronological zone dicts:
      pattern ("RBR"|"DBD"|"RBD"|"DBR"), kind (ZoneKind), price_high,
      price_low, base_start / conf_idx / leg_out_end (integer positions in
      `df`), retest_idx (first bar back in the band after the leg-out, or
      None), broken_idx (first bar CLOSING through the far side, or None).
    """
    n = len(df)
    valid_atr = atr.dropna()
    if valid_atr.empty:
        return []
    # Pad the ATR warmup bars with the first available value so early
    # candles still classify (same padding the chart indicator does).
    atr_filled = atr.fillna(valid_atr.iloc[0]).to_numpy()

    opens = df["open"].to_numpy()
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    closes = df["close"].to_numpy()

    base_mult = params["base_body_atr_mult"]
    leg_mult = params["leg_travel_atr_mult"]
    max_base = int(params["max_base_candles"])

    # 0 = base (small body, either color); +1/-1 = directional momentum bar.
    def classify(i: int) -> int:
        if abs(closes[i] - opens[i]) <= base_mult * atr_filled[i]:
            return 0
        return 1 if closes[i] >= opens[i] else -1

    # Runs of consecutive same-class candles, as mutable [cls, start, end].
    runs: list[list[int]] = []
    for i in range(n):
        cls = classify(i)
        if runs and runs[-1][0] == cls:
            runs[-1][2] = i
        else:
            runs.append([cls, i, i])

    def is_leg(run: list[int]) -> bool:
        cls, start, end = run
        return cls != 0 and abs(closes[end] - opens[start]) >= leg_mult * atr_filled[end]

    # Weak same-direction runs split by a short base run merge into one run
    # (a rally printing 0.7-ATR candles around a doji is one leg, not two
    # non-legs). Runs that BOTH already qualify as legs stay separate: the
    # pause between them is a stacked-zone base, not leg interior.
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
        # Confirmation: first leg-out candle whose close actually departs the
        # base band — a momentum run that never clears the base is still
        # consolidation, not a zone.
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

        # Retest/break scan starts after the whole leg-out run — its own
        # early candles' wicks still overlap the base and aren't a return.
        retest_idx = None
        broken_idx = None
        for j in range(leg_out[2] + 1, n):
            touched = (lows[j] <= price_high) if demand else (highs[j] >= price_low)
            if retest_idx is None and touched:
                retest_idx = j
            broke = (closes[j] < price_low) if demand else (closes[j] > price_high)
            if broke:
                broken_idx = j
                break

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
            }
        )
    return zones


class PobSndZonesFx:
    def __init__(self) -> None:
        self.spec = StrategySpec(
            name="pob_snd_zones_fx",
            version=1,
            symbols=("XAUUSD", "XAGUSD"),
            entry_timeframe="M5",
            confirmation_timeframes=("H1", "H4"),
            params={
                # Zone detection — MUST stay in sync with the frontend `snd`
                # indicator's DEFAULT_SND_PARAMS + dock period so the chart
                # rectangles match what the bot trades.
                "atr_period": 14,
                "base_body_atr_mult": 0.5,
                "leg_travel_atr_mult": 1.0,
                "max_base_candles": 3,
                "zone_lookback_bars": 200,
                # Entry gating.
                "retest_max_age_bars": 2,
                "entry_max_dist_atr_mult": 3.0,
                "engulf_min_body_ratio": 0.6,
                "pin_bar_max_body_ratio": 0.35,
                "pin_bar_min_wick_mult": 2.0,
                "mtf_min_body_ratio": 0.4,
                "confirm_lookback": 6,
                "min_confirmations": 1,
                # Refinement toggles (v2): demand the strongest entry
                # confirmation only, and/or trade only the continuation
                # zones (RBR/DBD) — reversal-turn zones (RBD/DBR) are the
                # weaker SNRC2 tier.
                "require_engulfing_entry": False,
                "continuation_only": True,
                # 0 disables; otherwise only trade zones aligned with the
                # first confirmation TF's EMA trend (close vs EMA(n)).
                "htf_trend_ema_period": 50,
                # Require the retest bar to CLOSE back outside the band in
                # the trade direction — proven rejection, not a hope-entry.
                "require_rejection_close": False,
                # Risk shape.
                "sl_zone_buffer_atr_mult": 1.0,
                "sl_atr_mult": 1.5,
                "reward_risk_ratio": 2.5,
                "min_confidence": 0.5,
            },
        )

    def evaluate(self, ctx: MarketContext) -> Signal | None:
        params = self.spec.params
        df = ctx.candles.get(self.spec.entry_timeframe)
        min_bars = int(params["atr_period"]) * 2 + 10
        if df is None or len(df) < min_bars:
            return None

        window = df.iloc[-int(params["zone_lookback_bars"]) :].reset_index(drop=True)
        atr = _atr(window, int(params["atr_period"]))
        atr_val = atr.iloc[-1]
        if pd.isna(atr_val) or atr_val <= 0:
            return None
        atr_val = float(atr_val)

        zones = _detect_zones(window, atr, params)
        last_i = len(window) - 1

        # Most recent live zone whose FIRST retest is happening right now
        # (within retest_max_age_bars of the last bar). A broken zone, a
        # zone never retested, or a stale retest all pass — no trade.
        candidate = None
        for z in reversed(zones):
            if params.get("continuation_only") and z["pattern"] not in ("RBR", "DBD"):
                continue
            if z["broken_idx"] is not None or z["retest_idx"] is None:
                continue
            if last_i - z["retest_idx"] > int(params["retest_max_age_bars"]):
                continue
            candidate = z
            break
        if candidate is None:
            return None

        demand = candidate["kind"] == ZoneKind.DEMAND
        direction = Direction.BUY if demand else Direction.SELL

        # Confirmation candle on the entry bar, in the zone's direction —
        # "the best confirmation is in the engulfing candle body".
        pattern, side = _classify_pattern(window, last_i, params)
        if pattern is None or side != ("up" if demand else "down"):
            return None
        if params.get("require_engulfing_entry") and "engulfing" not in pattern:
            return None

        close = float(window["close"].iloc[last_i])
        proximal = candidate["price_high"] if demand else candidate["price_low"]
        # Negative when the close is inside the band; the gate only rejects
        # closes that already ran too far past the zone to anchor a stop.
        dist = (close - proximal) if demand else (proximal - close)
        if dist > params["entry_max_dist_atr_mult"] * atr_val:
            return None

        if params.get("require_rejection_close") and dist <= 0:
            return None

        ema_period = int(params.get("htf_trend_ema_period", 0))
        if ema_period > 0:
            htf = ctx.candles.get(self.spec.confirmation_timeframes[0])
            if htf is None or len(htf) < ema_period:
                return None
            ema_last = htf["close"].ewm(span=ema_period, adjust=False).mean().iloc[-1]
            htf_close = htf["close"].iloc[-1]
            aligned = (htf_close > ema_last) if demand else (htf_close < ema_last)
            if not aligned:
                return None

        confirmations = sum(
            1
            for tf in self.spec.confirmation_timeframes
            if _mtf_confirms(ctx, tf, direction, params)
        )
        if confirmations < int(params["min_confirmations"]):
            return None

        # RBR/DBD are continuation entries (SNRC1); RBD/DBR mark the turn
        # (SNRC2) and start slightly lower, same weighting the existing
        # vix75 strategy uses.
        continuation = candidate["pattern"] in ("RBR", "DBD")
        confidence = (0.5 if continuation else 0.45) + 0.1 * confirmations
        if "engulfing" in pattern:
            confidence += 0.05
        confidence = min(confidence, 0.9)
        if confidence < params["min_confidence"]:
            return None

        if demand:
            structural_level = candidate["price_low"] - atr_val * params["sl_zone_buffer_atr_mult"]
            structural_dist = close - structural_level
        else:
            structural_level = candidate["price_high"] + atr_val * params["sl_zone_buffer_atr_mult"]
            structural_dist = structural_level - close
        sl_points = max(structural_dist, atr_val * params["sl_atr_mult"])
        spread_price = float(ctx.spread_points) * POINT_VALUES.get(ctx.symbol, 0.01)
        tp_points = (sl_points + spread_price) * params["reward_risk_ratio"]
        if demand:
            sl_price, tp_price = close - sl_points, close + tp_points
        else:
            sl_price, tp_price = close + sl_points, close - tp_points

        zone = PriceZone(
            kind=candidate["kind"],
            price_low=candidate["price_low"],
            price_high=candidate["price_high"],
            time_start=window["time"].iloc[candidate["base_start"]],
            time_end=window["time"].iloc[last_i],
        )
        n_confirm_tfs = len(self.spec.confirmation_timeframes)
        retest_age = last_i - candidate["retest_idx"]
        reason = (
            f"{candidate['pattern']}-retest pattern={pattern} "
            f"zone_rect=[{candidate['price_low']:.2f},{candidate['price_high']:.2f}] "
            f"retest_age={retest_age} mtf_confirms={confirmations}/{n_confirm_tfs} "
            f"dist_atr={dist / atr_val:.2f} zone_unbroken "
            f"lines: entry={close:.2f} sl={sl_price:.2f} tp={tp_price:.2f}"
        )
        return Signal(
            direction=direction,
            sl_points=float(sl_points),
            tp_points=float(tp_points),
            confidence=float(confidence),
            reason=reason,
            zone=zone,
            pattern=pattern,
        )
