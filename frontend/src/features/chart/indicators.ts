/**
 * Pure indicator math over `Candle[]`, computed client-side so the backend
 * stays limited to emitting the structured `IndicatorSpec` (type/period/
 * params) extracted from a strategy's source PDF — see `ChartPanel.tsx`,
 * which feeds these into `chart.addSeries(LineSeries/HistogramSeries, ...)`.
 *
 * EMA matches this project's existing backend convention
 * (`backend/src/engine/application/mtf_confirm.py`: `ewm(span, adjust=False)`).
 * RSI uses standard Wilder smoothing since no backend RSI exists to match.
 */

import type { UTCTimestamp } from "lightweight-charts";
import type { Candle } from "@/shared/api/client";

export interface LinePoint {
  time: UTCTimestamp;
  value: number;
}

function toPoint(candle: Candle, value: number): LinePoint {
  return { time: candle.time as UTCTimestamp, value };
}

export function ema(candles: Candle[], period: number): LinePoint[] {
  if (candles.length === 0) return [];
  const alpha = 2 / (period + 1);
  const points: LinePoint[] = [];
  let prev = candles[0].close;
  points.push(toPoint(candles[0], prev));
  for (let i = 1; i < candles.length; i++) {
    prev = candles[i].close * alpha + prev * (1 - alpha);
    points.push(toPoint(candles[i], prev));
  }
  return points;
}

export function sma(candles: Candle[], period: number): LinePoint[] {
  const points: LinePoint[] = [];
  let sum = 0;
  for (let i = 0; i < candles.length; i++) {
    sum += candles[i].close;
    if (i >= period) sum -= candles[i - period].close;
    if (i >= period - 1) points.push(toPoint(candles[i], sum / period));
  }
  return points;
}

export function rsi(candles: Candle[], period: number): LinePoint[] {
  if (candles.length < period + 1) return [];
  const points: LinePoint[] = [];
  let avgGain = 0;
  let avgLoss = 0;
  for (let i = 1; i <= period; i++) {
    const change = candles[i].close - candles[i - 1].close;
    avgGain += Math.max(change, 0);
    avgLoss += Math.max(-change, 0);
  }
  avgGain /= period;
  avgLoss /= period;
  const rsiAt = (gain: number, loss: number) => (loss === 0 ? 100 : 100 - 100 / (1 + gain / loss));
  points.push(toPoint(candles[period], rsiAt(avgGain, avgLoss)));

  for (let i = period + 1; i < candles.length; i++) {
    const change = candles[i].close - candles[i - 1].close;
    const gain = Math.max(change, 0);
    const loss = Math.max(-change, 0);
    avgGain = (avgGain * (period - 1) + gain) / period;
    avgLoss = (avgLoss * (period - 1) + loss) / period;
    points.push(toPoint(candles[i], rsiAt(avgGain, avgLoss)));
  }
  return points;
}

function emaSeries(closes: number[], period: number): number[] {
  const alpha = 2 / (period + 1);
  const out: number[] = [closes[0]];
  for (let i = 1; i < closes.length; i++) {
    out.push(closes[i] * alpha + out[i - 1] * (1 - alpha));
  }
  return out;
}

export interface MacdResult {
  macdLine: LinePoint[];
  signalLine: LinePoint[];
  histogram: LinePoint[];
}

export function macd(
  candles: Candle[],
  fast: number,
  slow: number,
  signal: number,
): MacdResult {
  if (candles.length === 0) {
    return { macdLine: [], signalLine: [], histogram: [] };
  }
  const closes = candles.map((c) => c.close);
  const fastEma = emaSeries(closes, fast);
  const slowEma = emaSeries(closes, slow);
  const macdValues = fastEma.map((v, i) => v - slowEma[i]);
  const signalValues = emaSeries(macdValues, signal);

  const macdLine = candles.map((c, i) => toPoint(c, macdValues[i]));
  const signalLine = candles.map((c, i) => toPoint(c, signalValues[i]));
  const histogram = candles.map((c, i) => toPoint(c, macdValues[i] - signalValues[i]));
  return { macdLine, signalLine, histogram };
}

