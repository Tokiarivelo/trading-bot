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
