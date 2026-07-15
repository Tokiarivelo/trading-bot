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

  for (let i = period - 1; i < candles.length; i++) {
    const window = candles.slice(i - period + 1, i + 1);
    const mean = window.reduce((sum, c) => sum + c.close, 0) / period;
    const variance = window.reduce((sum, c) => sum + (c.close - mean) ** 2, 0) / period;
    const sd = Math.sqrt(variance);
    middle.push(toPoint(candles[i], mean));
    upper.push(toPoint(candles[i], mean + stdDev * sd));
    lower.push(toPoint(candles[i], mean - stdDev * sd));
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

export type QuasimodoKind = "QML" | "QMR";

export interface QuasimodoZone {
  /** Time the pattern confirmed — the swing that broke structure. */
  time: UTCTimestamp;
  /** The "left shoulder" price level — where the QM entry zone sits. */
  price: number;
  kind: QuasimodoKind;
}

/**
 * Quasimodo levels derived from `swingStructure()`'s output — a chart
 * annotation only, not wired into any strategy's trading decision.
 *
 * QML (bearish/sell zone): two rising highs framing a higher low — a
 * "left shoulder" (first HH), then a "head" (second, bigger HH) — followed
 * by a swing low that breaks back below the low between them (structure
 * break down). The zone is the left shoulder's price: price often returns
 * there before continuing down. QMR (bullish/buy zone) is the mirror image.
 *
 * This is a best-effort algorithmic reading of the strategy spec's textual
 * description of QMR/QML/QMM ("left shoulder", "QM levels") — it hasn't been
 * validated against the source PDF's diagrams, so treat it as a reasonable
 * approximation, not a certified match to any specific course's exact rules.
 */
export function quasimodoLevels(points: StructurePoint[]): QuasimodoZone[] {
  const zones: QuasimodoZone[] = [];
  for (let i = 0; i + 3 < points.length; i++) {
    const shoulder = points[i + 1];
    const neckline = points[i + 2];
    const head = points[i + 3];

    // Bearish QML: ... HH(shoulder), HL(neckline), HH(head) — a rising
    // structure — then the first low after the head that breaks below the
    // neckline confirms it.
    if (shoulder.label === "HH" && neckline.label === "HL" && head.label === "HH") {
      for (let j = i + 4; j < points.length; j++) {
        const p = points[j];
        if (p.label === "HL" || p.label === "LL") {
          if (p.price < neckline.price) {
            zones.push({ time: p.time, price: shoulder.price, kind: "QML" });
          }
          break;
        }
      }
    }

    // Bullish QMR: mirror — LL(shoulder), LH(neckline), LL(head) — then the
    // first high after the head that breaks above the neckline confirms it.
    if (shoulder.label === "LL" && neckline.label === "LH" && head.label === "LL") {
      for (let j = i + 4; j < points.length; j++) {
        const p = points[j];
        if (p.label === "LH" || p.label === "HH") {
          if (p.price > neckline.price) {
            zones.push({ time: p.time, price: shoulder.price, kind: "QMR" });
          }
          break;
        }
      }
    }
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