export interface BollingerResult {
  upper: LinePoint[];
  middle: LinePoint[];
  lower: LinePoint[];
}

export function bollinger(candles: Candle[], period: number, stdDev: number): BollingerResult {
  const upper: LinePoint[] = [];
  const middle: LinePoint[] = [];
  const lower: LinePoint[] = [];

  // Rolling sum/sum-of-squares instead of re-slicing + reducing the last
  // `period` candles at every bar — O(n) instead of O(n * period).
  let sum = 0;
  let sumSq = 0;
  for (let i = 0; i < candles.length; i++) {
    const close = candles[i].close;
    sum += close;
    sumSq += close * close;
    if (i >= period) {
      const dropped = candles[i - period].close;
      sum -= dropped;
      sumSq -= dropped * dropped;
    }
    if (i >= period - 1) {
      const mean = sum / period;
      const variance = Math.max(0, sumSq / period - mean * mean);
      const sd = Math.sqrt(variance);
      middle.push(toPoint(candles[i], mean));
      upper.push(toPoint(candles[i], mean + stdDev * sd));
      lower.push(toPoint(candles[i], mean - stdDev * sd));
    }
  }
  return { upper, middle, lower };
}

/**
 * Cumulative VWAP over whatever candles are currently loaded (not a true
 * session VWAP reset at a fixed calendar boundary — matches how every other
 * indicator here is recomputed over the full in-memory window on each
 * `recomputeIndicators()` pass, see ChartPanel.tsx). Uses `tick_volume` as
 * the volume proxy, same convention as the volume histogram series.
 */
export function vwap(candles: Candle[]): LinePoint[] {
  const points: LinePoint[] = [];
  let cumulativePv = 0;
  let cumulativeVolume = 0;
  for (const candle of candles) {
    const typicalPrice = (candle.high + candle.low + candle.close) / 3;
    cumulativePv += typicalPrice * candle.tick_volume;
    cumulativeVolume += candle.tick_volume;
    points.push(toPoint(candle, cumulativeVolume === 0 ? typicalPrice : cumulativePv / cumulativeVolume));
  }
  return points;
}

export type StructureLabel = "HH" | "HL" | "LH" | "LL";

export interface StructurePoint {
  time: UTCTimestamp;
  price: number;
  label: StructureLabel;
}

/**
 * Swing-structure classification (HH/HL/LH/LL) over the whole loaded candle
 * series. Mirrors the backend vix75 strategy's `_swing_flags`/
 * `_classify_structure` (see `backend/src/strategies/generated/"pob_price_
 * action_snd for vix75_v1.py"`), but computed once over every candle here
 * instead of a single trade's ~100-bar pre-entry window — a real swing that
 * doesn't happen to fall inside some trade's specific lookback was
 * previously just never labeled, even when it's the most obvious peak on
 * screen. `marginAtrMult` requires a swing to clear the prior one of the
 * same type by more than `marginAtrMult * ATR` before it reads as "higher" —
 * without it, two swings a fraction of a point apart (a retest, not a real
 * break) flip unpredictably between HH/LH or HL/LL.
 */
export function swingStructure(
  candles: Candle[],
  lookback: number,
  atrPeriod: number,
  marginAtrMult: number,
): StructurePoint[] {
  const n = candles.length;
  if (n < 2 * lookback + 1) return [];

  const atrPoints = atr(candles, atrPeriod);
  const atrByTime = new Map(atrPoints.map((p) => [p.time as number, p.value]));
  let currentAtr = atrPoints.length > 0 ? atrPoints[0].value : 0;

  const isHigh = new Array<boolean>(n).fill(false);
  const isLow = new Array<boolean>(n).fill(false);
  for (let i = lookback; i < n - lookback; i++) {
    let maxHigh = -Infinity;
    let minLow = Infinity;
    for (let j = i - lookback; j <= i + lookback; j++) {
      if (candles[j].high > maxHigh) maxHigh = candles[j].high;
      if (candles[j].low < minLow) minLow = candles[j].low;
    }
    if (candles[i].high === maxHigh) isHigh[i] = true;
    if (candles[i].low === minLow) isLow[i] = true;
  }

  const points: StructurePoint[] = [];
  let lastHigh: number | null = null;
  let lastLow: number | null = null;
  for (let i = 0; i < n; i++) {
    const time = candles[i].time as UTCTimestamp;
    const atrHere = atrByTime.get(time as number);
    if (atrHere !== undefined) currentAtr = atrHere;
    const margin = currentAtr * marginAtrMult;

    if (isHigh[i]) {
      if (lastHigh !== null) {
        const label: StructureLabel = candles[i].high > lastHigh + margin ? "HH" : "LH";
        points.push({ time, price: candles[i].high, label });
      }
      lastHigh = candles[i].high;
    } else if (isLow[i]) {
      if (lastLow !== null) {
        const label: StructureLabel = candles[i].low > lastLow + margin ? "HL" : "LL";
        points.push({ time, price: candles[i].low, label });
      }
      lastLow = candles[i].low;
    }
  }
  return points;
}

export type QuasimodoKind = "QML" | "QML_INV";

export interface QuasimodoZone {
  /** Candle that confirmed the pattern — the close that broke the neckline. */
  time: UTCTimestamp;
  /** QML level: the left shoulder's extreme, where the retest entry sits. */
  price: number;
  kind: QuasimodoKind;
  /** The swing between shoulder and head whose break confirms the pattern. */
  necklinePrice: number;
  /** Head extreme — the "maximum pain level"; a move past it voids the level. */
  headPrice: number;
  /** Head swing's candle — where the QM zone rectangle starts on the chart. */
  headTime: UTCTimestamp;
  /** First candle that tags the QML level again after confirmation, if any —
   * the retest entry (sell for QML, buy for QML_INV). Undefined when price
   * hasn't come back yet or ran past the head first. */
  retestTime?: UTCTimestamp;
}

/**
 * Quasimodo (QML) levels from `swingStructure()`'s output plus raw candles —
 * a chart annotation only, not wired into any strategy's trading decision.
 *
 * QML (bearish, sell): an uptrend prints a high (left shoulder), a low
 * (neckline), then a higher high (head). The pattern confirms when a candle
 * CLOSES back below the neckline — the break of structure that turns the
 * up-sequence into a lower low. The QML level is the left shoulder's high:
 * price typically rallies back into it before continuing down, and that
 * retest is the sell signal. QML_INV (bullish, buy) is the exact mirror —
 * low shoulder, high neckline, lower-low head, confirmation on a close above
 * the neckline, buy on the drop back into the shoulder's low.
 *
 * The head is the "maximum pain level" (MPL): price trading beyond it —
 * before the neckline breaks, or after the break but before the retest —
 * voids the level (pattern dropped / no retest marker). Both quick and late
 * retests count; there is no bar-count expiry. Confirmation and retest are
 * checked against actual candles, not just labeled swings, so a break that
 * never printed a new swing pivot still confirms.
 */
export function quasimodoLevels(points: StructurePoint[], candles: Candle[]): QuasimodoZone[] {
  const zones: QuasimodoZone[] = [];
  const indexByTime = new Map<number, number>();
  for (let i = 0; i < candles.length; i++) indexByTime.set(candles[i].time as number, i);

  for (let i = 0; i + 2 < points.length; i++) {
    const shoulder = points[i];
    const neckline = points[i + 1];
    const head = points[i + 2];
    const headIdx = indexByTime.get(head.time as number);
    if (headIdx === undefined) continue;

    // The label margin (marginAtrMult) can call a high "HH" that is only a
    // hair above the shoulder, so re-check the head strictly beats it.
    const bearish =
      shoulder.label === "HH" &&
      neckline.label === "HL" &&
      head.label === "HH" &&
      head.price > shoulder.price;
    const bullish =
      shoulder.label === "LL" &&
      neckline.label === "LH" &&
      head.label === "LL" &&
      head.price < shoulder.price;
    if (!bearish && !bullish) continue;

    // Confirmation: after the head, price must close through the neckline
    // (break of structure) before extending past the head again.
    let confIdx = -1;
    for (let j = headIdx + 1; j < candles.length; j++) {
      const c = candles[j];
      if (bearish ? c.high > head.price : c.low < head.price) break;
      if (bearish ? c.close < neckline.price : c.close > neckline.price) {
        confIdx = j;
        break;
      }
    }
    if (confIdx === -1) continue;

    // Retest: first candle back at the QML level after the break. A move
    // beyond the head (maximum pain level) first voids the level instead.
    let retestTime: UTCTimestamp | undefined;
    for (let j = confIdx + 1; j < candles.length; j++) {
      const c = candles[j];
      if (bearish ? c.high >= shoulder.price : c.low <= shoulder.price) {
        retestTime = c.time as UTCTimestamp;
        break;
      }
      if (bearish ? c.high > head.price : c.low < head.price) break;
    }

    zones.push({
      time: candles[confIdx].time as UTCTimestamp,
      price: shoulder.price,
      kind: bearish ? "QML" : "QML_INV",
      necklinePrice: neckline.price,
      headPrice: head.price,
      headTime: head.time,
      retestTime,
    });
  }
  return zones;
}

export type SndPattern = "RBR" | "DBD" | "RBD" | "DBR";
export type SndKind = "demand" | "supply";

export interface SndZone {
  /** First leg-out candle whose close clears the base band — the pattern is
   * complete and the zone exists from here. */
  time: UTCTimestamp;
  pattern: SndPattern;
  /** demand (buy) for RBR/DBR, supply (sell) for DBD/RBD. */
  kind: SndKind;
  /** Zone band = the base candles' extremes. */
  priceHigh: number;
  priceLow: number;
  /** First base candle — where the zone rectangle starts on the chart. */
  baseStartTime: UTCTimestamp;
  /** First candle back inside the zone after the leg-out, if any — the
   * retest entry (buy for demand, sell for supply). Undefined when price
   * hasn't returned yet or broke through the zone first. */
  retestTime?: UTCTimestamp;
  /** Candle that CLOSED through the far side of the zone, voiding it —
   * where the rectangle ends. Undefined while the zone is still live. */
  brokenTime?: UTCTimestamp;
}

export interface SndParams {
  /** A leg run's NET travel (open of its first candle to close of its last)
   * must be ≥ this × ATR to count as a rally/drop. */
  legTravelAtrMult: number;
  /** Base candle body must be ≤ this × ATR to count as consolidation. */
  baseBodyAtrMult: number;
}

/** Same PoB doctrine as the backend vix75 strategy's zone params, tuned so
 * an M5/M15 chart shows the obvious bases without flagging every doji. */
export const DEFAULT_SND_PARAMS: SndParams = {
  legTravelAtrMult: 1.0,
  baseBodyAtrMult: 0.5,
};

/**
 * PoB supply & demand zones — the "only 4 types of Entry Point" from the
 * Property of Bystra notes: RBR (Rally Base Rally) / DBR (Drop Base Rally)
 * demand zones to buy, DBD (Drop Base Drop) / RBD (Rally Base Drop) supply
 * zones to sell. A chart annotation like `quasimodoLevels`, not wired into
 * any strategy's trading decision.
 *
 * Detection finds the LEGS first, then reads the base as whatever sits
 * between them. Every candle is either base-class (body ≤ baseBodyAtrMult ×
 * ATR, any color) or a directional momentum bar; consecutive same-class
 * candles merge into runs, and a directional run is a *leg* when its net
 * travel reaches legTravelAtrMult × ATR — one 1.5-ATR candle and three
 * 0.6-ATR candles in a row are both rallies (the PDF draws the RBD/DBR arms
 * as multi-candle swings, not single bars). Two refinements, both from real
 * missed-zone reports:
 *   - weak same-direction runs split by a short pause merge into one run
 *     (a rally printing 0.7-ATR candles around a doji is one leg, not two
 *     non-legs) — but runs that BOTH already qualify stay separate, because
 *     the pause between them is a stacked-zone base, not leg interior;
 *   - the base between two legs is EVERY candle between them, including
 *     medium-bodied pullback bars that are neither base-class nor
 *     leg-strong (a lone 0.7-ATR red candle inside a rally used to break
 *     the pattern into up / junk / up and silently drop the zone).
 * A zone is then each adjacent pair of legs with 1..maxBaseCandles candles
 * between them, confirmed by the first leg-out candle whose close clears
 * the base extremes; the zone band is those between-candles' high/low. Leg
 * directions name the pattern: up-base-up = RBR, down-base-up = DBR,
 * down-base-down = DBD, up-base-down = RBD. Adjacent pairs share legs, so
 * stacked zones (rally → base → rally → base → rally) all detect.
 *
 * Lifecycle mirrors the QML indicator: after the leg-out run, the first
 * candle trading back into the band is the retest entry; a candle *closing*
 * beyond the far side of the band breaks the zone (rectangle ends there).
 * Unlike QML there is no separate confirmation step — the leg-out is itself
 * the confirmation.
 */
export function sndZones(
  candles: Candle[],
  maxBaseCandles: number,
  atrPeriod: number,
  params: SndParams = DEFAULT_SND_PARAMS,
): SndZone[] {
  const n = candles.length;
  const atrPoints = atr(candles, atrPeriod);
  if (atrPoints.length === 0) return [];
  // atrPoints[k] is the ATR at candles[atrPeriod + k]; pad the warmup bars
  // with the first available value so early candles still classify.
  const atrAt = new Array<number>(n).fill(atrPoints[0].value);
  for (let k = 0; k < atrPoints.length; k++) atrAt[atrPeriod + k] = atrPoints[k].value;

  // 0 = base (small body, either color); +1/-1 = directional momentum bar.
  const classify = (i: number): -1 | 0 | 1 => {
    if (Math.abs(candles[i].close - candles[i].open) <= params.baseBodyAtrMult * atrAt[i]) return 0;
    return candles[i].close >= candles[i].open ? 1 : -1;
  };

  interface Run {
    cls: -1 | 0 | 1;
    start: number;
    end: number;
  }
  const runs: Run[] = [];
  for (let i = 0; i < n; i++) {
    const cls = classify(i);
    const last = runs[runs.length - 1];
    if (last && last.cls === cls) last.end = i;
    else runs.push({ cls, start: i, end: i });
  }

  const isLeg = (r: Run): boolean =>
    r.cls !== 0 &&
    Math.abs(candles[r.end].close - candles[r.start].open) >= params.legTravelAtrMult * atrAt[r.end];

  // Weak same-direction runs split by a short base run merge into one run:
  // a rally printing 0.7-ATR candles around a doji is one leg, not two
  // non-legs (which made the whole move — and its zones — invisible). Runs
  // that BOTH already qualify as legs stay separate: the pause between them
  // is a stacked-zone base (rally → base → rally), not leg interior.
  let mergedSomething = true;
  while (mergedSomething) {
    mergedSomething = false;
    for (let k = 0; k + 2 < runs.length; k++) {
      const d1 = runs[k];
      const pause = runs[k + 1];
      const d2 = runs[k + 2];
      if (d1.cls === 0 || pause.cls !== 0 || d2.cls !== d1.cls) continue;
      if (pause.end - pause.start + 1 > maxBaseCandles) continue;
      if (isLeg(d1) && isLeg(d2)) continue;
      runs.splice(k, 3, { cls: d1.cls, start: d1.start, end: d2.end });
      mergedSomething = true;
      break;
    }
  }

  // The base between two adjacent legs is EVERY candle between them —
  // base-class candles, but also medium-bodied pullback bars that are
  // neither base-class nor leg-strong (a lone 0.7-ATR counter candle inside
  // the pause used to break the pattern apart and drop the zone).
  const legs = runs.filter(isLeg);

  const zones: SndZone[] = [];
  for (let k = 0; k + 1 < legs.length; k++) {
    const legIn = legs[k];
    const legOut = legs[k + 1];
    const baseStart = legIn.end + 1;
    const baseEnd = legOut.start - 1;
    const baseCount = baseEnd - baseStart + 1;
    if (baseCount < 1 || baseCount > maxBaseCandles) continue;

    let priceHigh = -Infinity;
    let priceLow = Infinity;
    for (let j = baseStart; j <= baseEnd; j++) {
      if (candles[j].high > priceHigh) priceHigh = candles[j].high;
      if (candles[j].low < priceLow) priceLow = candles[j].low;
    }

    const legOutUp = legOut.cls === 1;
    // Confirmation: the first leg-out candle whose close actually departs
    // the base band — a momentum run that never clears the base is still
    // consolidation, not a zone.
    let confIdx = -1;
    for (let j = legOut.start; j <= legOut.end; j++) {
      if (legOutUp ? candles[j].close > priceHigh : candles[j].close < priceLow) {
        confIdx = j;
        break;
      }
    }
    if (confIdx === -1) continue;

    const pattern: SndPattern =
      legIn.cls === 1 ? (legOutUp ? "RBR" : "RBD") : legOutUp ? "DBR" : "DBD";
    const kind: SndKind = legOutUp ? "demand" : "supply";

    // Retest/break scan starts after the whole leg-out run — its own early
    // candles' wicks still overlap the base and are not a return to it.
    let retestTime: UTCTimestamp | undefined;
    let brokenTime: UTCTimestamp | undefined;
    for (let j = legOut.end + 1; j < n; j++) {
      const c = candles[j];
      if (retestTime === undefined && (kind === "demand" ? c.low <= priceHigh : c.high >= priceLow)) {
        retestTime = c.time as UTCTimestamp;
      }
      if (kind === "demand" ? c.close < priceLow : c.close > priceHigh) {
        brokenTime = c.time as UTCTimestamp;
        break;
      }
    }

    zones.push({
      time: candles[confIdx].time as UTCTimestamp,
      pattern,
      kind,
      priceHigh,
      priceLow,
      baseStartTime: candles[baseStart].time as UTCTimestamp,
      retestTime,
      brokenTime,
    });
  }
  return zones;
}

export type PatternLabel =
  | "bullish_engulfing"
  | "bearish_engulfing"
  | "bullish_pin_bar"
  | "bearish_pin_bar";

export interface PatternPoint {
  time: UTCTimestamp;
  price: number;
  label: PatternLabel;
}

function isBullishEngulfing(candles: Candle[], i: number): boolean {
  if (i < 1) return false;
  const prevO = candles[i - 1].open;
  const prevC = candles[i - 1].close;
  const o = candles[i].open;
  const c = candles[i].close;
  if (!(prevC < prevO && c > o)) return false;
  return o <= prevC && c >= prevO;
}

function isBearishEngulfing(candles: Candle[], i: number): boolean {
  if (i < 1) return false;
  const prevO = candles[i - 1].open;
  const prevC = candles[i - 1].close;
  const o = candles[i].open;
  const c = candles[i].close;
  if (!(prevC > prevO && c < o)) return false;
  return o >= prevC && c <= prevO;
}

function isPinBar(
  candles: Candle[],
  i: number,
  maxBodyRatio: number,
  minWickBodyMult: number,
): "up" | "down" | null {
  const candle = candles[i];
  const range = candle.high - candle.low;
  if (range <= 0) return null;
  const body = Math.abs(candle.close - candle.open);
  if (body / range > maxBodyRatio) return null;
  const bodyFloor = Math.max(body, range * 0.05);
  const lowerWick = Math.min(candle.open, candle.close) - candle.low;
  const upperWick = candle.high - Math.max(candle.open, candle.close);
  if (lowerWick >= minWickBodyMult * bodyFloor && lowerWick > upperWick) return "up";
  if (upperWick >= minWickBodyMult * bodyFloor && upperWick > lowerWick) return "down";
  return null;
}

export interface PatternParams {
  pinBarMaxBodyRatio: number;
  pinBarMinWickMult: number;
}

/** Stricter than the backend strategy's own `pin_bar_*` params (0.35/2.0).
 * Those are calibrated as ONE OF SEVERAL gates on a specific breakout candle
 * inside `evaluate()`; applied to every candle on the whole chart, the
 * looser thresholds flagged ~35% of bars — unreadable clutter. Tightened
 * here (empirically, against real M5 data) to ~25%, matching engulfing's
 * own natural, non-tunable rate (~12%). */
export const DEFAULT_PATTERN_PARAMS: PatternParams = {
  pinBarMaxBodyRatio: 0.15,
  pinBarMinWickMult: 3.0,
};

/**
 * Candlestick pattern detection (engulfing, pin bar) over the whole loaded
 * candle series — the two patterns distinctive enough to be meaningful as an
 * always-on chart overlay. Mirrors the backend vix75 strategy's
 * `_is_bullish_engulfing`/`_is_bearish_engulfing`/`_is_pin_bar` (see
 * `backend/src/strategies/generated/"pob_price_action_snd for vix75_v1.py"`),
 * but evaluated at every candle instead of only at a strategy's own trade
 * entries. Deliberately excludes the strategy's third fallback pattern
 * ("body/momentum candle," any candle with a big-enough body) — that alone
 * matched ~33% of bars in testing, common enough to be noise rather than a
 * chart-worthy pattern; it stays a valid, useful gate inside the strategy's
 * own multi-filter `evaluate()`, just not here.
 */
export function detectPatterns(
  candles: Candle[],
  params: PatternParams = DEFAULT_PATTERN_PARAMS,
): PatternPoint[] {
  const points: PatternPoint[] = [];
  for (let i = 0; i < candles.length; i++) {
    let label: PatternLabel | null = null;
    if (isBullishEngulfing(candles, i)) {
      label = "bullish_engulfing";
    } else if (isBearishEngulfing(candles, i)) {
      label = "bearish_engulfing";
    } else {
      const pinSide = isPinBar(candles, i, params.pinBarMaxBodyRatio, params.pinBarMinWickMult);
      if (pinSide) {
        label = pinSide === "up" ? "bullish_pin_bar" : "bearish_pin_bar";
      }
    }
    if (label) {
      points.push({ time: candles[i].time as UTCTimestamp, price: candles[i].close, label });
    }
  }
  return points;
}

/** Average True Range with Wilder smoothing (same scheme as `rsi` above). */
export function atr(candles: Candle[], period: number): LinePoint[] {
  if (candles.length < period + 1) return [];
  const trueRanges: number[] = [];
  for (let i = 1; i < candles.length; i++) {
    const prevClose = candles[i - 1].close;
    trueRanges.push(
      Math.max(
        candles[i].high - candles[i].low,
        Math.abs(candles[i].high - prevClose),
        Math.abs(candles[i].low - prevClose),
      ),
    );
  }

  const points: LinePoint[] = [];
  let value = trueRanges.slice(0, period).reduce((sum, tr) => sum + tr, 0) / period;
  points.push(toPoint(candles[period], value));
  for (let i = period; i < trueRanges.length; i++) {
    value = (value * (period - 1) + trueRanges[i]) / period;
    points.push(toPoint(candles[i + 1], value));
  }
  return points;
}
