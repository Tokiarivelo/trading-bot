'use client';

/**
 * Chart feature (Phase 2+3): lightweight-charts candlesticks + volume, live WS
 * updates, timeframe switcher, spread indicator, and trade markers (F7) from
 * the journal — entry arrows + exit circles, refreshed alongside the spread.
 * Drawing tools (F-draw): lightweight-charts-drawing DrawingManager attached to
 * the candleSeries — toolbar in DrawingToolbar.tsx, persistence in localStorage.
 */

import {
  CandlestickSeries,
  createChart,
  createSeriesMarkers,
  HistogramSeries,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type LogicalRange,
  type MouseEventParams,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts';
import {
  DrawingManager,
  type IDrawing,
  type SerializedDrawing,
  TrendLine,
  ExtendedLine,
  HorizontalLine,
  VerticalLine,
  Rectangle,
  FibRetracement,
  ParallelChannel,
} from 'lightweight-charts-drawing';
import { History, Play, Square } from 'lucide-react';
import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import {
  getActiveNewsWindows,
  getBacktestReport,
  getCandles,
  getSymbolInfo,
  getTradeMarkers,
  type ActivityLogEntry,
  type BacktestTrade,
  type Candle,
  type NewsWindow,
  type PositionOut,
  type TradeMarker,
  type OrderSide,
  type PendingOrderType,
  type StrategyVersionSummary,
  evaluateCustomCode,
  type EvaluateCustomCodeResponse,
  type CustomSignal,
  computeIndicator,
  type ComputeIndicatorResponse,
} from '@/shared/api/client';
import { python } from '@codemirror/lang-python';
import { githubDarkInit } from '@uiw/codemirror-theme-github';
import CodeMirror from '@uiw/react-codemirror';
import { subscribeRoom } from '@/shared/api/ws';
import type { Trading } from '@/features/trading/useTrading';
import { BacktestStrategyEditor } from '@/features/backtest/BacktestStrategyEditor';
import { ActivityLogDock } from './ActivityLogDock';
import { DrawingToolbar } from './DrawingToolbar';
import { DrawingsList } from './DrawingsList';
import { IndicatorsDock } from './IndicatorsDock';
import { ReplayControls } from './ReplayControls';
import { SessionReplayPicker } from './SessionReplayPicker';
import {
  atr,
  bollinger,
  detectPatterns,
  ema,
  macd,
  quasimodoLevels,
  rsi,
  sma,
  swingStructure,
  vwap,
} from './indicators';

// Prefix for drawings this component adds itself (from the active strategy's
// PDF-derived price levels) so they can be told apart from the user's own —
// never persisted to localStorage, never removed by "Clear All".
const STRATEGY_DRAWING_PREFIX = 'strategy-derived:';
// Prefix for drawings rendered from a backtest report's trades (zone
// rectangles, SL/TP segments) — same "not user data" treatment as
// STRATEGY_DRAWING_PREFIX, but cleared/rebuilt on its own lifecycle (when
// the backtest report's trades change) rather than on every candle tick.
const BACKTEST_DRAWING_PREFIX = 'backtest-derived:';
// Prefix for the entry->exit oblique line drawn for closed *live* trades
// (journal-backed) — same "not user data" treatment as BACKTEST_DRAWING_PREFIX,
// but rebuilt on the live trade-markers poll cadence instead of the backtest
// report lifecycle.
const LIVE_TRADE_DRAWING_PREFIX = 'live-trade-derived:';
// Prefix for daily/period separators drawn on the chart.
const SEPARATOR_DRAWING_PREFIX = 'separator:';

/** True for any drawing this component added itself (strategy price levels,
 * backtest zone/SL annotations, live closed-trade lines, or period
 * separators) — never user data, so excluded from persistence, the
 * drawings-list panel, and "Clear All". */
function isProgrammaticDrawingId(id: string): boolean {
  return (
    id.startsWith(STRATEGY_DRAWING_PREFIX) ||
    id.startsWith(BACKTEST_DRAWING_PREFIX) ||
    id.startsWith(LIVE_TRADE_DRAWING_PREFIX) ||
    id.startsWith(SEPARATOR_DRAWING_PREFIX)
  );
}

/** Manually added indicator (via IndicatorsDock), independent of whatever
 * the active strategy's spec auto-draws — see `recomputeIndicators` below,
 * which plots both together. */
export type ManualIndicatorType =
  | 'ema'
  | 'sma'
  | 'rsi'
  | 'macd'
  | 'bollinger'
  | 'vwap'
  | 'atr'
  | 'structure'
  | 'qml'
  | 'patterns'
  | 'custom';

// Shared swing-detection constants for the 'structure'/'qml' indicators,
// matching the backend vix75 strategy's defaults (atr_period: 14,
// structure_margin_atr_mult: 0.1) so the chart's reading of "HH"/"QML"
// agrees with what the strategy itself computes per trade. Swing lookback
// itself is user-editable per instance (ManualIndicator.period).
const STRUCTURE_ATR_PERIOD = 14;
const STRUCTURE_MARGIN_ATR_MULT = 0.1;

export interface ManualIndicator {
  id: string;
  type: ManualIndicatorType;
  period: number;
  color: string;
  label: string;
  /** Set only when type === 'custom': the saved backend indicator's id
   * (GET /indicators/{id}) whose compute() output this instance plots. */
  indicatorId?: string;
}

/** Tool type strings accepted by DrawingManager.setActiveTool() */
export type DrawingToolType =
  | 'trend-line'
  | 'extended-line'
  | 'horizontal-line'
  | 'vertical-line'
  | 'rectangle'
  | 'fib-retracement'
  | 'parallel-channel';

const TIMEFRAMES: Candle['timeframe'][] = [
  'M1',
  'M5',
  'M15',
  'M30',
  'H1',
  'H4',
  'D1',
  'W1',
  'MN',
];
const LAST_TIMEFRAME_KEY = 'chart-last-timeframe';
const TIMEFRAME_QUERY_KEY = 'timeframe';
const CANDLE_COUNT = 300;
// Seconds per bar, used only to anchor backtest-view history loads (see
// `resolveInitialCandles` below) — approximate for W1/MN is fine since it
// only sizes a buffer, never the bars themselves.
const TIMEFRAME_SECONDS: Record<Candle['timeframe'], number> = {
  M1: 60,
  M5: 300,
  M15: 900,
  M30: 1800,
  H1: 3600,
  H4: 14_400,
  D1: 86_400,
  W1: 604_800,
  MN: 2_592_000,
};

// Session replay ("live session player" over an arbitrary historical period,
// independent of any backtest report): backend's `/market-data/candles` caps
// `count` at 5000 (market_data/api/routes.py), so a period wider than one
// page needs multiple requests paged backward via `before` — the "looping
// fetch" in `fetchCandlesForPeriod` below.
const SESSION_REPLAY_CHUNK_SIZE = 5000;
// Beyond this many candles the picker warns (but still allows) the period —
// it'll take more than one request to load.
const SESSION_REPLAY_WARN_CANDLES = 8000;
// Hard ceiling so a mis-picked period (e.g. years of M1) can't hang the tab
// on dozens of sequential requests or hold an enormous array in memory.
const SESSION_REPLAY_MAX_CANDLES = 60_000;
// Safety valve on the fetch loop itself (defense in depth beyond the picker's
// own block threshold) — a couple of pages of slack past what
// SESSION_REPLAY_MAX_CANDLES should ever require.
const SESSION_REPLAY_MAX_PAGES =
  Math.ceil(SESSION_REPLAY_MAX_CANDLES / SESSION_REPLAY_CHUNK_SIZE) + 2;

/** Fetches every candle in `[fromSec, toSec]`, paging backward one
 * `SESSION_REPLAY_CHUNK_SIZE`-sized page at a time (same `before`-cursor
 * pattern as the chart's own "load more") until the range is covered.
 * `onPage` reports progress for the picker/banner UI. */
async function fetchCandlesForPeriod(
  symbol: string,
  timeframe: Candle['timeframe'],
  fromSec: number,
  toSec: number,
  onPage?: (page: number, loaded: number) => void,
): Promise<Candle[]> {
  let acc: Candle[] = [];
  // `before` excludes the cursor bar itself — nudge one bar past `toSec` so
  // the bar covering the period's end is still included in the first page.
  let cursor = toSec + TIMEFRAME_SECONDS[timeframe];
  for (let page = 1; page <= SESSION_REPLAY_MAX_PAGES; page++) {
    const batch = await getCandles(
      symbol,
      timeframe,
      SESSION_REPLAY_CHUNK_SIZE,
      cursor,
    );
    if (batch.length === 0) break;
    acc = [...batch, ...acc];
    onPage?.(page, acc.length);
    const oldest = batch[0];
    if (oldest.time <= fromSec || batch.length < SESSION_REPLAY_CHUNK_SIZE) break;
    cursor = oldest.time;
  }
  return acc.filter((c) => c.time >= fromSec && c.time <= toSec);
}

function isTimeframe(value: string | null): value is Candle['timeframe'] {
  return TIMEFRAMES.includes(value as Candle['timeframe']);
}

/**
 * Restores the timeframe to open on load — `?timeframe=` wins over the last
 * one picked on any chart (`chart-last-timeframe`), same priority order as
 * the symbol resolution in page.tsx.
 */
function loadLastTimeframe(): Candle['timeframe'] {
  try {
    const urlTimeframe = new URLSearchParams(window.location.search).get(
      TIMEFRAME_QUERY_KEY,
    );
    if (isTimeframe(urlTimeframe)) return urlTimeframe;
    const stored = localStorage.getItem(LAST_TIMEFRAME_KEY);
    return isTimeframe(stored) ? stored : 'M5';
  } catch {
    return 'M5';
  }
}
const SPREAD_POLL_MS = 3000;
const MARKERS_POLL_MS = 5000;
// Matches the backend's own news-window transition-check cadence — no point
// polling faster than the window state can actually change.
const NEWS_POLL_MS = 30_000;
// Start fetching the next page of history once the visible window's left
// edge gets this close to the oldest bar currently loaded, so more arrives
// before the user actually scrolls past the end of the data.
const LOAD_MORE_THRESHOLD = 50;

/** Number of anchor clicks needed to complete each drawing tool. */
const REQUIRED_ANCHORS: Record<DrawingToolType, number> = {
  'trend-line': 2,
  'extended-line': 2,
  'horizontal-line': 1,
  'vertical-line': 1,
  rectangle: 2,
  'fib-retracement': 2,
  'parallel-channel': 3,
};

function cssVar(name: string): string {
  const val = getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim();
  if (val) return val;
  // Fallbacks in case the document stylesheets haven't parsed yet:
  switch (name) {
    case '--color-bg':
      return '#131722';
    case '--color-panel':
      return '#1e222d';
    case '--color-line':
      return '#2a2e39';
    case '--color-ink':
      return '#d1d4dc';
    case '--color-ink-muted':
      return '#5d606b';
    case '--color-accent':
      return '#2962ff';
    case '--color-ok':
      return '#26a69a';
    case '--color-err':
      return '#ef5350';
    case '--color-buy':
      return '#42a5f5';
    case '--color-sell':
      return '#ff9800';
    default:
      return '';
  }
}

function hexToRgba(hex: string, alpha: number): string {
  const clean = hex.replace('#', '');
  const value = parseInt(clean, 16);
  const r = (value >> 16) & 255;
  const g = (value >> 8) & 255;
  const b = value & 255;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

interface NewsBand {
  key: string;
  left: number;
  width: number;
  label: string;
  phase: 'pre' | 'post';
}

/**
 * Restores saved drawings for `symbol` from localStorage into `manager`.
 * Uses a minimal factory that maps the serialised `type` string back to
 * the appropriate Drawing subclass — only the tools we expose in the toolbar
 * are covered; unknown types are silently skipped so old/unknown data can
 * never crash the chart.
 */
function loadDrawingsFromStorage(
  manager: DrawingManager,
  symbol: string,
): void {
  try {
    const raw = localStorage.getItem(`chart-drawings:${symbol}`);
    if (!raw) return;
    const data: SerializedDrawing[] = JSON.parse(raw);
    manager.importDrawings(data, (type, d) => {
      switch (type) {
        case 'trend-line':
          return new TrendLine(d.id, d.anchors, d.style, d.options);
        case 'extended-line':
          return new ExtendedLine(d.id, d.anchors, d.style, d.options);
        case 'horizontal-line':
          return new HorizontalLine(d.id, d.anchors, d.style, d.options);
        case 'vertical-line':
          return new VerticalLine(d.id, d.anchors, d.style, d.options);
        case 'rectangle':
          return new Rectangle(d.id, d.anchors, d.style, d.options);
        case 'fib-retracement':
          return new FibRetracement(d.id, d.anchors, d.style, d.options);
        case 'parallel-channel':
          return new ParallelChannel(d.id, d.anchors, d.style, d.options);
        default:
          return null;
      }
    });
  } catch {
    // Corrupt or missing localStorage data is silently ignored.
  }
}

/** Restores manually-added indicators for `symbol` from localStorage. */
function loadManualIndicators(symbol: string): ManualIndicator[] {
  try {
    const raw = localStorage.getItem(`chart-indicators:${symbol}`);
    if (!raw) return [];
    return JSON.parse(raw) as ManualIndicator[];
  } catch {
    return [];
  }
}

function saveManualIndicators(
  symbol: string,
  indicators: ManualIndicator[],
): void {
  try {
    localStorage.setItem(
      `chart-indicators:${symbol}`,
      JSON.stringify(indicators),
    );
  } catch {
    // localStorage quota or serialisation errors are non-fatal.
  }
}

/** Removes every drawing except strategy-derived ones (see
 * `STRATEGY_DRAWING_PREFIX`) — used in place of `manager.clearAll()`
 * wherever the intent is "clear *my* drawings", not the strategy's
 * auto-plotted price levels. */
function clearUserDrawings(manager: DrawingManager): void {
  for (const drawing of manager.getAllDrawings()) {
    if (!isProgrammaticDrawingId(drawing.id)) {
      manager.removeDrawing(drawing.id);
    }
  }
}

interface PriceLineSpec {
  key: string;
  price: number;
  color: string;
  label: string;
  commit: (newPrice: number) => void;
  placeholder?: boolean; // no sl/tp set yet — drag (or click) this to add one
}

// Default distance for a not-yet-set SL/TP placeholder line: a flat points
// value would be meaningless across arbitrary instruments (gold vs. a
// synthetic index vs. BTC), so scale it off the reference price instead.
function defaultOffset(referencePrice: number): number {
  return Math.abs(referencePrice) * 0.005 || 1;
}

function numOrNull(value: string): number | null {
  if (value.trim() === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

interface EntryLineSpec {
  key: string;
  position: PositionOut;
  color: string;
  label: string;
}

/** Double-click editor for a running position's entry line: SL/TP fields
 * plus a close button, positioned at the entry line's current pixel row. */
function PositionEditPopover({
  position,
  top,
  busy,
  onClose,
  onSave,
  onClosePosition,
}: {
  position: PositionOut;
  top: number;
  busy: boolean;
  onClose: () => void;
  onSave: (sl: number | null, tp: number | null) => void;
  onClosePosition: () => void;
}) {
  const [sl, setSl] = useState(position.sl === null ? '' : String(position.sl));
  const [tp, setTp] = useState(position.tp === null ? '' : String(position.tp));
  const sideClass = position.side === 'buy' ? 'text-buy' : 'text-sell';

  return (
    <div
      className='pointer-events-auto absolute right-2 z-10 flex w-40 -translate-y-1/2 flex-col gap-1 rounded border border-line bg-panel p-2 text-xs shadow-lg'
      style={{ top: `${top}px` }}
      onMouseDown={(e) => e.stopPropagation()}
      onDoubleClick={(e) => e.stopPropagation()}
    >
      <div className='flex items-center justify-between'>
        <span className={`font-bold ${sideClass}`}>
          #{position.ticket} {position.side.toUpperCase()}
        </span>
        <button
          onClick={onClose}
          className='cursor-pointer text-ink-muted hover:text-ink'
          title='Cancel'
        >
          ×
        </button>
      </div>
      <div className='flex gap-1'>
        <input
          className='w-1/2 rounded border border-line bg-transparent px-1 py-0.5'
          value={sl}
          onChange={(e) => setSl(e.target.value)}
          placeholder='SL'
        />
        <input
          className='w-1/2 rounded border border-line bg-transparent px-1 py-0.5'
          value={tp}
          onChange={(e) => setTp(e.target.value)}
          placeholder='TP'
        />
      </div>
      <div className='flex gap-1'>
        <button
          onClick={() => onSave(numOrNull(sl), numOrNull(tp))}
          disabled={busy}
          className='flex-1 cursor-pointer rounded border border-accent px-1 py-0.5 text-accent disabled:opacity-50'
        >
          Save
        </button>
        <button
          onClick={onClosePosition}
          disabled={busy}
          className='flex-1 cursor-pointer rounded border border-err px-1 py-0.5 text-err disabled:opacity-50'
        >
          Close
        </button>
      </div>
    </div>
  );
}

/** "YYYY-MM:YYYY-MM" spanning the currently-loaded candle range — the
 * period format `parse_period` (backend/src/backtest/application/period.py)
 * expects. Returns null with nothing loaded yet. */
function derivePeriodParam(candles: Candle[]): string | null {
  const oldestCandle = candles[0];
  const newestCandle = candles[candles.length - 1];
  if (!oldestCandle || !newestCandle) return null;
  const oldestDate = new Date(oldestCandle.time * 1000);
  const newestDate = new Date(newestCandle.time * 1000);
  const pad = (n: number) => String(n).padStart(2, '0');
  const oldestStr = `${oldestDate.getUTCFullYear()}-${pad(oldestDate.getUTCMonth() + 1)}`;
  const newestStr = `${newestDate.getUTCFullYear()}-${pad(newestDate.getUTCMonth() + 1)}`;
  return `${oldestStr}:${newestStr}`;
}

function toBar(candle: Candle) {
  return {
    time: candle.time as UTCTimestamp,
    open: candle.open,
    high: candle.high,
    low: candle.low,
    close: candle.close,
  };
}

function toVolumeBar(candle: Candle, upColor: string, downColor: string) {
  return {
    time: candle.time as UTCTimestamp,
    value: candle.tick_volume,
    color: candle.close >= candle.open ? upColor : downColor,
  };
}

function isCandleMessage(
  message: unknown,
): message is { type: 'candle_closed' | 'candle_update'; candle: Candle } {
  const type = (message as { type?: unknown } | null)?.type;
  return type === 'candle_closed' || type === 'candle_update';
}

function toSeriesMarkers(
  trades: TradeMarker[],
  colors: { ok: string; err: string },
): SeriesMarker<Time>[] {
  const markers: SeriesMarker<Time>[] = [];
  for (const t of trades) {
    markers.push({
      time: t.open_time as UTCTimestamp,
      position: t.side === 'buy' ? 'belowBar' : 'aboveBar',
      color: t.side === 'buy' ? colors.ok : colors.err,
      shape: t.side === 'buy' ? 'arrowUp' : 'arrowDown',
      text: `${t.side.toUpperCase()} ${t.volume}`,
    });
    if (t.close_time !== null) {
      markers.push({
        time: t.close_time as UTCTimestamp,
        position: 'inBar',
        color: (t.profit ?? 0) >= 0 ? colors.ok : colors.err,
        shape: 'circle',
        text:
          t.profit !== null
            ? `${t.profit >= 0 ? '+' : ''}${t.profit.toFixed(2)}`
            : 'close',
      });
    }
  }
  // The markers plugin requires ascending time order.
  return markers.sort((a, b) => (a.time as number) - (b.time as number));
}

/** `lightweight-charts-drawing`'s anchors call the chart's native
 * `timeToCoordinate`, which returns null (silently skipping the draw) unless
 * the time exactly matches a loaded bar's timestamp. Backtest trades always
 * open/close exactly on a candle close, so they match already — but a live
 * trade's open/close time is the broker's real fill timestamp, essentially
 * never aligned to a bar boundary on any timeframe. Snap it to the nearest
 * loaded candle so the anchor resolves to a real coordinate. `candles` is
 * ascending by time (see `candlesRef`). */
function nearestCandleTime(
  candles: Candle[],
  target: number,
): UTCTimestamp | null {
  if (candles.length === 0) return null;
  let lo = 0;
  let hi = candles.length - 1;
  if (target <= candles[lo].time) return candles[lo].time as UTCTimestamp;
  if (target >= candles[hi].time) return candles[hi].time as UTCTimestamp;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (candles[mid].time < target) lo = mid + 1;
    else hi = mid;
  }
  const after = candles[lo];
  const before = candles[Math.max(0, lo - 1)];
  return (
    target - before.time <= after.time - target ? before.time : after.time
  ) as UTCTimestamp;
}

/** Entry->exit oblique line for each closed live trade (LIVE_TRADE_DRAWING_PREFIX)
 * — mirrors the SL/TP-style segments `buildTradeSetupDrawings` draws for a
 * backtest report, but sourced from the journal's `TradeMarker[]` poll so a
 * closed live position is visible on the chart the same way. Open trades
 * (close_time/close_price still null) are skipped — there's no exit yet. */
function buildLiveTradeLineDrawings(
  trades: TradeMarker[],
  colors: { ok: string; err: string },
  candles: Candle[],
): IDrawing[] {
  const drawings: IDrawing[] = [];
  for (const t of trades) {
    if (t.close_time === null || t.close_price === null) continue;
    const openTime = nearestCandleTime(candles, t.open_time);
    const closeTime = nearestCandleTime(candles, t.close_time);
    if (openTime === null || closeTime === null) continue;
    drawings.push(
      buildExitLineDrawing(
        LIVE_TRADE_DRAWING_PREFIX,
        t.id,
        openTime,
        t.open_price,
        closeTime,
        t.close_price,
        t.profit ?? 0,
        colors,
      ),
    );
  }
  return drawings;
}

/** Same entry-arrow/exit-circle rendering as `toSeriesMarkers`, but for a
 * backtest report's closed trades (§F: "test the bot against candle
 * history") — a `BacktestTrade` always has a `close_time`/`close_price`
 * (the run is over), unlike a live `TradeMarker` which is null while open.
 * Also folds in the trade's `pattern` into the entry marker's text when the
 * strategy reports one. `t.structure` (the swing window that validated this
 * trade's zone) is intentionally NOT drawn here — it only covers each
 * trade's own ~100-bar lookback, so real swings between/around trades were
 * silently missing; the 'structure' manual indicator draws HH/HL/LH/LL over
 * the whole chart instead (see `swingStructure()` in indicators.ts). */
function toBacktestSeriesMarkers(
  trades: BacktestTrade[],
  colors: { ok: string; err: string },
): SeriesMarker<Time>[] {
  const markers: SeriesMarker<Time>[] = [];
  for (const t of trades) {
    markers.push({
      time: t.open_time as UTCTimestamp,
      position: t.side === 'buy' ? 'belowBar' : 'aboveBar',
      color: t.side === 'buy' ? colors.ok : colors.err,
      shape: t.side === 'buy' ? 'arrowUp' : 'arrowDown',
      text: t.pattern
        ? `${t.side.toUpperCase()} ${t.volume} · ${t.pattern}`
        : `${t.side.toUpperCase()} ${t.volume}`,
    });
    markers.push({
      time: t.close_time as UTCTimestamp,
      position: 'inBar',
      color: t.profit >= 0 ? colors.ok : colors.err,
      shape: 'circle',
      text: `${t.profit >= 0 ? '+' : ''}${t.profit.toFixed(2)}`,
    });
  }
  return markers.sort((a, b) => (a.time as number) - (b.time as number));
}

/** Oblique line from a closed trade's entry (open_time, open_price) to its
 * exit (close_time, close_price) — a closed position previously only left
 * behind an entry arrow + a small exit circle, with nothing tying them
 * together or showing the price path between them. Colored ok/err by
 * profit, same as the exit marker. */
function buildExitLineDrawing(
  idPrefix: string,
  tradeId: string,
  openTime: UTCTimestamp,
  openPrice: number,
  closeTime: UTCTimestamp,
  closePrice: number,
  profit: number,
  colors: { ok: string; err: string },
): IDrawing {
  return new TrendLine(
    `${idPrefix}exit-line:${tradeId}`,
    [
      { time: openTime, price: openPrice },
      { time: closeTime, price: closePrice },
    ],
    { lineColor: profit >= 0 ? colors.ok : colors.err, lineWidth: 2 },
    { locked: true },
  );
}

/** Zone rectangle + SL/TP segments for a single backtest trade — the part
 * that's known the moment the trade opens (unlike the exit line below, whose
 * color/endpoint depend on the close). Split out from the old
 * `buildBacktestZoneDrawings` so replay (§F, ChartPanel's trade-drawing
 * effect) can reveal a trade's setup at `open_time` and its exit separately
 * at `close_time`, instead of the whole bundle appearing at once. Each
 * segment is bounded to the trade's own open→close time span (unlike live's
 * full-chart `buildPriceLines()`), since a report can have many trades on
 * screen at once. Only strategies that set `Signal.zone`/`sl`/`tp` produce
 * anything here; trades without one are skipped for that piece. */
function buildTradeSetupDrawings(
  t: BacktestTrade,
  i: number,
  colors: { demand: string; supply: string; sl: string; tp: string },
): IDrawing[] {
  const drawings: IDrawing[] = [];
  if (t.zone) {
    const zoneColor = t.zone.kind === 'demand' ? colors.demand : colors.supply;
    drawings.push(
      new Rectangle(
        `${BACKTEST_DRAWING_PREFIX}zone:${i}`,
        [
          { time: t.zone.time_start as UTCTimestamp, price: t.zone.price_high },
          { time: t.zone.time_end as UTCTimestamp, price: t.zone.price_low },
        ],
        {
          lineColor: zoneColor,
          lineWidth: 1,
          fillColor: hexToRgba(zoneColor, 0.15),
        },
        { filled: true, locked: true },
      ),
    );
  }
  const openTime = t.open_time as UTCTimestamp;
  const closeTime = t.close_time as UTCTimestamp;
  if (t.sl !== null) {
    drawings.push(
      new TrendLine(
        `${BACKTEST_DRAWING_PREFIX}sl:${i}`,
        [
          { time: openTime, price: t.sl },
          { time: closeTime, price: t.sl },
        ],
        { lineColor: colors.sl, lineWidth: 1, lineDash: [4, 4] },
        { locked: true },
      ),
    );
  }
  if (t.tp !== null) {
    drawings.push(
      new TrendLine(
        `${BACKTEST_DRAWING_PREFIX}tp:${i}`,
        [
          { time: openTime, price: t.tp },
          { time: closeTime, price: t.tp },
        ],
        { lineColor: colors.tp, lineWidth: 1, lineDash: [4, 4] },
        { locked: true },
      ),
    );
  }
  return drawings;
}

const cmTheme = githubDarkInit({
  settings: {
    background: 'var(--color-bg)',
    gutterBackground: 'var(--color-bg)',
    lineHighlight: 'var(--color-panel)',
    foreground: 'var(--color-ink)',
    caret: 'var(--color-accent)',
    selection: 'color-mix(in srgb, var(--color-accent) 30%, transparent)',
  },
});

function toCustomSignalsSeriesMarkers(
  signals: CustomSignal[],
  colors: { ok: string; err: string },
): SeriesMarker<Time>[] {
  const markers: SeriesMarker<Time>[] = [];
  for (const s of signals) {
    markers.push({
      time: s.time as UTCTimestamp,
      position: s.direction === 'buy' ? 'belowBar' : 'aboveBar',
      color: s.direction === 'buy' ? colors.ok : colors.err,
      shape: s.direction === 'buy' ? 'arrowUp' : 'arrowDown',
      text: `${s.direction.toUpperCase()}: ${s.reason}`,
    });
  }
  return markers.sort((a, b) => (a.time as number) - (b.time as number));
}

const DEFAULT_CUSTOM_CODE_TEMPLATE = `import pandas as pd
from src.strategies.domain.models import Direction, MarketContext, Signal, StrategySpec

class CustomScriptStrategy:
    def __init__(self) -> None:
        self.spec = StrategySpec(
            name="custom_script",
            version=1,
            symbols=("XAUUSD", "Volatility 75 Index"),
            entry_timeframe="M5",
            confirmation_timeframes=(),
            params={}
        )

    def indicators(self, candles: dict[str, pd.DataFrame]) -> dict[str, list]:
        df = candles[self.spec.entry_timeframe]
        # Example: Calculate a 20-period Simple Moving Average (SMA)
        sma_20 = df["close"].rolling(20).mean()
        return {
            "SMA 20": sma_20.tolist()
        }

    def evaluate(self, ctx: MarketContext) -> Signal | None:
        df = ctx.candles[self.spec.entry_timeframe]
        if len(df) < 21:
            return None
            
        # Example logic: Close crosses above SMA 20
        close_prev = df["close"].iloc[-2]
        close_curr = df["close"].iloc[-1]
        
        # Calculate SMA 20 for previous and current bar
        sma_20 = df["close"].rolling(20).mean()
        sma_prev = sma_20.iloc[-2]
        sma_curr = sma_20.iloc[-1]
        
        if close_prev <= sma_prev and close_curr > sma_curr:
            return Signal(direction=Direction.BUY, sl_points=200, tp_points=400, reason="Cross above SMA 20")
        elif close_prev >= sma_prev and close_curr < sma_curr:
            return Signal(direction=Direction.SELL, sl_points=200, tp_points=400, reason="Cross below SMA 20")
            
        return None
`;

interface ChartContextMenuProps {
  x: number;
  y: number;
  price: number;
  containerWidth: number;
  containerHeight: number;
  onSelectOption: (side: OrderSide, type: PendingOrderType) => void;
}

function ChartContextMenu({
  x,
  y,
  price,
  containerWidth,
  containerHeight,
  onSelectOption,
}: ChartContextMenuProps) {
  const menuWidth = 160;
  const menuHeight = 130;
  const left = x + menuWidth > containerWidth ? x - menuWidth : x;
  const top = y + menuHeight > containerHeight ? y - menuHeight : y;

  return (
    <div
      id='chart-context-menu'
      className='pointer-events-auto absolute z-30 flex w-40 flex-col rounded border border-line bg-panel py-1 text-xs shadow-xl backdrop-blur-sm bg-opacity-95'
      style={{ left: `${left}px`, top: `${top}px` }}
      onMouseDown={(e) => e.stopPropagation()}
    >
      <div className='border-b border-line px-2 py-1 text-[10px] font-semibold text-ink-muted'>
        Price: {price.toFixed(5)}
      </div>
      <button
        onClick={() => onSelectOption('buy', 'limit')}
        className='w-full text-left px-2 py-1.5 hover:bg-line text-ok transition-colors font-semibold'
      >
        Buy Limit
      </button>
      <button
        onClick={() => onSelectOption('buy', 'stop')}
        className='w-full text-left px-2 py-1.5 hover:bg-line text-ok transition-colors font-semibold'
      >
        Buy Stop
      </button>
      <button
        onClick={() => onSelectOption('sell', 'limit')}
        className='w-full text-left px-2 py-1.5 hover:bg-line text-err transition-colors font-semibold'
      >
        Sell Limit
      </button>
      <button
        onClick={() => onSelectOption('sell', 'stop')}
        className='w-full text-left px-2 py-1.5 hover:bg-line text-err transition-colors font-semibold'
      >
        Sell Stop
      </button>
    </div>
  );
}

interface ChartOrderPopoverProps {
  x: number;
  y: number;
  price: number;
  side: OrderSide;
  orderType: PendingOrderType;
  containerWidth: number;
  containerHeight: number;
  busy: boolean;
  onClose: () => void;
  onPlace: (
    volume: number,
    price: number,
    sl: number | null,
    tp: number | null,
  ) => Promise<void>;
}

function ChartOrderPopover({
  x,
  y,
  price: initialPrice,
  side,
  orderType,
  containerWidth,
  containerHeight,
  busy: parentBusy,
  onClose,
  onPlace,
}: ChartOrderPopoverProps) {
  const [volume, setVolume] = useState(() => {
    return localStorage.getItem('chart-last-volume') || '0.01';
  });
  const [priceStr, setPriceStr] = useState(initialPrice.toFixed(5));
  const [sl, setSl] = useState('');
  const [tp, setTp] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [localBusy, setLocalBusy] = useState(false);

  const isBuy = side === 'buy';
  const sideColorClass = isBuy ? 'text-ok' : 'text-err';
  const buttonBgClass = isBuy
    ? 'bg-ok hover:bg-opacity-90'
    : 'bg-err hover:bg-opacity-90';
  const buttonTextClass = isBuy ? 'text-[#04211e]' : 'text-[#2b0808]';

  const popoverWidth = 180;
  const popoverHeight = 220;
  const left = x + popoverWidth > containerWidth ? x - popoverWidth : x;
  const top = y + popoverHeight > containerHeight ? y - popoverHeight : y;

  const handlePlace = async () => {
    const v = Number(volume);
    const p = Number(priceStr);
    if (!v || isNaN(v) || v <= 0) {
      setError('Invalid volume');
      return;
    }
    if (!p || isNaN(p) || p <= 0) {
      setError('Invalid price');
      return;
    }
    setError(null);
    setLocalBusy(true);
    try {
      localStorage.setItem('chart-last-volume', volume);
      await onPlace(v, p, numOrNull(sl), numOrNull(tp));
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Order placement failed');
    } finally {
      setLocalBusy(false);
    }
  };

  const isBusy = parentBusy || localBusy;

  return (
    <div
      id='chart-order-popover'
      className='pointer-events-auto absolute z-30 flex w-44 flex-col gap-2 rounded border border-line bg-panel p-3 text-xs shadow-xl backdrop-blur-sm bg-opacity-95'
      style={{ left: `${left}px`, top: `${top}px` }}
      onMouseDown={(e) => e.stopPropagation()}
    >
      <div className='flex items-center justify-between border-b border-line pb-1'>
        <span className={`font-bold uppercase ${sideColorClass}`}>
          {side} {orderType}
        </span>
        <button
          onClick={onClose}
          className='cursor-pointer text-ink-muted hover:text-ink text-sm font-bold'
          title='Cancel'
          disabled={isBusy}
        >
          ×
        </button>
      </div>

      {error && (
        <div className='text-[10px] text-err leading-tight'>{error}</div>
      )}

      <div className='flex flex-col gap-1'>
        <label className='text-[10px] text-ink-muted'>Volume (lots)</label>
        <input
          className='rounded border border-line bg-transparent px-1.5 py-0.5'
          value={volume}
          onChange={(e) => setVolume(e.target.value)}
          placeholder='0.01'
          disabled={isBusy}
        />
      </div>

      <div className='flex flex-col gap-1'>
        <label className='text-[10px] text-ink-muted'>Price</label>
        <input
          className='rounded border border-line bg-transparent px-1.5 py-0.5'
          value={priceStr}
          onChange={(e) => setPriceStr(e.target.value)}
          placeholder='Price'
          disabled={isBusy}
        />
      </div>

      <div className='flex gap-2'>
        <div className='flex flex-1 flex-col gap-1'>
          <label className='text-[10px] text-ink-muted'>SL (opt)</label>
          <input
            className='w-full rounded border border-line bg-transparent px-1.5 py-0.5'
            value={sl}
            onChange={(e) => setSl(e.target.value)}
            placeholder='SL'
            disabled={isBusy}
          />
        </div>
        <div className='flex flex-1 flex-col gap-1'>
          <label className='text-[10px] text-ink-muted'>TP (opt)</label>
          <input
            className='w-full rounded border border-line bg-transparent px-1.5 py-0.5'
            value={tp}
            onChange={(e) => setTp(e.target.value)}
            placeholder='TP'
            disabled={isBusy}
          />
        </div>
      </div>

      <button
        onClick={handlePlace}
        disabled={isBusy}
        className={`mt-1 cursor-pointer rounded py-1 px-2 font-bold transition-opacity ${buttonBgClass} ${buttonTextClass} disabled:opacity-50`}
      >
        {isBusy ? 'Placing...' : 'Place Order'}
      </button>
    </div>
  );
}

interface DrawingContextMenuProps {
  x: number;
  y: number;
  drawingType: string;
  containerWidth: number;
  containerHeight: number;
  onSelectEdit: () => void;
  onDelete: () => void;
}

function DrawingContextMenu({
  x,
  y,
  drawingType,
  containerWidth,
  containerHeight,
  onSelectEdit,
  onDelete,
}: DrawingContextMenuProps) {
  const menuWidth = 160;
  const menuHeight = 100;
  const left = x + menuWidth > containerWidth ? x - menuWidth : x;
  const top = y + menuHeight > containerHeight ? y - menuHeight : y;

  const typeLabels: Record<string, string> = {
    'trend-line': 'Trend Line',
    'extended-line': 'Extended Line',
    'horizontal-line': 'Horizontal Line',
    'vertical-line': 'Vertical Line',
    rectangle: 'Rectangle',
    'fib-retracement': 'Fibonacci Retr.',
    'parallel-channel': 'Parallel Channel',
  };

  return (
    <div
      id='drawing-context-menu'
      className='pointer-events-auto absolute z-30 flex w-40 flex-col rounded border border-line bg-panel py-1 text-xs shadow-xl backdrop-blur-sm bg-opacity-95'
      style={{ left: `${left}px`, top: `${top}px` }}
      onMouseDown={(e) => e.stopPropagation()}
    >
      <div className='border-b border-line px-2 py-1 text-[10px] font-semibold text-ink-muted'>
        {typeLabels[drawingType] || drawingType}
      </div>
      <button
        onClick={onSelectEdit}
        className='w-full text-left px-2 py-1.5 hover:bg-line text-ink transition-colors font-semibold flex items-center gap-1.5 cursor-pointer'
      >
        <span>✏️</span> Edit Style
      </button>
      <button
        onClick={onDelete}
        className='w-full text-left px-2 py-1.5 hover:bg-line text-err transition-colors font-semibold flex items-center gap-1.5 cursor-pointer'
      >
        <span>🗑️</span> Delete
      </button>
    </div>
  );
}

interface DrawingEditPopoverProps {
  x: number;
  y: number;
  drawingId: string;
  drawingType: string;
  containerWidth: number;
  containerHeight: number;
  manager: DrawingManager | null;
  originalStylesRef: React.MutableRefObject<Record<string, any>>;
  onClose: () => void;
  onSaveAndSync: () => void;
  onColorChange: (id: string, color: string) => void;
}

function DrawingEditPopover({
  x,
  y,
  drawingId,
  drawingType,
  containerWidth,
  containerHeight,
  manager,
  originalStylesRef,
  onClose,
  onSaveAndSync,
  onColorChange,
}: DrawingEditPopoverProps) {
  const popoverWidth = 180;
  const popoverHeight = 160;
  const left = x + popoverWidth > containerWidth ? x - popoverWidth : x;
  const top = y + popoverHeight > containerHeight ? y - popoverHeight : y;

  const drawing = manager?.getDrawing(drawingId);
  const isLocked = drawing?.options?.locked === true;
  const isVisible = drawing?.options?.visible !== false;

  const backup = originalStylesRef.current[drawingId];
  const activeColor =
    backup?.lineColor || drawing?.style?.lineColor || '#2962ff';
  const activeWidth = backup?.lineWidth || drawing?.style?.lineWidth || 2;

  const PRESET_COLORS = [
    '#2962ff', // Blue
    '#26a69a', // Green
    '#ef5350', // Red
    '#ff9800', // Orange
    '#9c27b0', // Purple
    '#ffffff', // White
  ];

  const handleLockToggle = () => {
    if (drawing) {
      const nextLocked = !isLocked;
      drawing.updateOptions({ locked: nextLocked });
      onSaveAndSync();
    }
  };

  const handleVisibleToggle = () => {
    if (drawing) {
      const nextVisible = !isVisible;
      drawing.updateOptions({ visible: nextVisible });
      onSaveAndSync();
    }
  };

  const handleWidthChange = (width: number) => {
    if (drawing) {
      if (originalStylesRef.current[drawingId]) {
        originalStylesRef.current[drawingId].lineWidth = width;
      } else {
        drawing.updateStyle({ lineWidth: width });
      }
      onSaveAndSync();
    }
  };

  const typeLabels: Record<string, string> = {
    'trend-line': 'Trend Line',
    'extended-line': 'Extended Line',
    'horizontal-line': 'Horizontal Line',
    'vertical-line': 'Vertical Line',
    rectangle: 'Rectangle',
    'fib-retracement': 'Fibonacci Retr.',
    'parallel-channel': 'Parallel Channel',
  };

  return (
    <div
      id='drawing-edit-popover'
      className='pointer-events-auto absolute z-30 flex w-44 flex-col gap-2 rounded border border-line bg-panel p-3 text-xs shadow-xl backdrop-blur-sm bg-opacity-95'
      style={{ left: `${left}px`, top: `${top}px` }}
      onMouseDown={(e) => e.stopPropagation()}
    >
      <div className='flex items-center justify-between border-b border-line pb-1'>
        <span className='font-bold text-ink'>
          {typeLabels[drawingType] || 'Edit Drawing'}
        </span>
        <button
          onClick={onClose}
          className='cursor-pointer text-ink-muted hover:text-ink text-sm font-bold'
          title='Close'
        >
          ×
        </button>
      </div>

      <div className='flex flex-col gap-1'>
        <label className='text-[10px] text-ink-muted'>Color</label>
        <div className='flex items-center gap-1 flex-wrap'>
          {PRESET_COLORS.map((c) => (
            <button
              key={c}
              onClick={() => onColorChange(drawingId, c)}
              className={`cursor-pointer rounded-full border hover:scale-110 transition-transform ${
                activeColor === c ? 'border-ink scale-105' : 'border-line'
              }`}
              style={{
                width: 16,
                height: 16,
                backgroundColor: c,
              }}
              title={c}
            />
          ))}
          <input
            type='color'
            value={activeColor}
            onChange={(e) => onColorChange(drawingId, e.target.value)}
            className='color-picker-input cursor-pointer'
            style={{
              width: 16,
              height: 16,
              border: 'none',
              padding: 0,
              background: 'none',
            }}
            title='Custom color'
          />
        </div>
      </div>

      <div className='flex flex-col gap-1'>
        <label className='text-[10px] text-ink-muted'>Thickness</label>
        <div className='flex gap-1'>
          {[1, 2, 3, 4].map((w) => (
            <button
              key={w}
              onClick={() => handleWidthChange(w)}
              className={`flex-1 py-0.5 rounded border text-[10px] text-center transition-colors cursor-pointer ${
                activeWidth === w
                  ? 'border-accent text-accent font-bold bg-line'
                  : 'border-line text-ink-muted hover:text-ink'
              }`}
            >
              {w}px
            </button>
          ))}
        </div>
      </div>

      <div className='flex items-center justify-between mt-1 border-t border-line pt-2'>
        <button
          onClick={handleVisibleToggle}
          className={`flex items-center gap-1.5 px-2 py-1 rounded border text-[10px] cursor-pointer transition-colors ${
            isVisible
              ? 'border-line text-ink hover:bg-line'
              : 'border-err border-opacity-50 text-err hover:bg-err hover:bg-opacity-10'
          }`}
          title={isVisible ? 'Hide drawing' : 'Show drawing'}
        >
          <span>{isVisible ? '👁️ Visible' : '🚫 Hidden'}</span>
        </button>

        <button
          onClick={handleLockToggle}
          className={`flex items-center gap-1.5 px-2 py-1 rounded border text-[10px] cursor-pointer transition-colors ${
            isLocked
              ? 'border-err border-opacity-50 text-err hover:bg-err hover:bg-opacity-10'
              : 'border-line text-ink hover:bg-line'
          }`}
          title={isLocked ? 'Unlock drawing' : 'Lock drawing'}
        >
          <span>{isLocked ? '🔒 Locked' : '🔓 Unlocked'}</span>
        </button>
      </div>
    </div>
  );
}

export function ChartPanel({
  symbol,
  trading,
  activeStrategy,
  backtestReportId = null,
  onExitBacktestView,
  onReportChange,
}: {
  symbol: string;
  trading: Trading;
  activeStrategy: StrategyVersionSummary | null;
  /** When set, the chart shows this backtest report's trades as markers
   * (§F: "test the bot in chart for candle history") instead of the live
   * journal's — anchored to the historical candle window the report's
   * trades actually happened in, and with live WS updates paused so a
   * present-day candle doesn't get appended after months of history. */
  backtestReportId?: string | null;
  /** Called when the user leaves backtest view (only rendered while
   * `backtestReportId` is set) — the caller owns clearing the id/URL param. */
  onExitBacktestView?: () => void;
  /** Called with a new report id after the inline strategy editor (below)
   * saves an edit and re-runs the backtest — the caller owns swapping
   * `backtestReportId`/the URL to it so the chart picks up the new report's
   * trades without leaving the chart. */
  onReportChange?: (reportId: string) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const seriesMarkersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  // Separate marker-plugin instance for the manual 'structure'/'qml'
  // indicators (see recomputeIndicators) — kept independent of
  // seriesMarkersRef's trade-entry/exit markers so toggling structure on/off
  // never touches the live/backtest/custom-code marker-setting effects.
  const structureMarkersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(
    null,
  );
  // Drawing tools: one manager instance, alive for the lifetime of the chart.
  const drawingManagerRef = useRef<DrawingManager | null>(null);
  // Series added for the active strategy's PDF-derived indicators (EMA/SMA/
  // RSI/MACD/Bollinger) — replaced wholesale on every recompute.
  const indicatorSeriesRef = useRef<ISeriesApi<'Line' | 'Histogram'>[]>([]);
  const activeStrategyRef = useRef<StrategyVersionSummary | null>(
    activeStrategy,
  );
  activeStrategyRef.current = activeStrategy;
  // User-added indicators (via the IndicatorsDock), read fresh inside
  // recomputeIndicators the same way activeStrategyRef is.
  const manualIndicatorsRef = useRef<ManualIndicator[]>([]);
  // Computed series for each 'custom' (saved, backend-Python) manual
  // indicator instance, keyed by ManualIndicator.id — populated by
  // computeCustomIndicatorsRef below (an API round trip, so it can't live
  // inside the synchronous recomputeIndicators) and read fresh inside
  // recomputeIndicators the same way customCodeResultRef already is.
  const customIndicatorResultsRef = useRef<Record<string, ComputeIndicatorResponse>>({});
  // Reassigned every render (see the assignment below) so it always closes
  // over the current symbol/timeframe/manualIndicators — called both from
  // the effect below (add/remove/symbol/timeframe changes) and from the
  // chart-creation effect's `render()` once the initial history lands, so
  // an indicator added before candles finish loading still computes.
  const computeCustomIndicatorsRef = useRef<() => void>(() => {});
  // Set inside the chart-creation effect (has access to `chart`/`manager`),
  // invoked from the history/live-update effect below whenever new candle
  // data lands, and from the activeStrategy-change effect.
  const recomputeIndicatorsRef = useRef<() => void>(() => {});
  // Guards against applying a live WS update before the REST history load
  // for the current symbol/timeframe has landed — see the effect below.
  const historyLoadedRef = useRef(false);
  // All candles currently on the chart for this symbol/timeframe, oldest
  // first — kept in sync with live updates so "load more" always pages back
  // from the true oldest bar, and mutated in place (no React re-render).
  const candlesRef = useRef<Candle[]>([]);
  const hasMoreHistoryRef = useRef(true);
  const loadingMoreRef = useRef(false);
  // Backtest-view state (§F): the report's trades, converted to markers once
  // fetched, and an error flag for the "View on Chart" banner below.
  const [backtestTrades, setBacktestTrades] = useState<BacktestTrade[] | null>(
    null,
  );
  const [backtestError, setBacktestError] = useState<string | null>(null);
  // Strategy/symbol/period behind the current backtest report — fetched
  // alongside `backtestTrades` (see `resolveInitialCandles` below), and fed
  // to the inline strategy editor so it can be tested/tweaked right here
  // instead of navigating back to the report page.
  const [backtestMeta, setBacktestMeta] = useState<{
    strategy: string;
    symbol: string;
    period: string;
  } | null>(null);
  // Backtest report's own persisted activity log (signals/vetoes/fills for
  // this exact run, with simulated-clock timestamps) — distinct from
  // ActivityLogDock's default live/global poll, used to drive replay (below).
  const [backtestActivityLog, setBacktestActivityLog] = useState<
    ActivityLogEntry[] | null
  >(null);
  // Replay ("live session player", §F): progressively reveals the backtest
  // report's candles/indicators/trades/log up to a moving cursor instead of
  // drawing everything at once — see `visibleCandles()` below. `replayActive`
  // toggles the mode on/off (off = today's static full-report view,
  // unchanged); `replayActiveRef`/`replayCursorIndexRef` are the imperative
  // source of truth read by `visibleCandles()`/`render()`/`recomputeIndicators`
  // (closures created once per data-load, not re-created on every cursor
  // tick), while the `useState` pair only drives the player UI.
  const [replayActive, setReplayActive] = useState(false);
  const [replayPlaying, setReplayPlaying] = useState(false);
  const [replaySpeed, setReplaySpeed] = useState(1);
  const [replayCursorIndex, setReplayCursorIndex] = useState(0);
  const replayActiveRef = useRef(false);
  const replayCursorIndexRef = useRef(0);
  // Whether the view auto-centers on the cursor bar as it advances — turned
  // off by a manual drag/zoom (see the mousedown/wheel listener below), back
  // on via ReplayControls' "Center" button. `followingCursor` mirrors it
  // into state purely so the UI can show whether it's engaged.
  const followCursorRef = useRef(true);
  const [followingCursor, setFollowingCursor] = useState(true);
  // Track dragging/scrolling interaction and animation frame handles for replay panning
  const isMouseDownRef = useRef(false);
  const animationFrameRef = useRef<number | null>(null);
  // "open-count:close-count" signature of the trades revealed as of the last
  // trade-drawing rebuild — lets that effect skip rebuilding when a cursor
  // tick didn't actually cross any trade's reveal threshold (see below).
  const lastRevealedSignatureRef = useRef<string | null>(null);
  // Set at the end of the candle-loading effect below to the `render()`
  // closure created there, so the replay tick loop (a separate effect) can
  // trigger a redraw without duplicating candle/volume `setData()` logic.
  const renderRef = useRef<() => void>(() => {});
  // The single gate every candle/indicator render path reads through: the
  // full loaded window normally, or a prefix up to the replay cursor while
  // replaying — so candles, EMA/SMA/RSI/MACD/Bollinger, and every manual
  // indicator (VWAP/ATR/structure/QML/patterns) all become cursor-gated for
  // free by switching their one `candlesRef.current` read to this call.
  function visibleCandles(): Candle[] {
    if (!replayActiveRef.current) return candlesRef.current;
    return candlesRef.current.slice(0, replayCursorIndexRef.current + 1);
  }

  // Session replay: an arbitrary historical period, picked ad hoc (not tied
  // to a saved backtest report), replayed bar-by-bar like a live session.
  // `sessionReplayPeriod` drives the history-loading effect below the same
  // way `backtestReportId` does — pausing live WS and anchoring the initial
  // candle load to the picked window instead of "now" — and is cleared to
  // return to the live view.
  const [sessionReplayPeriod, setSessionReplayPeriod] = useState<{
    from: number;
    to: number;
  } | null>(null);
  const [showSessionReplayPicker, setShowSessionReplayPicker] = useState(false);
  const [sessionReplayFromInput, setSessionReplayFromInput] = useState('');
  const [sessionReplayToInput, setSessionReplayToInput] = useState('');
  // Progress while `fetchCandlesForPeriod`'s loop is still paging — null once
  // the fetch settles (success or failure).
  const [sessionReplayLoadingPage, setSessionReplayLoadingPage] = useState<{
    page: number;
    loaded: number;
  } | null>(null);

  function parseDateTimeLocal(value: string): number | null {
    if (!value) return null;
    const ms = new Date(value).getTime();
    return Number.isNaN(ms) ? null : Math.floor(ms / 1000);
  }

  const [showStrategyEditor, setShowStrategyEditor] = useState(false);
  // Drawer position for the strategy code editor
  type DrawerPosition = 'right' | 'left' | 'bottom' | 'top';
  const [drawerPosition, setDrawerPosition] = useState<DrawerPosition>('right');
  // Whether the strategy info pills are expanded
  const [strategyInfoExpanded, setStrategyInfoExpanded] = useState(false);

  const [showCustomCodeEditor, setShowCustomCodeEditor] = useState(false);
  const [customCodeDraft, setCustomCodeDraft] = useState(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('chart-custom-script-code');
      if (saved) return saved;
    }
    return DEFAULT_CUSTOM_CODE_TEMPLATE;
  });
  const [customCodeResult, setCustomCodeResult] =
    useState<EvaluateCustomCodeResponse | null>(null);
  const customCodeResultRef = useRef<EvaluateCustomCodeResponse | null>(null);
  customCodeResultRef.current = customCodeResult;
  const [customCodeBusy, setCustomCodeBusy] = useState(false);
  const [customCodeError, setCustomCodeError] = useState<string | null>(null);
  const [customCodeCopied, setCustomCodeCopied] = useState(false);

  const handleCopyCustomCode = () => {
    navigator.clipboard.writeText(customCodeDraft);
    setCustomCodeCopied(true);
    setTimeout(() => setCustomCodeCopied(false), 2000);
  };

  useEffect(() => {
    try {
      localStorage.setItem('chart-custom-script-code', customCodeDraft);
    } catch {}
  }, [customCodeDraft]);

  const [timeframe, setTimeframe] =
    useState<Candle['timeframe']>(loadLastTimeframe);
  const timeframeRef = useRef(timeframe);
  timeframeRef.current = timeframe;

  // Derived from the session-replay picker's raw input strings — recomputed
  // each render (cheap) rather than kept in state, since it always follows
  // directly from sessionReplayFromInput/ToInput/timeframe.
  const sessionReplayFromSec = parseDateTimeLocal(sessionReplayFromInput);
  const sessionReplayToSec = parseDateTimeLocal(sessionReplayToInput);
  const sessionReplayEstimate =
    sessionReplayFromSec !== null &&
    sessionReplayToSec !== null &&
    sessionReplayToSec > sessionReplayFromSec
      ? (() => {
          const candles = Math.ceil(
            (sessionReplayToSec - sessionReplayFromSec) /
              TIMEFRAME_SECONDS[timeframe],
          );
          const pages = Math.ceil(candles / SESSION_REPLAY_CHUNK_SIZE);
          const level: 'ok' | 'warn' | 'block' =
            candles > SESSION_REPLAY_MAX_CANDLES
              ? 'block'
              : candles > SESSION_REPLAY_WARN_CANDLES
                ? 'warn'
                : 'ok';
          return { candles, pages, level };
        })()
      : null;

  const [showSeparators, setShowSeparators] = useState<boolean>(() => {
    try {
      const stored = localStorage.getItem('chart-show-separators');
      return stored ? stored === 'true' : false;
    } catch {
      return false;
    }
  });
  const showSeparatorsRef = useRef(showSeparators);
  showSeparatorsRef.current = showSeparators;

  // Keep `?timeframe=` and the last-picked timeframe in sync so a refresh (or
  // a bookmarked/bare link) resumes on the same timeframe — same convention
  // as the `?symbol=`/`tb.lastSymbol` sync in page.tsx.
  useEffect(() => {
    const url = new URL(window.location.href);
    url.searchParams.set(TIMEFRAME_QUERY_KEY, timeframe);
    window.history.replaceState(null, '', url);
    try {
      localStorage.setItem(LAST_TIMEFRAME_KEY, timeframe);
    } catch {
      // Ignore blocked/full localStorage — timeframe just won't persist.
    }
  }, [timeframe]);

  const [spreadPoints, setSpreadPoints] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [newsBands, setNewsBands] = useState<NewsBand[]>([]);
  // Active drawing tool — null means normal pointer/pan mode.
  const [drawingTool, setDrawingTool] = useState<DrawingToolType | null>(null);
  // Mirror of manager.getAllDrawings() — kept in React state so the
  // DrawingsList panel re-renders whenever drawings are added/removed.
  const [drawingsList, setDrawingsList] = useState<IDrawing[]>([]);
  const [showDrawingsList, setShowDrawingsList] = useState(false);
  // Manually added indicators (independent of the active strategy's spec),
  // persisted per-symbol in localStorage — same convention as drawings.
  const [manualIndicators, setManualIndicators] = useState<ManualIndicator[]>(
    () => loadManualIndicators(symbol),
  );
  manualIndicatorsRef.current = manualIndicators;
  const [showIndicatorsDock, setShowIndicatorsDock] = useState(false);
  const [showActivityLogDock, setShowActivityLogDock] = useState(false);
  // How many anchor points the user has placed for the current in-progress
  // drawing (0 = none yet). Displayed as a hint in the header.
  const [pendingAnchorCount, setPendingAnchorCount] = useState(0);

  // Drawing color selection state
  const [activeColor, setActiveColor] = useState<string>('#2962ff');
  const activeColorRef = useRef(activeColor);
  activeColorRef.current = activeColor;

  // Stored original styles for drawings that are highlighted when selected
  const originalStylesRef = useRef<Record<string, any>>({});

  // Ref to invoke saveAndSync from outside the useEffect block
  const saveAndSyncRef = useRef<() => void>(() => {});

  // States for context menu and edit popover of drawings
  const [drawingContextMenu, setDrawingContextMenu] = useState<{
    x: number;
    y: number;
    drawingId: string;
    drawingType: string;
    containerWidth: number;
    containerHeight: number;
  } | null>(null);

  const [drawingEditPopover, setDrawingEditPopover] = useState<{
    x: number;
    y: number;
    drawingId: string;
    drawingType: string;
    containerWidth: number;
    containerHeight: number;
  } | null>(null);

  // Ticket of the running position whose entry line was double-clicked, if
  // any — drives the SL/TP/close popover rendered below the price lines.
  const [editingTicket, setEditingTicket] = useState<number | null>(null);
  const [editBusy, setEditBusy] = useState(false);

  // States for context menu and order popover from right-click on chart
  const [contextMenu, setContextMenu] = useState<{
    x: number;
    y: number;
    price: number;
    containerWidth: number;
    containerHeight: number;
  } | null>(null);

  const [orderPopover, setOrderPopover] = useState<{
    x: number;
    y: number;
    price: number;
    side: OrderSide;
    orderType: PendingOrderType;
    containerWidth: number;
    containerHeight: number;
  } | null>(null);

  // Stable references for symbol and symbol-switching state to avoid stale
  // closures inside the chart-creation useEffect.
  const symbolRef = useRef(symbol);
  symbolRef.current = symbol;
  const isSwitchingSymbolRef = useRef(false);
  const drawingToolRef = useRef(drawingTool);
  drawingToolRef.current = drawingTool;

  // SL/TP/trigger-price draggable lines (F-manual-trading): dragging updates
  // this only for live visual feedback during the drag — the actual API
  // call fires once on mouseup, via `spec.commit`.
  const [drag, setDrag] = useState<{
    key: string;
    price: number;
    commit: (p: number) => void;
  } | null>(null);
  const dragRef = useRef(drag);
  dragRef.current = drag;
  // Forces a re-render (to recompute price->pixel positions) on pan/zoom/resize,
  // same trigger set the news-band overlay below already reacts to.
  const [, bumpLines] = useState(0);
  // Keeps the click-to-trade subscription (below) stable across re-renders
  // instead of resubscribing on every `trading` poll tick.
  const placeFromClickRef = useRef(trading.placeFromClick);
  placeFromClickRef.current = trading.placeFromClick;

  // Create the chart once; destroy on unmount.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const line = cssVar('--color-line');
    const chart = createChart(container, {
      layout: {
        background: { color: cssVar('--color-panel') },
        textColor: cssVar('--color-ink'),
        // Required by lightweight-charts' free-tier license — do not hide or
        // replace this mark. Explicit `true` (not the implicit default) so
        // the license condition is visible here in code.
        attributionLogo: true,
      },
      grid: {
        vertLines: { color: line },
        horzLines: { color: line },
      },
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
        borderColor: line,
      },
      rightPriceScale: { borderColor: line },
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: cssVar('--color-ok'),
      downColor: cssVar('--color-err'),
      borderVisible: false,
      wickUpColor: cssVar('--color-ok'),
      wickDownColor: cssVar('--color-err'),
      autoscaleInfoProvider: (originalProvider: any) => {
        const res = originalProvider ? originalProvider() : null;
        if (replayActiveRef.current && followCursorRef.current) {
          const bars = visibleCandles();
          if (bars.length > 0) {
            const lastCandle = bars[bars.length - 1];
            const currentPrice = lastCandle.close;
            if (res && res.priceRange) {
              const { minValue, maxValue } = res.priceRange;
              const originalSpan = maxValue - minValue;
              const span = originalSpan > 0 ? originalSpan : currentPrice * 0.02;
              return {
                priceRange: {
                  minValue: currentPrice - span / 2,
                  maxValue: currentPrice + span / 2,
                }
              };
            } else {
              const span = currentPrice * 0.02;
              return {
                priceRange: {
                  minValue: currentPrice - span / 2,
                  maxValue: currentPrice + span / 2,
                }
              };
            }
          }
        }
        return res;
      }
    });

    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    });
    volumeSeries
      .priceScale()
      .applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;
    seriesMarkersRef.current = createSeriesMarkers(candleSeries, []);
    structureMarkersRef.current = createSeriesMarkers(candleSeries, []);

    // Attach the drawing manager to the chart and its primary series so the
    // drawing tools can convert pixel ↔ price/time coordinates and register
    // their mouse-event handlers on the container element.
    const manager = new DrawingManager();
    manager.attach(chart, candleSeries, container);
    drawingManagerRef.current = manager;

    // Recomputes every PDF-derived indicator overlay + price-level line for
    // whatever strategy is currently active on this symbol. Cheap enough to
    // call on every history load and every live tick (≤500 candles) — reads
    // `activeStrategyRef`/`candlesRef` fresh each time so it never closes
    // over stale props from the effect it's defined in.
    const recomputeIndicators = () => {
      for (const series of indicatorSeriesRef.current) {
        try {
          chart.removeSeries(series);
        } catch {
          // Series may already be gone if the chart is mid-teardown.
        }
      }
      indicatorSeriesRef.current = [];
      for (const drawing of manager.getAllDrawings()) {
        if (
          drawing.id.startsWith(STRATEGY_DRAWING_PREFIX) ||
          drawing.id.startsWith(SEPARATOR_DRAWING_PREFIX)
        ) {
          manager.removeDrawing(drawing.id);
        }
      }
      // Note: BACKTEST_DRAWING_PREFIX drawings are intentionally left alone
      // here — they're cleared/rebuilt by the backtest-trades effect only,
      // not on every recomputeIndicators call (candle tick, symbol switch).

      const spec = activeStrategyRef.current?.spec;
      const candles = visibleCandles();
      if (candles.length === 0) return;

      let rsiScaleReady = false;
      let macdScaleReady = false;
      let atrScaleReady = false;

      for (const indicator of spec?.indicators ?? []) {
        switch (indicator.type) {
          case 'ema': {
            const series = chart.addSeries(LineSeries, {
              color: '#42a5f5',
              lineWidth: 1,
              priceLineVisible: false,
              lastValueVisible: false,
              title: indicator.label,
            });
            series.setData(ema(candles, indicator.period));
            indicatorSeriesRef.current.push(series);
            break;
          }
          case 'sma': {
            const series = chart.addSeries(LineSeries, {
              color: '#ffa726',
              lineWidth: 1,
              priceLineVisible: false,
              lastValueVisible: false,
              title: indicator.label,
            });
            series.setData(sma(candles, indicator.period));
            indicatorSeriesRef.current.push(series);
            break;
          }
          case 'rsi': {
            const series = chart.addSeries(LineSeries, {
              color: '#ab47bc',
              lineWidth: 1,
              priceScaleId: 'strategy-rsi',
              priceLineVisible: false,
              lastValueVisible: false,
              title: indicator.label,
              autoscaleInfoProvider: () => ({
                priceRange: { minValue: 0, maxValue: 100 },
              }),
            });
            if (!rsiScaleReady) {
              // Own band above the volume series's band (top: 0.8, bottom: 0
              // — see the volume series setup above) so the two don't overlap.
              series
                .priceScale()
                .applyOptions({ scaleMargins: { top: 0.55, bottom: 0.25 } });
              rsiScaleReady = true;
            }
            series.setData(rsi(candles, indicator.period));
            indicatorSeriesRef.current.push(series);
            break;
          }
          case 'macd': {
            const slow = indicator.params.slow ?? 26;
            const signal = indicator.params.signal ?? 9;
            const { macdLine, signalLine, histogram } = macd(
              candles,
              indicator.period,
              slow,
              signal,
            );
            const macdSeries = chart.addSeries(LineSeries, {
              color: '#26a69a',
              lineWidth: 1,
              priceScaleId: 'strategy-macd',
              priceLineVisible: false,
              lastValueVisible: false,
              title: `${indicator.label} macd`,
            });
            const signalSeries = chart.addSeries(LineSeries, {
              color: '#ef5350',
              lineWidth: 1,
              priceScaleId: 'strategy-macd',
              priceLineVisible: false,
              lastValueVisible: false,
              title: `${indicator.label} signal`,
            });
            const histSeries = chart.addSeries(HistogramSeries, {
              priceScaleId: 'strategy-macd',
              priceLineVisible: false,
              lastValueVisible: false,
              title: `${indicator.label} hist`,
            });
            if (!macdScaleReady) {
              // Own band above RSI's (0.55-0.75) and volume's (0.8-1.0), so
              // all three can coexist without overlapping.
              macdSeries
                .priceScale()
                .applyOptions({ scaleMargins: { top: 0.3, bottom: 0.5 } });
              macdScaleReady = true;
            }
            macdSeries.setData(macdLine);
            signalSeries.setData(signalLine);
            histSeries.setData(histogram);
            indicatorSeriesRef.current.push(
              macdSeries,
              signalSeries,
              histSeries,
            );
            break;
          }
          case 'bollinger': {
            const stdDev = indicator.params.std_dev ?? 2;
            const { upper, middle, lower } = bollinger(
              candles,
              indicator.period,
              stdDev,
            );
            for (const [data, opacity] of [
              [upper, 1],
              [middle, 0.6],
              [lower, 1],
            ] as const) {
              const series = chart.addSeries(LineSeries, {
                color: hexToRgba('#78909c', opacity),
                lineWidth: 1,
                priceLineVisible: false,
                lastValueVisible: false,
                title: indicator.label,
              });
              series.setData(data);
              indicatorSeriesRef.current.push(series);
            }
            break;
          }
        }
      }

      if (spec) {
        const anchorTime = candles[0].time as UTCTimestamp;
        spec.price_levels.forEach((level, i) => {
          const color = level.type === 'support' ? '#26a69a' : '#ab47bc';
          const drawing = HorizontalLine.create(
            `${STRATEGY_DRAWING_PREFIX}${symbolRef.current}:${i}`,
            level.price,
            anchorTime,
            { lineColor: color, lineWidth: 1, lineDash: [4, 4] },
            {
              locked: true,
              showPrice: true,
              showLabel: true,
              labelText: level.label,
            },
          );
          manager.addDrawing(drawing);
        });
      }

      // User-added indicators from IndicatorsDock — plotted alongside
      // whatever the strategy spec above already drew. RSI/MACD reuse the
      // same panes (`strategy-rsi`/`strategy-macd`) as the strategy-derived
      // ones so oscillators from both sources stack in one place rather than
      // each opening a second pane.
      const structureMarkers: SeriesMarker<Time>[] = [];
      for (const manualIndicator of manualIndicatorsRef.current) {
        switch (manualIndicator.type) {
          case 'ema': {
            const series = chart.addSeries(LineSeries, {
              color: manualIndicator.color,
              lineWidth: 1,
              priceLineVisible: false,
              lastValueVisible: false,
              title: manualIndicator.label,
            });
            series.setData(ema(candles, manualIndicator.period));
            indicatorSeriesRef.current.push(series);
            break;
          }
          case 'sma': {
            const series = chart.addSeries(LineSeries, {
              color: manualIndicator.color,
              lineWidth: 1,
              priceLineVisible: false,
              lastValueVisible: false,
              title: manualIndicator.label,
            });
            series.setData(sma(candles, manualIndicator.period));
            indicatorSeriesRef.current.push(series);
            break;
          }
          case 'vwap': {
            const series = chart.addSeries(LineSeries, {
              color: manualIndicator.color,
              lineWidth: 1,
              priceLineVisible: false,
              lastValueVisible: false,
              title: manualIndicator.label,
            });
            series.setData(vwap(candles));
            indicatorSeriesRef.current.push(series);
            break;
          }
          case 'rsi': {
            const series = chart.addSeries(LineSeries, {
              color: manualIndicator.color,
              lineWidth: 1,
              priceScaleId: 'strategy-rsi',
              priceLineVisible: false,
              lastValueVisible: false,
              title: manualIndicator.label,
              autoscaleInfoProvider: () => ({
                priceRange: { minValue: 0, maxValue: 100 },
              }),
            });
            if (!rsiScaleReady) {
              series
                .priceScale()
                .applyOptions({ scaleMargins: { top: 0.55, bottom: 0.25 } });
              rsiScaleReady = true;
            }
            series.setData(rsi(candles, manualIndicator.period));
            indicatorSeriesRef.current.push(series);
            break;
          }
          case 'atr': {
            const series = chart.addSeries(LineSeries, {
              color: manualIndicator.color,
              lineWidth: 1,
              priceScaleId: 'manual-atr',
              priceLineVisible: false,
              lastValueVisible: false,
              title: manualIndicator.label,
            });
            if (!atrScaleReady) {
              // Own band, clear of RSI (0.55-0.75), MACD (0.3-0.5) and
              // volume (0.8-1.0).
              series
                .priceScale()
                .applyOptions({ scaleMargins: { top: 0.05, bottom: 0.75 } });
              atrScaleReady = true;
            }
            series.setData(atr(candles, manualIndicator.period));
            indicatorSeriesRef.current.push(series);
            break;
          }
          case 'macd': {
            const { macdLine, signalLine, histogram } = macd(
              candles,
              12,
              26,
              9,
            );
            const macdSeries = chart.addSeries(LineSeries, {
              color: manualIndicator.color,
              lineWidth: 1,
              priceScaleId: 'strategy-macd',
              priceLineVisible: false,
              lastValueVisible: false,
              title: `${manualIndicator.label} macd`,
            });
            const signalSeries = chart.addSeries(LineSeries, {
              color: '#ef5350',
              lineWidth: 1,
              priceScaleId: 'strategy-macd',
              priceLineVisible: false,
              lastValueVisible: false,
              title: `${manualIndicator.label} signal`,
            });
            const histSeries = chart.addSeries(HistogramSeries, {
              priceScaleId: 'strategy-macd',
              priceLineVisible: false,
              lastValueVisible: false,
              title: `${manualIndicator.label} hist`,
            });
            if (!macdScaleReady) {
              macdSeries
                .priceScale()
                .applyOptions({ scaleMargins: { top: 0.3, bottom: 0.5 } });
              macdScaleReady = true;
            }
            macdSeries.setData(macdLine);
            signalSeries.setData(signalLine);
            histSeries.setData(histogram);
            indicatorSeriesRef.current.push(
              macdSeries,
              signalSeries,
              histSeries,
            );
            break;
          }
          case 'bollinger': {
            const { upper, middle, lower } = bollinger(
              candles,
              manualIndicator.period,
              2,
            );
            for (const [data, opacity] of [
              [upper, 1],
              [middle, 0.6],
              [lower, 1],
            ] as const) {
              const series = chart.addSeries(LineSeries, {
                color: hexToRgba(manualIndicator.color, opacity),
                lineWidth: 1,
                priceLineVisible: false,
                lastValueVisible: false,
                title: manualIndicator.label,
              });
              series.setData(data);
              indicatorSeriesRef.current.push(series);
            }
            break;
          }
          case 'structure': {
            const points = swingStructure(
              candles,
              manualIndicator.period,
              STRUCTURE_ATR_PERIOD,
              STRUCTURE_MARGIN_ATR_MULT,
            );
            for (const p of points) {
              structureMarkers.push({
                time: p.time,
                position:
                  p.label === 'HH' || p.label === 'LH'
                    ? 'aboveBar'
                    : 'belowBar',
                color: manualIndicator.color,
                shape: 'circle',
                size: 0,
                text: p.label,
              });
            }
            break;
          }
          case 'qml': {
            const points = swingStructure(
              candles,
              manualIndicator.period,
              STRUCTURE_ATR_PERIOD,
              STRUCTURE_MARGIN_ATR_MULT,
            );
            const lastTime = candles[candles.length - 1]
              .time as UTCTimestamp;
            quasimodoLevels(points, candles).forEach((zone, zoneIdx) => {
              // Confirmation: the neckline-break candle, tagged at the QML
              // level (the left shoulder) where the retest entry sits.
              structureMarkers.push({
                time: zone.time,
                position: 'atPriceMiddle',
                price: zone.price,
                color: manualIndicator.color,
                shape: zone.kind === 'QML' ? 'arrowDown' : 'arrowUp',
                text: zone.kind === 'QML' ? 'QML' : 'QML-INV',
              });
              // The QM zone band between the QML level (left shoulder) and
              // the head (maximum pain level), from the head until the
              // retest consumes it — or still-open to the latest candle.
              // Supply (sell) tint for QML, demand (buy) for the inverse.
              const zoneColor =
                zone.kind === 'QML'
                  ? cssVar('--color-sell')
                  : cssVar('--color-buy');
              manager.addDrawing(
                new Rectangle(
                  `${STRATEGY_DRAWING_PREFIX}qml-zone:${manualIndicator.id}:${zoneIdx}`,
                  [
                    { time: zone.headTime, price: zone.headPrice },
                    { time: zone.retestTime ?? lastTime, price: zone.price },
                  ],
                  {
                    lineColor: zoneColor,
                    lineWidth: 1,
                    fillColor: hexToRgba(zoneColor, 0.15),
                  },
                  { filled: true, locked: true },
                ),
              );
              // Retest of the QML level after the break = the actual
              // entry signal (sell for QML, buy for the inversed pattern).
              if (zone.retestTime) {
                structureMarkers.push({
                  time: zone.retestTime,
                  position: 'atPriceMiddle',
                  price: zone.price,
                  color: manualIndicator.color,
                  shape: zone.kind === 'QML' ? 'arrowDown' : 'arrowUp',
                  text: zone.kind === 'QML' ? 'SELL' : 'BUY',
                });
              }
            });
            break;
          }
          case 'patterns': {
            for (const p of detectPatterns(candles)) {
              structureMarkers.push({
                time: p.time,
                position: p.label.startsWith('bullish')
                  ? 'belowBar'
                  : 'aboveBar',
                color: manualIndicator.color,
                shape: 'circle',
                size: 0,
                text: p.label,
              });
            }
            break;
          }
        }
      }
      // If we have custom code results, plot their custom indicators
      if (customCodeResultRef.current) {
        const { indicators, candles: customCandles } =
          customCodeResultRef.current;
        let colorIdx = 0;
        const CUSTOM_INDICATOR_COLORS = [
          '#00f0ff',
          '#e0aaff',
          '#ffd166',
          '#06d6a0',
          '#ff70a6',
        ];
        for (const [name, values] of Object.entries(indicators)) {
          const lineData = [];
          for (let i = 0; i < customCandles.length; i++) {
            const val = values[i];
            if (val !== null && val !== undefined) {
              lineData.push({
                time: customCandles[i].time as UTCTimestamp,
                value: val,
              });
            }
          }
          if (lineData.length > 0) {
            const series = chart.addSeries(LineSeries, {
              color:
                CUSTOM_INDICATOR_COLORS[
                  colorIdx % CUSTOM_INDICATOR_COLORS.length
                ],
              lineWidth: 2,
              priceLineVisible: false,
              lastValueVisible: false,
              title: name,
            });
            series.setData(lineData);
            indicatorSeriesRef.current.push(series);
            colorIdx++;
          }
        }
      }

      // Saved custom (backend-Python) indicators added via IndicatorsDock —
      // computed asynchronously by the computeCustomIndicators effect below
      // and cached per manual-indicator instance id in
      // customIndicatorResultsRef, so this stays a synchronous read like
      // every other case here. Silently skipped if the result hasn't
      // arrived yet or carries an error (surfaced in IndicatorsDock instead
      // of breaking the rest of the chart).
      //
      // A series name ending in `_marker_up`/`_marker_down`/`_marker` is a
      // reserved convention (see the PoB pattern/confirmation indicators)
      // for discrete one-off events — a candle pattern, a swing point, an
      // entry retest — rather than a continuous line. Values for those bars
      // would otherwise get silently connected by a straight line across
      // whatever gap separates two occurrences (LineSeries has no concept
      // of "these two points aren't related"), so they're routed through
      // the same `structureMarkers`/`structureMarkersRef` plugin the
      // built-in structure/QML/pattern indicators already use instead.
      for (const manualIndicator of manualIndicatorsRef.current) {
        if (manualIndicator.type !== 'custom' || !manualIndicator.indicatorId) continue;
        const result = customIndicatorResultsRef.current[manualIndicator.id];
        if (!result || result.error) continue;
        let colorIdx = 0;
        for (const [seriesName, values] of Object.entries(result.series)) {
          const markerKind = seriesName.endsWith('_marker_up')
            ? 'up'
            : seriesName.endsWith('_marker_down')
              ? 'down'
              : seriesName.endsWith('_marker')
                ? 'neutral'
                : null;

          if (markerKind) {
            const label = seriesName
              .replace(/_marker(_up|_down)?$/, '')
              .replace(/_/g, ' ');
            for (let i = 0; i < result.times.length; i++) {
              const val = values[i];
              if (val === null || val === undefined) continue;
              structureMarkers.push({
                time: result.times[i] as UTCTimestamp,
                position:
                  markerKind === 'up'
                    ? 'belowBar'
                    : markerKind === 'down'
                      ? 'aboveBar'
                      : 'atPriceMiddle',
                price: markerKind === 'neutral' ? val : undefined,
                color:
                  markerKind === 'up'
                    ? cssVar('--color-ok')
                    : markerKind === 'down'
                      ? cssVar('--color-err')
                      : manualIndicator.color,
                shape:
                  markerKind === 'up'
                    ? 'arrowUp'
                    : markerKind === 'down'
                      ? 'arrowDown'
                      : 'circle',
                size: markerKind === 'neutral' ? 0 : undefined,
                text: label,
              } as SeriesMarker<Time>);
            }
            continue;
          }

          const lineData: { time: UTCTimestamp; value: number }[] = [];
          for (let i = 0; i < result.times.length; i++) {
            const val = values[i];
            if (val !== null && val !== undefined) {
              lineData.push({ time: result.times[i] as UTCTimestamp, value: val });
            }
          }
          if (lineData.length === 0) continue;
          const series = chart.addSeries(LineSeries, {
            color: hexToRgba(manualIndicator.color, colorIdx === 0 ? 1 : 0.6),
            lineWidth: 1,
            priceLineVisible: false,
            lastValueVisible: false,
            title: `${manualIndicator.label} ${seriesName}`,
          });
          series.setData(lineData);
          indicatorSeriesRef.current.push(series);
          colorIdx++;
        }
      }
      structureMarkersRef.current?.setMarkers(
        structureMarkers.sort(
          (a, b) => (a.time as number) - (b.time as number),
        ),
      );

      // Draw day/period separators if enabled
      if (showSeparatorsRef.current) {
        const tf = timeframeRef.current;
        for (let i = 1; i < candles.length; i++) {
          const prev = candles[i - 1];
          const curr = candles[i];

          let isNew = false;
          const prevDate = new Date(prev.time * 1000);
          const currDate = new Date(curr.time * 1000);

          if (tf === 'W1') {
            isNew =
              prevDate.getUTCMonth() !== currDate.getUTCMonth() ||
              prevDate.getUTCFullYear() !== currDate.getUTCFullYear();
          } else if (tf === 'MN') {
            isNew = prevDate.getUTCFullYear() !== currDate.getUTCFullYear();
          } else if (tf === 'D1') {
            const prevWeek = Math.floor((prev.time / 86400 + 3) / 7);
            const currWeek = Math.floor((curr.time / 86400 + 3) / 7);
            isNew = prevWeek !== currWeek;
          } else {
            // M1, M5, M15, M30, H1, H4
            isNew =
              prevDate.getUTCDate() !== currDate.getUTCDate() ||
              prevDate.getUTCMonth() !== currDate.getUTCMonth() ||
              prevDate.getUTCFullYear() !== currDate.getUTCFullYear();
          }

          if (isNew) {
            const t = curr.time as UTCTimestamp;
            const drawing = VerticalLine.create(
              `${SEPARATOR_DRAWING_PREFIX}${symbolRef.current}:${i}`,
              t,
              curr.open,
              {
                lineColor: hexToRgba(cssVar('--color-ink'), 0.5),
                lineWidth: 1,
                lineDash: [4, 4],
              },
              {
                locked: true,
              }
            );
            manager.addDrawing(drawing);
          }
        }
      }
    };
    recomputeIndicatorsRef.current = recomputeIndicators;

    const highlightDrawing = (drawing: IDrawing) => {
      if (!originalStylesRef.current[drawing.id]) {
        originalStylesRef.current[drawing.id] = {
          lineColor: drawing.style.lineColor,
          lineWidth: drawing.style.lineWidth,
          lineDash: drawing.style.lineDash || [],
          fillColor: drawing.style.fillColor,
          showLabels: drawing.style.showLabels,
          labelColor: drawing.style.labelColor,
        };
      }
      drawing.updateStyle({
        lineWidth: 4,
        lineColor: '#00f0ff',
        labelColor: '#00f0ff',
        fillColor: hexToRgba('#00f0ff', 0.25),
      });
    };

    const restoreDrawing = (drawingId: string) => {
      const orig = originalStylesRef.current[drawingId];
      if (orig) {
        const drawing = manager.getDrawing(drawingId);
        if (drawing) {
          drawing.updateStyle(orig);
        }
        delete originalStylesRef.current[drawingId];
      }
    };

    // Persist drawings + keep the drawings-list panel in sync whenever any
    // drawing mutation happens.
    // Strategy-derived drawings are recomputed from the active spec on every
    // candle tick — they're never user data, so they're excluded from both
    // the persisted localStorage snapshot and the drawings-list panel.
    const syncList = () =>
      setDrawingsList(
        manager.getAllDrawings().filter((d) => !isProgrammaticDrawingId(d.id)),
      );
    const saveAndSync = () => {
      if (isSwitchingSymbolRef.current) {
        syncList();
        return;
      }
      try {
        const selected = manager.getSelectedDrawing();
        let backup: any = null;
        if (selected && originalStylesRef.current[selected.id]) {
          backup = { ...selected.style };
          selected.updateStyle(originalStylesRef.current[selected.id]);
        }

        const data = manager
          .exportDrawings()
          .filter((d) => !isProgrammaticDrawingId(d.id));
        localStorage.setItem(
          `chart-drawings:${symbolRef.current}`,
          JSON.stringify(data),
        );

        if (selected && backup) {
          selected.updateStyle(backup);
        }
      } catch {
        // localStorage quota or serialisation errors are non-fatal.
      }
      syncList();
    };
    saveAndSyncRef.current = saveAndSync;
    const syncSelectedColor = () => {
      const selected = manager.getSelectedDrawing();
      if (selected) {
        const orig = originalStylesRef.current[selected.id];
        if (orig && orig.lineColor) {
          setActiveColor(orig.lineColor);
        } else if (selected.style?.lineColor) {
          setActiveColor(selected.style.lineColor);
        }
      }
    };
    const unsubAdd = manager.on('drawing:added', saveAndSync);
    const unsubRemove = manager.on('drawing:removed', (e) => {
      if (e.drawingId) {
        delete originalStylesRef.current[e.drawingId];
      }
      saveAndSync();
    });
    const unsubClear = manager.on('drawing:cleared', () => {
      originalStylesRef.current = {};
      saveAndSync();
    });
    const unsubUpdate = manager.on('drawing:updated', saveAndSync);
    const unsubSelect = manager.on('drawing:selected', (e) => {
      if (e.drawing) {
        highlightDrawing(e.drawing);
      }
      syncSelectedColor();
      saveAndSync();
    });
    const unsubDeselect = manager.on('drawing:deselected', (e) => {
      if (e.drawingId) {
        restoreDrawing(e.drawingId);
      }
      saveAndSync();
    });

    // Restore any previously saved drawings for the initial symbol.
    loadDrawingsFromStorage(manager, symbolRef.current);
    // Initialise the drawings-list panel state.
    syncList();

    const resize = () =>
      chart.applyOptions({
        width: container.clientWidth,
        height: container.clientHeight,
      });
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(container);

    let isDraggingAnchor = false;
    let dragStartPoint: { x: number; y: number } | null = null;
    let dragDrawing: IDrawing | null = null;
    let dragInitialPixels: Array<{ x: number; y: number } | null> = [];

    // Event listener to lock chart panning/scaling when dragging/resizing a drawing
    const handleDrawingDragStart = (e: MouseEvent) => {
      if (!manager || !chart) return;
      if (drawingToolRef.current) return;

      const rect = container.getBoundingClientRect();
      const point = {
        x: e.clientX - rect.left,
        y: e.clientY - rect.top,
      };

      const anchorIndex = manager.hitTestAnchor(point);
      if (anchorIndex !== null) {
        isDraggingAnchor = true;
        container.style.cursor = 'grabbing';
        // Disable chart panning and zooming so the chart doesn't move during drag.
        chart.applyOptions({ handleScroll: false, handleScale: false });

        // Listen to mouseup on window to re-enable chart scrolling/scaling.
        const handleDragEnd = () => {
          isDraggingAnchor = false;
          container.style.cursor = '';
          chart.applyOptions({ handleScroll: true, handleScale: true });
          window.removeEventListener('mouseup', handleDragEnd);
        };
        window.addEventListener('mouseup', handleDragEnd);
        return;
      }

      const hoveredDrawing = manager.hitTest(point);
      if (hoveredDrawing !== null && !hoveredDrawing.options.locked) {
        // Automatically select the hovered drawing if it wasn't selected
        if (manager.getSelectedDrawing()?.id !== hoveredDrawing.id) {
          manager.selectDrawing(hoveredDrawing.id);
        }

        dragStartPoint = { x: e.clientX, y: e.clientY };
        dragDrawing = hoveredDrawing;

        const viewport = hoveredDrawing.getViewport();
        if (viewport) {
          dragInitialPixels = hoveredDrawing.anchors.map((a) =>
            (hoveredDrawing as any).anchorToPixel(a, viewport),
          );
        }

        container.style.cursor = 'grabbing';
        // Disable chart panning and zooming so the chart doesn't move during drag.
        chart.applyOptions({ handleScroll: false, handleScale: false });

        const handleBodyDrag = (moveEvent: MouseEvent) => {
          if (!dragStartPoint || !dragDrawing || !viewport) return;
          const dx = moveEvent.clientX - dragStartPoint.x;
          const dy = moveEvent.clientY - dragStartPoint.y;

          const newAnchors = dragDrawing.anchors.map((anchor, idx) => {
            const pixel = dragInitialPixels[idx];
            if (!pixel) return anchor;
            const newPixel = { x: pixel.x + dx, y: pixel.y + dy };
            const newAnchor = (dragDrawing as any).pixelToAnchor(
              newPixel,
              viewport,
            );
            return newAnchor || anchor;
          });

          dragDrawing.anchors = newAnchors;
          (manager as any).emit('drawing:updated', {
            drawingId: dragDrawing.id,
            drawing: dragDrawing,
          });
        };

        const handleBodyDragEnd = () => {
          window.removeEventListener('mousemove', handleBodyDrag);
          window.removeEventListener('mouseup', handleBodyDragEnd);

          dragStartPoint = null;
          dragDrawing = null;
          dragInitialPixels = [];

          container.style.cursor = '';
          chart.applyOptions({ handleScroll: true, handleScale: true });
          saveAndSync();
        };

        window.addEventListener('mousemove', handleBodyDrag);
        window.addEventListener('mouseup', handleBodyDragEnd);
      }
    };
    container.addEventListener('mousedown', handleDrawingDragStart, {
      capture: true,
    });

    const handleContextMenu = (e: MouseEvent) => {
      if (drawingToolRef.current) {
        setDrawingTool(null);
        e.preventDefault();
        return;
      }

      const rect = container.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;

      const hoveredDrawing = manager.hitTest({ x, y });
      if (hoveredDrawing !== null) {
        e.preventDefault();
        e.stopPropagation();

        manager.selectDrawing(hoveredDrawing.id);

        setOrderPopover(null);
        setContextMenu(null);
        setDrawingEditPopover(null);
        setDrawingContextMenu({
          x,
          y,
          drawingId: hoveredDrawing.id,
          drawingType: hoveredDrawing.type,
          containerWidth: container.clientWidth,
          containerHeight: container.clientHeight,
        });
        return;
      }

      const candleSeries = candleSeriesRef.current;
      if (!candleSeries) return;

      const price = candleSeries.coordinateToPrice(y);
      if (price === null) return;

      e.preventDefault();

      setOrderPopover(null);
      setDrawingContextMenu(null);
      setDrawingEditPopover(null);
      setContextMenu({
        x,
        y,
        price,
        containerWidth: container.clientWidth,
        containerHeight: container.clientHeight,
      });
    };
    container.addEventListener('contextmenu', handleContextMenu);

    const handleMouseMoveCursor = (e: MouseEvent) => {
      // Re-trigger layout updates for HTML overlays
      bumpLines((t) => t + 1);

      if (!manager || isDraggingAnchor) return;

      // If we are currently in drawing tool placement mode, let that cursor (crosshair) stay.
      if (drawingToolRef.current) {
        container.style.cursor = 'crosshair';
        return;
      }

      const rect = container.getBoundingClientRect();
      const point = {
        x: e.clientX - rect.left,
        y: e.clientY - rect.top,
      };

      // Check if hovering over an anchor point of the selected drawing
      const anchorIndex = manager.hitTestAnchor(point);
      if (anchorIndex !== null) {
        container.style.cursor = 'nwse-resize';
        return;
      }

      // Check if hovering over any drawing body
      const hoveredDrawing = manager.hitTest(point);
      if (hoveredDrawing !== null) {
        container.style.cursor = 'pointer';
        return;
      }

      // Default: let chart cursor rule
      container.style.cursor = '';
    };
    container.addEventListener('mousemove', handleMouseMoveCursor, {
      capture: true,
    });

    return () => {
      observer.disconnect();
      container.removeEventListener('contextmenu', handleContextMenu);
      container.removeEventListener('mousemove', handleMouseMoveCursor, {
        capture: true,
      });
      container.removeEventListener('mousedown', handleDrawingDragStart, {
        capture: true,
      });
      unsubAdd();
      unsubRemove();
      unsubClear();
      unsubUpdate();
      unsubSelect();
      unsubDeselect();
      seriesMarkersRef.current?.detach();
      structureMarkersRef.current?.detach();
      manager.detach();
      drawingManagerRef.current = null;
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
      seriesMarkersRef.current = null;
      structureMarkersRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Load history + subscribe to live updates whenever symbol/timeframe
  // changes — or, in backtest view, whenever the report being inspected
  // changes (§F: "test the bot in chart for candle history").
  useEffect(() => {
    let cancelled = false;
    setError(null);
    setLoadingMore(false);
    setContextMenu(null);
    setOrderPopover(null);
    setDrawingContextMenu(null);
    setDrawingEditPopover(null);
    setBacktestTrades(null);
    setBacktestActivityLog(null);
    setBacktestError(null);
    // A new symbol/timeframe/report invalidates any in-progress replay —
    // the cursor index no longer lines up with the freshly-loaded candles.
    replayActiveRef.current = false;
    replayCursorIndexRef.current = 0;
    followCursorRef.current = true;
    setReplayActive(false);
    setReplayPlaying(false);
    setReplayCursorIndex(0);
    setFollowingCursor(true);
    // WS updates for the new room can start arriving before the REST
    // history call below resolves. Applying one to the still-stale
    // previous symbol/timeframe's data can move time backwards (e.g.
    // switching from M1 to D1: the D1 forming bar's open time is earlier
    // than the M1 bar still on screen) and lightweight-charts throws.
    // Dropping live updates until history for *this* symbol/timeframe is
    // actually on the chart avoids that race.
    historyLoadedRef.current = false;
    candlesRef.current = [];
    hasMoreHistoryRef.current = true;
    loadingMoreRef.current = false;

    const chart = chartRef.current;

    // `recomputeIndicators` tears down and recreates every indicator series
    // (`chart.removeSeries`/`addSeries` per EMA/RSI/MACD/Bollinger line, plus
    // rebuilding every period-separator drawing) — fine to call on every live
    // tick (~once/1.5s) but far too expensive to run on literally every
    // replay bar at speed. `scheduleOverlayRecompute` throttles just that
    // part (leading + trailing edge: the first call after an idle period
    // runs immediately, rapid follow-up calls coalesce into one trailing
    // update `OVERLAY_THROTTLE_MS` later) while candle/volume `setData()`
    // below — cheap, just fills existing series — still runs every tick so
    // playback itself stays smooth.
    const OVERLAY_THROTTLE_MS = 200;
    let overlayTimer: ReturnType<typeof setTimeout> | null = null;
    let lastOverlayRun = 0;

    function runOverlaysNow() {
      lastOverlayRun = Date.now();
      recomputeIndicatorsRef.current();
      // Custom-code overlays stay full-range/ungated during replay (§F scope
      // decision) — skip re-running the sandboxed backend eval on every
      // cursor tick, which would otherwise fire an HTTP request per bar.
      if (!replayActiveRef.current) computeCustomIndicatorsRef.current();
    }

    function scheduleOverlayRecompute() {
      if (!replayActiveRef.current) {
        runOverlaysNow();
        return;
      }
      const elapsed = Date.now() - lastOverlayRun;
      if (elapsed >= OVERLAY_THROTTLE_MS) {
        runOverlaysNow();
        return;
      }
      if (overlayTimer) return;
      overlayTimer = setTimeout(() => {
        overlayTimer = null;
        runOverlaysNow();
      }, OVERLAY_THROTTLE_MS - elapsed);
    }

    function render() {
      const upColor = cssVar('--color-ok');
      const downColor = cssVar('--color-err');
      const bars = visibleCandles();
      candleSeriesRef.current?.setData(bars.map(toBar));
      volumeSeriesRef.current?.setData(
        bars.map((c) => toVolumeBar(c, upColor, downColor)),
      );
      scheduleOverlayRecompute();
      setTimeout(() => {
        if (!cancelled) bumpLines((t) => t + 1);
      }, 50);
    }

    // Fetches the next page of older bars once the user pans near the left
    // edge of what's loaded — the chart's "fetch more" is this auto-trigger
    // plus the `loadingMore` indicator rendered below, not a manual button.
    async function loadMore() {
      if (
        loadingMoreRef.current ||
        !hasMoreHistoryRef.current ||
        candlesRef.current.length === 0
      ) {
        return;
      }
      loadingMoreRef.current = true;
      setLoadingMore(true);
      const oldest = candlesRef.current[0];
      try {
        const older = await getCandles(
          symbol,
          timeframe,
          CANDLE_COUNT,
          oldest.time,
        );
        if (cancelled) return;
        if (older.length === 0) {
          hasMoreHistoryRef.current = false;
        } else {
          hasMoreHistoryRef.current = older.length >= CANDLE_COUNT;
          candlesRef.current = [...older, ...candlesRef.current];
          // Prepending shifts every existing bar's logical index forward by
          // the number of new bars, so the visible window must shift with
          // it or the chart jumps — lightweight-charts has no "prepend"
          // primitive, this is the documented workaround for setData().
          // We snapshot the range *before* setData, call setData, then restore
          // via requestAnimationFrame so the adjustment runs after the new
          // layout pass — applying it synchronously can land before the bars
          // are actually committed and produce an off-by-N shift.
          const range = chart?.timeScale().getVisibleLogicalRange();
          if (replayActiveRef.current) {
            replayCursorIndexRef.current += older.length;
            setReplayCursorIndex((prev) => prev + older.length);
          }
          render();
          if (range) {
            requestAnimationFrame(() => {
              if (!cancelled) {
                chart?.timeScale().setVisibleLogicalRange({
                  from: range.from + older.length,
                  to: range.to + older.length,
                });
              }
            });
          }
        }
      } catch {
        // Transient failure — leave hasMore true so the next pan retries.
      } finally {
        if (!cancelled) {
          loadingMoreRef.current = false;
          setLoadingMore(false);
        }
      }
    }

    const onVisibleRangeChange = (range: LogicalRange | null) => {
      if (range && range.from < LOAD_MORE_THRESHOLD) void loadMore();
    };
    chart?.timeScale().subscribeVisibleLogicalRangeChange(onVisibleRangeChange);

    // Backtest view anchors history to the report's own trades instead of
    // "now" — just past the last trade's close, scaled to a couple of bars
    // of the current timeframe, so the anchor guarantees that trade's candle
    // is included without burning most of CANDLE_COUNT's budget on empty
    // time past the trades (a flat multi-hour buffer would eat most of a
    // 300-bar M5 window and push every earlier trade off the loaded page).
    async function resolveInitialCandles(): Promise<Candle[]> {
      if (sessionReplayPeriod) {
        setSessionReplayLoadingPage({ page: 0, loaded: 0 });
        return fetchCandlesForPeriod(
          symbol,
          timeframe,
          sessionReplayPeriod.from,
          sessionReplayPeriod.to,
          (page, loaded) => {
            if (!cancelled) setSessionReplayLoadingPage({ page, loaded });
          },
        );
      }
      if (!backtestReportId) return getCandles(symbol, timeframe, CANDLE_COUNT);
      const report = await getBacktestReport(backtestReportId);
      if (cancelled) return [];
      setBacktestTrades(report.trades);
      setBacktestActivityLog(report.activity_log);
      setBacktestMeta({
        strategy: report.strategy,
        symbol: report.symbol,
        period: report.period,
      });
      const lastClose = report.trades.reduce(
        (max, t) => Math.max(max, t.close_time),
        0,
      );
      const anchor =
        lastClose > 0
          ? lastClose + 2 * TIMEFRAME_SECONDS[timeframe]
          : undefined;
      return getCandles(symbol, timeframe, CANDLE_COUNT, anchor);
    }

    renderRef.current = render;

    resolveInitialCandles()
      .then((candles) => {
        if (cancelled) return;
        candlesRef.current = candles;
        // Session replay's window is deliberately bounded by the picked
        // period — panning left shouldn't silently pull in history from
        // before it, unlike the live/backtest views' open-ended paging.
        hasMoreHistoryRef.current = sessionReplayPeriod
          ? false
          : candles.length >= CANDLE_COUNT;
        render();
        historyLoadedRef.current = true;
        setSessionReplayLoadingPage(null);
        // A symbol/timeframe switch loads a fresh price/time range, but
        // lightweight-charts keeps whatever pan/zoom/price-scale state was
        // active for the previous symbol. `scrollToRealTime()` alone only
        // moves the time axis — it doesn't reset the logical range or price
        // scale, so e.g. switching from BTCUSD (~60000) to XAGUSD (~30) can
        // leave the new candles partly or fully outside the viewport.
        // `fitContent()` plus forcing `autoScale` back on fixes both.
        candleSeriesRef.current?.priceScale().applyOptions({ autoScale: true });
        chart?.timeScale().fitContent();
        setTimeout(() => {
          if (!cancelled) bumpLines((t) => t + 1);
        }, 50);
        // Session replay has no separate "static full view" step — entering
        // the mode always means playing through the picked period.
        if (sessionReplayPeriod) handleEnterReplay();
      })
      .catch(() => {
        if (cancelled) return;
        setSessionReplayLoadingPage(null);
        setError(
          backtestReportId
            ? 'failed to load backtest report'
            : sessionReplayPeriod
              ? 'failed to load session replay candles'
              : 'failed to load candles',
        );
        if (backtestReportId)
          setBacktestError('failed to load backtest report');
        if (sessionReplayPeriod) setSessionReplayPeriod(null);
      });

    // Live candle updates only make sense against "now" — in backtest view
    // or session replay the chart is anchored to a historical window, so a
    // fresh WS tick would just append a stray present-day bar after a
    // months-wide gap.
    if (backtestReportId || sessionReplayPeriod) {
      return () => {
        cancelled = true;
        if (overlayTimer) clearTimeout(overlayTimer);
        historyLoadedRef.current = false;
        chart
          ?.timeScale()
          .unsubscribeVisibleLogicalRangeChange(onVisibleRangeChange);
      };
    }

    // `candle_update` streams the in-progress bar every ~1.5s so the
    // rightmost candle moves continuously like MT5; `candle_closed` is the
    // authoritative final print once the bar completes. Both are handled
    // identically here — lightweight-charts' `update()` amends the last bar
    // in place when the timestamp matches, or appends a new one otherwise.
    const unsubscribe = subscribeRoom(
      ['candle_closed', 'candle_update'],
      { symbol, timeframe },
      (message) => {
        if (!isCandleMessage(message)) return;
        if (!historyLoadedRef.current) return;
        const { candle } = message;
        const bars = candlesRef.current;
        const lastTime =
          bars.length > 0 ? bars[bars.length - 1].time : undefined;
        if (lastTime !== undefined && candle.time < lastTime) {
          // Stale/out-of-order message (e.g. stream jitter) — pushing this
          // would break the ascending-time invariant every indicator and
          // lightweight-charts itself relies on, so drop it instead.
          console.warn(
            'chart: dropped out-of-order candle update',
            candle.time,
            'last',
            lastTime,
          );
          return;
        }
        if (lastTime === candle.time) {
          bars[bars.length - 1] = candle;
        } else {
          bars.push(candle);
        }
        try {
          candleSeriesRef.current?.update(toBar(candle));
          volumeSeriesRef.current?.update(
            toVolumeBar(candle, cssVar('--color-ok'), cssVar('--color-err')),
          );
          recomputeIndicatorsRef.current();
          setTimeout(() => {
            if (!cancelled) bumpLines((t) => t + 1);
          }, 50);
        } catch (err) {
          // Defensive: lightweight-charts throws if a live update's time
          // is older than what's on the chart. Shouldn't happen once
          // gated by historyLoadedRef, but a dropped frame beats a crash.
          console.warn('chart: dropped out-of-order live update', err);
        }
      },
    );

    return () => {
      cancelled = true;
      if (overlayTimer) clearTimeout(overlayTimer);
      historyLoadedRef.current = false;
      chart
        ?.timeScale()
        .unsubscribeVisibleLogicalRangeChange(onVisibleRangeChange);
      unsubscribe();
    };
  }, [symbol, timeframe, backtestReportId, sessionReplayPeriod]);

  // Recompute overlays when the active strategy changes (activated,
  // deactivated, or a different one picked up for this symbol), when the user
  // adds/removes a manual indicator, or when the separators toggle changes —
  // without waiting for the next candle.
  useEffect(() => {
    recomputeIndicatorsRef.current();
  }, [activeStrategy, manualIndicators, showSeparators]);

  // Saved custom (backend-Python) indicators need an API round trip to
  // compute, unlike every other manual-indicator type, so they can't live
  // inside the synchronous recomputeIndicators above. Reassigned every
  // render so `computeCustomIndicatorsRef.current()` (called below, and
  // from the chart-creation effect's `render()`) always sees the latest
  // symbol/timeframe/manualIndicators.
  computeCustomIndicatorsRef.current = () => {
    const customInstances = manualIndicators.filter(
      (ind): ind is ManualIndicator & { indicatorId: string } =>
        ind.type === 'custom' && !!ind.indicatorId,
    );
    if (customInstances.length === 0) return;
    const periodParam = derivePeriodParam(candlesRef.current);
    if (!periodParam) return;

    Promise.all(
      customInstances.map(async (ind) => {
        try {
          const result = await computeIndicator(ind.indicatorId, {
            symbol,
            timeframe,
            period: periodParam,
          });
          return [ind.id, result] as const;
        } catch (err) {
          return [
            ind.id,
            {
              times: [],
              series: {},
              error: err instanceof Error ? err.message : 'compute failed',
            } as ComputeIndicatorResponse,
          ] as const;
        }
      }),
    ).then((entries) => {
      const presentIds = new Set(customInstances.map((ind) => ind.id));
      const next: Record<string, ComputeIndicatorResponse> = {};
      for (const [id, result] of entries) next[id] = result;
      // Keep results for instances still present that weren't in this
      // batch (shouldn't happen given the filter above, but avoids
      // silently dropping data if this is ever narrowed later).
      for (const [id, result] of Object.entries(customIndicatorResultsRef.current)) {
        if (presentIds.has(id) && !(id in next)) next[id] = result;
      }
      customIndicatorResultsRef.current = next;
      recomputeIndicatorsRef.current();
    });
  };

  // Add/remove a custom indicator, or switch symbol/timeframe, without
  // waiting for the next candle. The initial-history-load case (candles not
  // loaded yet on mount) is covered separately by `render()` inside the
  // chart-creation effect below.
  useEffect(() => {
    computeCustomIndicatorsRef.current();
  }, [manualIndicators, symbol, timeframe]);

  // When the symbol changes, save the current symbol's drawings and load the
  // new symbol's drawings. The chart-creation effect only handles the initial
  // symbol; this effect keeps things in sync on subsequent symbol switches.
  // Manual indicators follow the same per-symbol load convention.
  useEffect(() => {
    const manager = drawingManagerRef.current;
    if (!manager) return;
    isSwitchingSymbolRef.current = true;
    clearUserDrawings(manager);
    loadDrawingsFromStorage(manager, symbol);
    isSwitchingSymbolRef.current = false;
    setManualIndicators(loadManualIndicators(symbol));
  }, [symbol]); // eslint-disable-line react-hooks/exhaustive-deps

  // Interactive drawing placement.
  //
  // DrawingManager.setActiveTool() is a stub in v0.1.1 — its handleClick
  // does nothing when a tool is active. We implement the anchor-collection
  // workflow ourselves:
  //   1. Disable chart panning so mouse events reach our handler.
  //   2. Subscribe to chart.subscribeClick to collect price+time anchors.
  //   3. Once the required number of anchors is placed, instantiate the
  //      concrete Drawing subclass and hand it to the manager.
  //
  // Required anchor counts per tool:
  //   1 anchor : horizontal-line, vertical-line
  //   2 anchors: trend-line, extended-line, rectangle, fib-retracement
  //   3 anchors: parallel-channel
  useEffect(() => {
    const manager = drawingManagerRef.current;
    const chart = chartRef.current;
    const container = containerRef.current;
    if (!chart) return;

    if (!drawingTool) {
      chart.applyOptions({ handleScroll: true, handleScale: true });
      if (container) container.style.cursor = '';
      setPendingAnchorCount(0);
      return;
    }

    // Freeze chart interaction so clicks are not consumed as pans.
    chart.applyOptions({ handleScroll: false, handleScale: false });
    if (container) container.style.cursor = 'crosshair';

    const REQUIRED: Record<DrawingToolType, number> = REQUIRED_ANCHORS;

    const required = REQUIRED[drawingTool];
    // Mutable accumulator — not React state because we don't need a re-render
    // for each click, only when the drawing is complete.
    const pendingAnchors: Array<{ price: number; time: UTCTimestamp }> = [];

    const handleClick = (param: MouseEventParams) => {
      if (!param.point) return;
      const candleSeries = candleSeriesRef.current;
      if (!candleSeries || !manager) return;

      const time = chart.timeScale().coordinateToTime(param.point.x);
      const price = candleSeries.coordinateToPrice(param.point.y);
      if (time === null || price === null) return;

      pendingAnchors.push({ price, time: time as UTCTimestamp });
      setPendingAnchorCount(pendingAnchors.length);

      if (pendingAnchors.length < required) return; // wait for more clicks

      // All anchors collected — create and register the drawing.
      const id = `d-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
      const chosenColor = activeColorRef.current;
      const style = {
        lineColor: chosenColor,
        lineWidth: 2,
        showLabels: true,
        labelColor: chosenColor,
        fillColor: hexToRgba(chosenColor, 0.15),
      };

      let drawing: IDrawing | null = null;
      switch (drawingTool) {
        case 'trend-line':
          drawing = new TrendLine(id, pendingAnchors, style);
          break;
        case 'extended-line':
          drawing = new ExtendedLine(id, pendingAnchors, style);
          break;
        case 'horizontal-line':
          drawing = new HorizontalLine(id, pendingAnchors, style);
          break;
        case 'vertical-line':
          drawing = new VerticalLine(id, pendingAnchors, style);
          break;
        case 'rectangle':
          drawing = new Rectangle(id, pendingAnchors, style);
          break;
        case 'fib-retracement':
          drawing = new FibRetracement(id, pendingAnchors, style);
          break;
        case 'parallel-channel':
          drawing = new ParallelChannel(id, pendingAnchors, style);
          break;
      }

      if (drawing) manager.addDrawing(drawing);

      // Reset — the drawing:added listener (in the chart-creation effect)
      // handles saving + updating the list panel.
      setDrawingTool(null);
      setPendingAnchorCount(0);
    };

    chart.subscribeClick(handleClick);

    return () => {
      chart.unsubscribeClick(handleClick);
      chart.applyOptions({ handleScroll: true, handleScale: true });
      if (container) container.style.cursor = '';
      setPendingAnchorCount(0);
    };
  }, [drawingTool]);

  // Poll live spread for the header indicator.
  useEffect(() => {
    let cancelled = false;

    const poll = () => {
      getSymbolInfo(symbol)
        .then((info) => {
          if (!cancelled) setSpreadPoints(info.spread_points);
        })
        .catch(() => {
          if (!cancelled) setSpreadPoints(null);
        });
    };

    poll();
    const timer = setInterval(poll, SPREAD_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [symbol]);

  // Poll trade markers (F7): entry arrows + exit circles from the journal,
  // plus an entry->exit oblique line (LIVE_TRADE_DRAWING_PREFIX) for each
  // closed trade so a closed position stays visible on the chart instead of
  // just leaving behind a small circle. Skipped in backtest view — those
  // markers/lines come from the report's own trades (set below) instead of
  // the live journal.
  useEffect(() => {
    if (backtestReportId) return;
    const colors = {
      ok: cssVar('--color-ok'),
      err: cssVar('--color-err'),
    };
    const clearLiveTradeLines = () => {
      const manager = drawingManagerRef.current;
      if (!manager) return;
      for (const drawing of manager.getAllDrawings()) {
        if (drawing.id.startsWith(LIVE_TRADE_DRAWING_PREFIX)) {
          manager.removeDrawing(drawing.id);
        }
      }
    };
    if (customCodeResult) {
      seriesMarkersRef.current?.setMarkers(
        toCustomSignalsSeriesMarkers(customCodeResult.signals, colors),
      );
      clearLiveTradeLines();
      return;
    }
    let cancelled = false;

    const poll = () => {
      getTradeMarkers(symbol)
        .then((trades) => {
          if (cancelled) return;
          seriesMarkersRef.current?.setMarkers(toSeriesMarkers(trades, colors));
          clearLiveTradeLines();
          const manager = drawingManagerRef.current;
          if (manager) {
            for (const drawing of buildLiveTradeLineDrawings(
              trades,
              colors,
              candlesRef.current,
            )) {
              manager.addDrawing(drawing);
            }
          }
        })
        .catch(() => {
          // Journal unreachable — leave whatever markers/lines are already drawn.
        });
    };

    poll();
    const timer = setInterval(poll, MARKERS_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [symbol, backtestReportId, customCodeResult]);

  // Render the backtest report's trades as markers once fetched (see the
  // history-loading effect above, which sets `backtestTrades`), plus each
  // trade's zone rectangle and SL/TP segments (BACKTEST_DRAWING_PREFIX) —
  // cleared and rebuilt here on every report change rather than reusing
  // recomputeIndicators's cadence, since this only needs to run when the
  // report's trades actually change, not on every live candle tick.
  useEffect(() => {
    const manager = drawingManagerRef.current;
    function clearBacktestDrawings() {
      if (!manager) return;
      for (const drawing of manager.getAllDrawings()) {
        if (
          drawing.id.startsWith(BACKTEST_DRAWING_PREFIX) ||
          // Also clear any live-view closed-trade lines left over from
          // before switching into the backtest report.
          drawing.id.startsWith(LIVE_TRADE_DRAWING_PREFIX)
        ) {
          manager.removeDrawing(drawing.id);
        }
      }
    }
    if (!backtestReportId || backtestTrades === null) {
      clearBacktestDrawings();
      lastRevealedSignatureRef.current = null;
      return;
    }
    const colors = { ok: cssVar('--color-ok'), err: cssVar('--color-err') };
    // While replaying, only reveal what would have been visible at the
    // cursor bar's close — entry/setup at `open_time`, exit at `close_time`
    // — same "no lookahead" contract as `visibleCandles()`. Off (the
    // default), `cursorTime = Infinity` shows everything, unchanged from
    // before replay existed.
    const cursorTime = replayActive
      ? ((candlesRef.current[replayCursorIndex]?.time as number | undefined) ??
        0)
      : Infinity;
    if (customCodeResult) {
      seriesMarkersRef.current?.setMarkers(
        toCustomSignalsSeriesMarkers(customCodeResult.signals, colors).filter(
          (m) => (m.time as number) <= cursorTime,
        ),
      );
      clearBacktestDrawings();
      lastRevealedSignatureRef.current = null;
      return;
    }
    seriesMarkersRef.current?.setMarkers(
      toBacktestSeriesMarkers(backtestTrades, colors).filter(
        (m) => (m.time as number) <= cursorTime,
      ),
    );
    if (manager) {
      // Rebuilding every trade's zone/SL/TP/exit-line drawings is O(trades)
      // — cheap once, but this effect reruns on every replay cursor tick,
      // and most single-bar advances don't cross any trade's reveal
      // threshold. Skip the rebuild entirely when the revealed set hasn't
      // actually changed since the last run (tracked as an "open:close
      // count" signature) — a no-op tick shouldn't pay for a full rebuild.
      const openCount = backtestTrades.reduce(
        (n, t) => (t.open_time <= cursorTime ? n + 1 : n),
        0,
      );
      const closeCount = backtestTrades.reduce(
        (n, t) => (t.close_time <= cursorTime ? n + 1 : n),
        0,
      );
      const signature = `${openCount}:${closeCount}`;
      if (signature !== lastRevealedSignatureRef.current) {
        lastRevealedSignatureRef.current = signature;
        clearBacktestDrawings();
        const zoneColors = {
          demand: cssVar('--color-buy'),
          supply: cssVar('--color-sell'),
          sl: cssVar('--color-err'),
          tp: cssVar('--color-ok'),
        };
        backtestTrades.forEach((t, i) => {
          if (t.open_time > cursorTime) return;
          for (const drawing of buildTradeSetupDrawings(t, i, zoneColors)) {
            manager.addDrawing(drawing);
          }
          if (t.close_time <= cursorTime) {
            manager.addDrawing(
              buildExitLineDrawing(
                BACKTEST_DRAWING_PREFIX,
                String(i),
                t.open_time as UTCTimestamp,
                t.open_price,
                t.close_time as UTCTimestamp,
                t.close_price,
                t.profit,
                { ok: zoneColors.tp, err: zoneColors.sl },
              ),
            );
          }
        });
      }
    }
  }, [backtestReportId, backtestTrades, customCodeResult, replayActive, replayCursorIndex]);

  // News window shading (§8, F8): shade the pre/post-event window of any
  // active news window that affects this symbol. Pixel positions are
  // recomputed on every news poll, pan/zoom, and resize since they depend on
  // the chart's current visible time range, not just the window's own times.
  useEffect(() => {
    let cancelled = false;
    let currentWindows: NewsWindow[] = [];
    const chart = chartRef.current;
    const container = containerRef.current;

    function recompute() {
      if (!chart || !container) {
        setNewsBands([]);
        return;
      }
      const visible = chart.timeScale().getVisibleRange();
      if (!visible) {
        setNewsBands([]);
        return;
      }
      const from = visible.from as number;
      const to = visible.to as number;
      const bands: NewsBand[] = [];
      for (const w of currentWindows) {
        if (!w.symbols.includes(symbol)) continue;
        if (w.window_end < from || w.window_start > to) continue;
        const x1 = chart
          .timeScale()
          .timeToCoordinate(Math.max(from, w.window_start) as UTCTimestamp);
        const x2 = chart
          .timeScale()
          .timeToCoordinate(Math.min(to, w.window_end) as UTCTimestamp);
        if (x1 === null || x2 === null) continue;
        bands.push({
          key: `${w.event.name}-${w.window_start}`,
          left: Math.min(x1, x2),
          width: Math.max(1, Math.abs(x2 - x1)),
          label: w.event.name,
          phase: w.phase,
        });
      }
      setNewsBands(bands);
    }

    function pollNews() {
      getActiveNewsWindows()
        .then((windows) => {
          if (cancelled) return;
          currentWindows = windows;
          recompute();
        })
        .catch(() => {
          if (!cancelled) setNewsBands([]);
        });
    }

    pollNews();
    const timer = setInterval(pollNews, NEWS_POLL_MS);
    chart?.timeScale().subscribeVisibleTimeRangeChange(recompute);
    const resizeObserver = new ResizeObserver(recompute);
    if (container) resizeObserver.observe(container);

    return () => {
      cancelled = true;
      clearInterval(timer);
      chart?.timeScale().unsubscribeVisibleTimeRangeChange(recompute);
      resizeObserver.disconnect();
    };
  }, [symbol, timeframe]);

  // Click-to-trade: while `trading.placementMode` is armed (from the order
  // ticket), a chart click converts its y-coordinate to a price and hands it
  // to the ticket for confirmation — it never fires an order directly.
  useEffect(() => {
    const chart = chartRef.current;
    const series = candleSeriesRef.current;
    if (!chart || !series) return;
    const handler = (param: MouseEventParams) => {
      if (!param.point) return;
      const price = series.coordinateToPrice(param.point.y);
      if (price !== null) placeFromClickRef.current(price);
    };
    chart.subscribeClick(handler);
    return () => chart.unsubscribeClick(handler);
  }, []);

  // Draggable SL/TP/trigger-price lines: recompute pixel positions on
  // pan/zoom/resize (prices themselves come from `trading` polling, which
  // already triggers a re-render on its own).
  useEffect(() => {
    const chart = chartRef.current;
    const container = containerRef.current;
    if (!chart || !container) return;
    const bump = () => bumpLines((t) => t + 1);
    chart.timeScale().subscribeVisibleTimeRangeChange(bump);
    const resizeObserver = new ResizeObserver(bump);
    resizeObserver.observe(container);
    return () => {
      chart.timeScale().unsubscribeVisibleTimeRangeChange(bump);
      resizeObserver.disconnect();
    };
  }, [symbol, timeframe]);

  // Live mousemove/mouseup for whichever line (if any) is currently being
  // dragged — subscribed once; `dragRef` always holds the current target so
  // this doesn't need to resubscribe on every drag start/stop.
  useEffect(() => {
    function onMove(e: MouseEvent) {
      const current = dragRef.current;
      const container = containerRef.current;
      const series = candleSeriesRef.current;
      if (!current || !container || !series) return;
      const rect = container.getBoundingClientRect();
      const price = series.coordinateToPrice(e.clientY - rect.top);
      if (price !== null) setDrag({ ...current, price });
    }
    function onUp() {
      const current = dragRef.current;
      if (current) current.commit(current.price);
      setDrag(null);
    }
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, []);

  // Close context menu / popover on click outside
  useEffect(() => {
    if (
      !contextMenu &&
      !orderPopover &&
      !drawingContextMenu &&
      !drawingEditPopover
    )
      return;
    const handleMouseDownOutside = (e: MouseEvent) => {
      const menuEl = document.getElementById('chart-context-menu');
      const popoverEl = document.getElementById('chart-order-popover');
      const drawingMenuEl = document.getElementById('drawing-context-menu');
      const drawingPopoverEl = document.getElementById('drawing-edit-popover');
      if (
        (menuEl && menuEl.contains(e.target as Node)) ||
        (popoverEl && popoverEl.contains(e.target as Node)) ||
        (drawingMenuEl && drawingMenuEl.contains(e.target as Node)) ||
        (drawingPopoverEl && drawingPopoverEl.contains(e.target as Node))
      ) {
        return;
      }
      setContextMenu(null);
      setOrderPopover(null);
      setDrawingContextMenu(null);
      setDrawingEditPopover(null);
    };
    window.addEventListener('mousedown', handleMouseDownOutside);
    return () =>
      window.removeEventListener('mousedown', handleMouseDownOutside);
  }, [contextMenu, orderPopover, drawingContextMenu, drawingEditPopover]);

  // How many bars of context to start replay with instead of a single bar —
  // one candle against the still-full-range price scale renders as a
  // barely-visible sliver squashed to one edge until the next fit; starting
  // with real context avoids that and gives a sane first frame.
  const REPLAY_START_CONTEXT_BARS = 50;

  // Replay ("live session player", §F): the single place the cursor moves —
  // used by step forward/back, the scrubber, and the autoplay tick below.
  // Reads `candlesRef.current.length` live (not a captured snapshot) since
  // panning near the left edge during replay can still trigger `loadMore`
  // and grow the array.
  //
  // Keeps the cursor bar centered (history to its left, reserved empty space
  // to its right, like a currently-forming live bar) by setting an explicit
  // logical range every tick — not `scrollToPosition`, which anchors the
  // latest bar to the *right edge*, not the middle. `followCursorRef` is the
  // on/off switch: a manual drag/zoom (see the mousedown/wheel listener
  // below) turns it off so playback stops fighting the user's pan, and
  // `centerOn`'s width is *read from* the current visible range so it
  // preserves whatever zoom level the user left it at rather than resetting.
  function centerOn(index: number) {
    const chart = chartRef.current;
    if (!chart) return;
    const current = chart.timeScale().getVisibleLogicalRange();
    const width = current ? Math.max(10, current.to - current.from) : 2 * REPLAY_START_CONTEXT_BARS;
    chart.timeScale().setVisibleLogicalRange({
      from: index - width / 2,
      to: index + width / 2,
    });
  }

  function seekTo(index: number) {
    const total = candlesRef.current.length;
    if (total === 0) return;
    const clamped = Math.max(0, Math.min(index, total - 1));
    replayCursorIndexRef.current = clamped;
    setReplayCursorIndex(clamped);
    const chart = chartRef.current;
    // Not following: capture the user's current view before `render()`
    // touches the series data, and restore it exactly afterward — immune to
    // whatever `setData()` itself does to the visible range internally, so
    // a manual pan/zoom is never fought no matter how fast replay is ticking.
    const preservedRange = followCursorRef.current
      ? null
      : chart?.timeScale().getVisibleLogicalRange();
    renderRef.current();

    // Cancel any pending animation frame to prevent layout queue accumulation
    if (animationFrameRef.current !== null) {
      cancelAnimationFrame(animationFrameRef.current);
      animationFrameRef.current = null;
    }

    if (followCursorRef.current) {
      animationFrameRef.current = requestAnimationFrame(() => {
        animationFrameRef.current = null;
        if (followCursorRef.current) {
          centerOn(clamped);
        }
      });
    } else if (chart && preservedRange && !isMouseDownRef.current) {
      animationFrameRef.current = requestAnimationFrame(() => {
        animationFrameRef.current = null;
        if (!followCursorRef.current && !isMouseDownRef.current) {
          chart.timeScale().setVisibleLogicalRange(preservedRange);
        }
      });
    }
  }

  function handleEnterReplay() {
    const total = candlesRef.current.length;
    const startIndex = Math.min(REPLAY_START_CONTEXT_BARS, Math.max(0, total - 1));
    replayCursorIndexRef.current = startIndex;
    setReplayCursorIndex(startIndex);
    setReplayPlaying(false);
    replayActiveRef.current = true;
    setReplayActive(true);
    followCursorRef.current = true;
    setFollowingCursor(true);
    setShowActivityLogDock(true);
    renderRef.current();
    // Re-fit the price scale to the (now much smaller) revealed window
    // instead of leaving the full report's price range applied — otherwise
    // the first bars render as a squashed sliver at one edge of the old
    // range. Center the time axis on the cursor with a fixed initial
    // window (not `centerOn`, which would inherit the old full-report
    // width and start zoomed miles out).
    candleSeriesRef.current?.priceScale().applyOptions({ autoScale: true });
    
    // Cancel any pending animation frame
    if (animationFrameRef.current !== null) {
      cancelAnimationFrame(animationFrameRef.current);
      animationFrameRef.current = null;
    }
    animationFrameRef.current = requestAnimationFrame(() => {
      animationFrameRef.current = null;
      chartRef.current?.timeScale().setVisibleLogicalRange({
        from: startIndex - REPLAY_START_CONTEXT_BARS,
        to: startIndex + REPLAY_START_CONTEXT_BARS,
      });
    });
  }

  function handleExitReplay() {
    replayActiveRef.current = false;
    setReplayActive(false);
    setReplayPlaying(false);
    if (animationFrameRef.current !== null) {
      cancelAnimationFrame(animationFrameRef.current);
      animationFrameRef.current = null;
    }
    renderRef.current();
    candleSeriesRef.current?.priceScale().applyOptions({ autoScale: true });
    chartRef.current?.timeScale().fitContent();
  }

  // Starts session replay: validates the picker's current from/to inputs
  // (mirrors the picker's own disabled-Start-button guard, in case this ever
  // gets called some other way) and hands the parsed range to the
  // history-loading effect via `sessionReplayPeriod`, which fetches it
  // (chunked, if needed) and auto-enters replay once it lands.
  function handleStartSessionReplay() {
    if (
      sessionReplayFromSec === null ||
      sessionReplayToSec === null ||
      sessionReplayToSec <= sessionReplayFromSec ||
      !sessionReplayEstimate ||
      sessionReplayEstimate.level === 'block'
    ) {
      return;
    }
    setShowSessionReplayPicker(false);
    setSessionReplayPeriod({ from: sessionReplayFromSec, to: sessionReplayToSec });
  }

  // Leaves session replay entirely (not just pausing the player) — clearing
  // `sessionReplayPeriod` re-triggers the history-loading effect, which
  // reloads live "now" candles and resubscribes to WS updates.
  function handleExitSessionReplay() {
    handleExitReplay();
    setSessionReplayPeriod(null);
  }

  function handleRecenterReplay() {
    followCursorRef.current = true;
    setFollowingCursor(true);
    candleSeriesRef.current?.priceScale().applyOptions({ autoScale: true });
    if (animationFrameRef.current !== null) {
      cancelAnimationFrame(animationFrameRef.current);
      animationFrameRef.current = null;
    }
    animationFrameRef.current = requestAnimationFrame(() => {
      animationFrameRef.current = null;
      if (followCursorRef.current) {
        centerOn(replayCursorIndexRef.current);
      }
    });
  }

  // A manual drag, touch-pan, or wheel/scroll zoom means the user wants to
  // look at something other than the cursor bar — stop fighting it and
  // leave the view exactly where they left it across every subsequent tick,
  // until they explicitly re-engage via the "Center" button in
  // ReplayControls. Only active during replay; the live/static views never
  // had auto-follow to begin with.
  useEffect(() => {
    if (!replayActive) {
      isMouseDownRef.current = false;
      return;
    }
    const container = containerRef.current;
    if (!container) return;
    
    const disengage = () => {
      followCursorRef.current = false;
      setFollowingCursor(false);
      isMouseDownRef.current = true;
    };
    
    const handleMouseUp = () => {
      isMouseDownRef.current = false;
    };
    
    container.addEventListener('mousedown', disengage);
    container.addEventListener('touchstart', disengage, { passive: true });
    container.addEventListener('wheel', disengage, { passive: true });
    
    window.addEventListener('mouseup', handleMouseUp);
    window.addEventListener('touchend', handleMouseUp);
    
    return () => {
      container.removeEventListener('mousedown', disengage);
      container.removeEventListener('touchstart', disengage);
      container.removeEventListener('wheel', disengage);
      window.removeEventListener('mouseup', handleMouseUp);
      window.removeEventListener('touchend', handleMouseUp);
      if (animationFrameRef.current !== null) {
        cancelAnimationFrame(animationFrameRef.current);
        animationFrameRef.current = null;
      }
    };
  }, [replayActive]);

  // Autoplay: advances the cursor at an interval scaled by `replaySpeed`,
  // pausing once it reaches the last loaded bar. `render()` re-runs the full
  // indicator/structure/pattern recompute (and the trade-drawing effect
  // reruns on every cursor change too) — expensive enough over a few hundred
  // bars that firing it once per *bar* at high speed (e.g. every ~37ms at
  // 16x) visibly stutters. Ticks are floored at MIN_TICK_MS and the cursor
  // advances more bars per tick to compensate, capping how often the
  // expensive recompute actually runs regardless of the speed the user picks.
  useEffect(() => {
    if (!replayPlaying) return;
    const MIN_TICK_MS = 100;
    const rawIntervalMs = 600 / replaySpeed;
    const tickMs = Math.max(MIN_TICK_MS, rawIntervalMs);
    const barsPerTick = Math.max(1, Math.round(tickMs / rawIntervalMs));
    const id = setInterval(() => {
      const next = replayCursorIndexRef.current + barsPerTick;
      if (next >= candlesRef.current.length) {
        seekTo(candlesRef.current.length - 1);
        setReplayPlaying(false);
        return;
      }
      seekTo(next);
    }, tickMs);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [replayPlaying, replaySpeed]);

  const handleColorChange = (newColor: string) => {
    setActiveColor(newColor);

    // If a drawing is currently selected, update its style immediately
    const manager = drawingManagerRef.current;
    if (manager) {
      const selected = manager.getSelectedDrawing();
      if (selected) {
        if (originalStylesRef.current[selected.id]) {
          originalStylesRef.current[selected.id].lineColor = newColor;
          originalStylesRef.current[selected.id].labelColor = newColor;
          originalStylesRef.current[selected.id].fillColor = hexToRgba(
            newColor,
            0.15,
          );
        }

        selected.updateStyle({
          lineColor: newColor,
          labelColor: newColor,
          fillColor: hexToRgba(newColor, 0.25),
          lineWidth: 4,
        });

        saveAndSyncRef.current();
      }
    }
  };

  const handleModifyDrawingColor = (id: string, newColor: string) => {
    const manager = drawingManagerRef.current;
    if (manager) {
      const d = manager.getDrawing(id);
      if (d) {
        if (originalStylesRef.current[id]) {
          originalStylesRef.current[id].lineColor = newColor;
          originalStylesRef.current[id].labelColor = newColor;
          originalStylesRef.current[id].fillColor = hexToRgba(newColor, 0.15);

          d.updateStyle({
            lineColor: newColor,
            labelColor: newColor,
            fillColor: hexToRgba(newColor, 0.25),
            lineWidth: 4,
          });
        } else {
          d.updateStyle({
            lineColor: newColor,
            labelColor: newColor,
            fillColor: hexToRgba(newColor, 0.15),
          });
        }

        // If the modified drawing is the currently selected one, sync activeColor
        const selected = manager.getSelectedDrawing();
        if (selected && selected.id === id) {
          setActiveColor(newColor);
        }

        saveAndSyncRef.current();
      }
    }
  };

  function buildPriceLines(): PriceLineSpec[] {
    const okColor = cssVar('--color-ok');
    const errColor = cssVar('--color-err');
    const accentColor = cssVar('--color-accent');
    const specs: PriceLineSpec[] = [];
    for (const p of trading.positions) {
      const offset = defaultOffset(p.open_price);
      const direction = p.side === 'buy' ? 1 : -1;
      if (p.sl !== null) {
        specs.push({
          key: `pos-${p.ticket}-sl`,
          price: p.sl,
          color: errColor,
          label: `SL ${p.sl}`,
          commit: (np) => trading.modifyPositionSlTp(p.ticket, np, p.tp),
        });
      } else {
        specs.push({
          key: `pos-${p.ticket}-sl`,
          price: p.open_price - direction * offset,
          color: errColor,
          label: '+ SL',
          placeholder: true,
          commit: (np) => trading.modifyPositionSlTp(p.ticket, np, p.tp),
        });
      }
      if (p.tp !== null) {
        specs.push({
          key: `pos-${p.ticket}-tp`,
          price: p.tp,
          color: okColor,
          label: `TP ${p.tp}`,
          commit: (np) => trading.modifyPositionSlTp(p.ticket, p.sl, np),
        });
      } else {
        specs.push({
          key: `pos-${p.ticket}-tp`,
          price: p.open_price + direction * offset,
          color: okColor,
          label: '+ TP',
          placeholder: true,
          commit: (np) => trading.modifyPositionSlTp(p.ticket, p.sl, np),
        });
      }
    }
    for (const o of trading.pendingOrders) {
      const offset = defaultOffset(o.price);
      const direction = o.side === 'buy' ? 1 : -1;
      specs.push({
        key: `pend-${o.ticket}-price`,
        price: o.price,
        color: accentColor,
        label: `${o.side} ${o.order_type} ${o.price}`,
        commit: (np) => trading.modifyPending(o.ticket, np, o.sl, o.tp),
      });
      if (o.sl !== null) {
        specs.push({
          key: `pend-${o.ticket}-sl`,
          price: o.sl,
          color: errColor,
          label: `SL ${o.sl}`,
          commit: (np) => trading.modifyPending(o.ticket, null, np, o.tp),
        });
      } else {
        specs.push({
          key: `pend-${o.ticket}-sl`,
          price: o.price - direction * offset,
          color: errColor,
          label: '+ SL',
          placeholder: true,
          commit: (np) => trading.modifyPending(o.ticket, null, np, o.tp),
        });
      }
      if (o.tp !== null) {
        specs.push({
          key: `pend-${o.ticket}-tp`,
          price: o.tp,
          color: okColor,
          label: `TP ${o.tp}`,
          commit: (np) => trading.modifyPending(o.ticket, null, o.sl, np),
        });
      } else {
        specs.push({
          key: `pend-${o.ticket}-tp`,
          price: o.price + direction * offset,
          color: okColor,
          label: '+ TP',
          placeholder: true,
          commit: (np) => trading.modifyPending(o.ticket, null, o.sl, np),
        });
      }
    }
    return specs;
  }

  // One dashed line per running position at its entry (open) price — separate
  // from the SL/TP lines above so it reads as "this is where the trade is
  // running from", not a modifiable trigger. Color is by side (buy/sell), not
  // ok/err, since those are already reserved for TP/SL regardless of side.
  function buildEntryLines(): EntryLineSpec[] {
    const buyColor = cssVar('--color-buy');
    const sellColor = cssVar('--color-sell');
    return trading.positions.map((p) => ({
      key: `entry-${p.ticket}`,
      position: p,
      color: p.side === 'buy' ? buyColor : sellColor,
      label: `${p.side.toUpperCase()} ${p.volume} @ ${p.open_price}`,
    }));
  }

  async function handleSaveEdit(
    ticket: number,
    sl: number | null,
    tp: number | null,
  ) {
    setEditBusy(true);
    try {
      await trading.modifyPositionSlTp(ticket, sl, tp);
      setEditingTicket(null);
    } finally {
      setEditBusy(false);
    }
  }

  async function handleCloseFromEdit(ticket: number) {
    if (!window.confirm(`Close position #${ticket}?`)) return;
    setEditBusy(true);
    try {
      await trading.close(ticket);
      setEditingTicket(null);
    } finally {
      setEditBusy(false);
    }
  }

  function handleAddManualIndicator(indicator: ManualIndicator) {
    setManualIndicators((prev) => {
      const next = [...prev, indicator];
      saveManualIndicators(symbolRef.current, next);
      return next;
    });
  }

  function handleRemoveManualIndicator(id: string) {
    setManualIndicators((prev) => {
      const next = prev.filter((ind) => ind.id !== id);
      saveManualIndicators(symbolRef.current, next);
      return next;
    });
  }
  async function runCustomCode(codeOverride?: string) {
    const code = codeOverride ?? customCodeDraft;
    if (!code) return;
    setCustomCodeBusy(true);
    setCustomCodeError(null);
    try {
      const periodParam = derivePeriodParam(candlesRef.current);
      if (!periodParam) {
        throw new Error('No historical candles loaded on the chart yet.');
      }

      const res = await evaluateCustomCode({
        code,
        symbol,
        timeframe,
        period: periodParam,
      });

      if (res.error) {
        setCustomCodeError(res.error);
      } else {
        setCustomCodeResult(res);
        customCodeResultRef.current = res;
        recomputeIndicatorsRef.current();
      }
    } catch (err) {
      setCustomCodeError(
        err instanceof Error ? err.message : 'Execution failed',
      );
    } finally {
      setCustomCodeBusy(false);
    }
  }

  function clearCustomCode() {
    setCustomCodeResult(null);
    customCodeResultRef.current = null;
    setCustomCodeError(null);
    recomputeIndicatorsRef.current();
  }
  return (
    <section className='flex min-h-0 flex-1 flex-col rounded-md border border-line bg-panel'>
      <header className='flex items-center gap-3 border-b border-line px-4 py-2'>
        <strong>{symbol}</strong>
        <nav className='flex gap-1'>
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf}
              className={`cursor-pointer rounded border px-2 py-0.5 text-xs ${
                tf === timeframe
                  ? 'border-accent text-accent'
                  : 'border-line text-ink-muted'
              }`}
              onClick={() => setTimeframe(tf)}
            >
              {tf}
            </button>
          ))}
        </nav>
        <div className='flex gap-1'>
          <button
            className='cursor-pointer rounded border border-line px-2 py-0.5 text-xs text-ink-muted'
            onClick={() => chartRef.current?.timeScale().scrollToRealTime()}
          >
            Latest
          </button>
          <button
            className='cursor-pointer rounded border border-line px-2 py-0.5 text-xs text-ink-muted'
            onClick={() => chartRef.current?.timeScale().resetTimeScale()}
          >
            Reset zoom
          </button>
        </div>
        {/* Custom Script Code Editor toggle */}
        <button
          className={`cursor-pointer rounded border px-2 py-0.5 text-xs ${
            showCustomCodeEditor
              ? 'border-accent text-accent'
              : 'border-line text-ink-muted'
          }`}
          onClick={() => {
            setShowCustomCodeEditor((v) => !v);
            setShowStrategyEditor(false); // Close strategy editor if custom is opened
          }}
          title='Write custom script and run directly on chart'
        >
          Code Editor
        </button>
        {/* Drawings list toggle + placement hint */}
        <button
          className={`cursor-pointer rounded border px-2 py-0.5 text-xs ${
            showDrawingsList
              ? 'border-accent text-accent'
              : 'border-line text-ink-muted'
          }`}
          onClick={() => setShowDrawingsList((v) => !v)}
          title='Show / hide drawings list'
        >
          Drawings {drawingsList.length > 0 && `(${drawingsList.length})`}
        </button>
        {/* Manual indicators dock toggle */}
        <button
          className={`cursor-pointer rounded border px-2 py-0.5 text-xs ${
            showIndicatorsDock
              ? 'border-accent text-accent'
              : 'border-line text-ink-muted'
          }`}
          onClick={() => setShowIndicatorsDock((v) => !v)}
          title='Add / remove indicators'
        >
          Indicators{' '}
          {manualIndicators.length > 0 && `(${manualIndicators.length})`}
        </button>
        {/* Activity log dock toggle — signals/vetoes/fills for this symbol */}
        <button
          className={`cursor-pointer rounded border px-2 py-0.5 text-xs ${
            showActivityLogDock
              ? 'border-accent text-accent'
              : 'border-line text-ink-muted'
          }`}
          onClick={() => setShowActivityLogDock((v) => !v)}
          title='See what the bot is doing on this symbol and why'
        >
          Activity log
        </button>
        {/* Period separators toggle */}
        <button
          className={`cursor-pointer rounded border px-2 py-0.5 text-xs ${
            showSeparators
              ? 'border-accent text-accent'
              : 'border-line text-ink-muted'
          }`}
          onClick={() => {
            const next = !showSeparators;
            setShowSeparators(next);
            try {
              localStorage.setItem('chart-show-separators', String(next));
            } catch {}
          }}
          title='Show / hide day/period separators'
        >
          Separators
        </button>
        {/* Session replay: pick an arbitrary historical period and replay it
            bar-by-bar, like a live session — independent of backtest reports,
            so it's hidden while already viewing one (which has its own
            Replay button above). */}
        {!backtestReportId && (
          <button
            className={`flex cursor-pointer items-center gap-1 rounded border px-2 py-0.5 text-xs ${
              sessionReplayPeriod
                ? 'border-accent bg-accent/20 text-accent'
                : showSessionReplayPicker
                  ? 'border-accent text-accent'
                  : 'border-line text-ink-muted hover:border-accent hover:text-accent'
            }`}
            onClick={() => {
              if (sessionReplayPeriod) {
                handleExitSessionReplay();
              } else {
                setShowSessionReplayPicker((v) => !v);
              }
            }}
            title="Replay an arbitrary historical period bar-by-bar, like a live session"
          >
            {sessionReplayPeriod ? (
              <>
                <Square size={12} fill="currentColor" /> Exit session replay
              </>
            ) : (
              <>
                <History size={12} /> Session replay
              </>
            )}
          </button>
        )}
        <span className='ml-auto text-xs text-ink-muted'>
          {drawingTool && pendingAnchorCount > 0 && (
            <span className='mr-3 text-accent'>
              Click {REQUIRED_ANCHORS[drawingTool] - pendingAnchorCount} more
              point
              {REQUIRED_ANCHORS[drawingTool] - pendingAnchorCount !== 1
                ? 's'
                : ''}
            </span>
          )}
          spread: {spreadPoints === null ? '—' : `${spreadPoints} pts`}
        </span>
      </header>
      {error && <p className='px-4 py-1 text-xs text-err'>{error}</p>}
      {showSessionReplayPicker && !sessionReplayPeriod && (
        <SessionReplayPicker
          fromValue={sessionReplayFromInput}
          toValue={sessionReplayToInput}
          onFromChange={setSessionReplayFromInput}
          onToChange={setSessionReplayToInput}
          estimate={sessionReplayEstimate}
          onCancel={() => setShowSessionReplayPicker(false)}
          onStart={handleStartSessionReplay}
        />
      )}
      {sessionReplayPeriod && (
        <div className='flex items-center gap-2 border-b border-line bg-accent/10 px-4 py-1 text-xs text-accent'>
          <span>
            Session replay —{' '}
            {new Date(sessionReplayPeriod.from * 1000)
              .toISOString()
              .replace('T', ' ')
              .slice(0, 16)}{' '}
            →{' '}
            {new Date(sessionReplayPeriod.to * 1000)
              .toISOString()
              .replace('T', ' ')
              .slice(0, 16)}
            {sessionReplayLoadingPage &&
              ` — loading… page ${sessionReplayLoadingPage.page} (${sessionReplayLoadingPage.loaded.toLocaleString()} candles so far)`}
          </span>
        </div>
      )}
      {backtestReportId && (
        <div className='flex items-center gap-2 border-b border-line bg-accent/10 px-4 py-1 text-xs text-accent'>
          <span>
            Backtest view
            {backtestTrades !== null &&
              ` — ${backtestTrades.length} trade${backtestTrades.length === 1 ? '' : 's'}`}
            {backtestError && ` — ${backtestError}`}
          </span>
          <Link
            href={`/backtest/${encodeURIComponent(backtestReportId)}`}
            className='rounded border border-accent px-2 py-0.5 text-accent hover:bg-accent/20'
          >
            ← Back to report
          </Link>
          {backtestMeta && (
            <button
              className={`cursor-pointer rounded border px-2 py-0.5 ${
                showStrategyEditor
                  ? 'border-accent bg-accent/20 text-accent'
                  : 'border-accent text-accent hover:bg-accent/20'
              }`}
              onClick={() => setShowStrategyEditor((v) => !v)}
              title="Edit this strategy's source code and re-run the backtest in place"
            >
              {showStrategyEditor ? 'Hide code' : 'Edit code'}
            </button>
          )}
          <button
            className={`flex cursor-pointer items-center gap-1 rounded border px-2 py-0.5 ${
              replayActive
                ? 'border-accent bg-accent/20 text-accent'
                : 'border-accent text-accent hover:bg-accent/20'
            }`}
            onClick={replayActive ? handleExitReplay : handleEnterReplay}
            title="Watch this backtest unfold bar by bar — candles, indicators, trades and the activity log revealed progressively, like a live session"
          >
            {replayActive ? (
              <>
                <Square size={12} fill="currentColor" /> Exit replay
              </>
            ) : (
              <>
                <Play size={12} fill="currentColor" /> Replay
              </>
            )}
          </button>
          {onExitBacktestView && (
            <button
              className='ml-auto cursor-pointer rounded border border-accent px-2 py-0.5 text-accent hover:bg-accent/20'
              onClick={onExitBacktestView}
            >
              Exit backtest view
            </button>
          )}
        </div>
      )}
      {/* Replay player — shown while replaying a backtest report (§F) or a
          session-replay period */}
      {(backtestReportId || sessionReplayPeriod) && replayActive && (
        <ReplayControls
          playing={replayPlaying}
          onPlayPause={() => setReplayPlaying((p) => !p)}
          onStepBack={() => {
            setReplayPlaying(false);
            seekTo(replayCursorIndexRef.current - 1);
          }}
          onStepForward={() => {
            setReplayPlaying(false);
            seekTo(replayCursorIndexRef.current + 1);
          }}
          speed={replaySpeed}
          onSpeedChange={setReplaySpeed}
          cursorIndex={replayCursorIndex}
          totalBars={candlesRef.current.length}
          currentTime={
            candlesRef.current[replayCursorIndex]
              ? new Date(candlesRef.current[replayCursorIndex].time * 1000)
                  .toISOString()
                  .replace('T', ' ')
                  .slice(0, 19)
              : '—'
          }
          onSeek={(index) => {
            setReplayPlaying(false);
            seekTo(index);
          }}
          following={followingCursor}
          onRecenter={handleRecenterReplay}
        />
      )}
      {/* Strategy info — collapsed by default, shows only name + toggle */}
      {activeStrategy?.spec &&
        (activeStrategy.spec.unrecognized_indicators.length > 0 ||
          activeStrategy.spec.chart_notes.length > 0) && (
          <div className='flex flex-col border-b border-line text-xs'>
            <div className='flex items-center gap-2 px-4 py-1'>
              <span className='font-semibold text-ink'>
                {activeStrategy.name}
              </span>
              <span className='text-ink-muted/70 text-[10px]'>
                {activeStrategy.spec.unrecognized_indicators.length +
                  activeStrategy.spec.chart_notes.length}{' '}
                item(s) not auto-drawn
              </span>
              <button
                onClick={() => setStrategyInfoExpanded((v) => !v)}
                className='ml-auto cursor-pointer rounded border border-line px-2 py-0.5 text-[10px] text-ink-muted hover:border-accent hover:text-accent transition-colors'
                title={
                  strategyInfoExpanded
                    ? 'Collapse strategy info'
                    : 'Expand strategy info'
                }
              >
                {strategyInfoExpanded ? '▲ Hide info' : '▼ Show info'}
              </button>
            </div>
            {strategyInfoExpanded && (
              <div className='flex flex-wrap items-center gap-1.5 border-t border-line px-4 py-1.5 text-ink-muted bg-panel/50'>
                <span className='text-ink-muted/70 mr-1'>
                  Mentions (not auto-drawn):
                </span>
                {activeStrategy.spec.unrecognized_indicators.map((name) => (
                  <span
                    key={`ind:${name}`}
                    className='rounded border border-line px-1.5 py-0.5 bg-panel'
                    title='Indicator outside the 5 plottable families (EMA/SMA/RSI/MACD/Bollinger)'
                  >
                    {name}
                  </span>
                ))}
                {activeStrategy.spec.chart_notes.map((note) => (
                  <span
                    key={`note:${note}`}
                    className='rounded border border-line px-1.5 py-0.5 bg-panel'
                    title='No explicit price level in the source document — not turned into chart geometry'
                  >
                    {note}
                  </span>
                ))}
              </div>
            )}
          </div>
        )}
      {/* Drawings list panel — shown when the toggle is active */}
      {showDrawingsList && (
        <DrawingsList
          drawings={drawingsList}
          onRemove={(id) => drawingManagerRef.current?.removeDrawing(id)}
          onToggleVisible={(id) => {
            const d = drawingManagerRef.current?.getDrawing(id);
            if (d) {
              d.updateOptions({ visible: !d.options.visible });
              const manager = drawingManagerRef.current;
              if (manager) {
                try {
                  const data = manager.exportDrawings();
                  localStorage.setItem(
                    `chart-drawings:${symbolRef.current}`,
                    JSON.stringify(data),
                  );
                } catch {}
                setDrawingsList(manager.getAllDrawings());
              }
            }
          }}
          onColorChange={handleModifyDrawingColor}
        />
      )}
      {/* Indicators dock — shown when the toggle is active */}
      {showIndicatorsDock && (
        <IndicatorsDock
          indicators={manualIndicators}
          onAdd={handleAddManualIndicator}
          onRemove={handleRemoveManualIndicator}
          onCustomIndicatorCodeSaved={() => computeCustomIndicatorsRef.current()}
        />
      )}
      {/* Activity log dock — shown when the toggle is active. During replay,
          feeds the backtest report's own activity log (its persisted trail
          of signals/vetoes/fills, simulated-clock timestamps) filtered up
          to the cursor bar, instead of the default live/global poll. */}
      {showActivityLogDock && (
        <ActivityLogDock
          symbol={symbol}
          replayEntries={
            replayActive && backtestActivityLog
              ? backtestActivityLog
                  .filter(
                    (e) =>
                      e.time <=
                      ((candlesRef.current[replayCursorIndex]?.time as
                        | number
                        | undefined) ?? 0),
                  )
                  .map((e, i) => ({
                    id: i,
                    created_at: e.time,
                    level: e.level,
                    logger: e.logger,
                    message: e.message,
                  }))
              : undefined
          }
        />
      )}
      <div className='relative min-h-0 flex-1'>
        <div ref={containerRef} className='h-full w-full' />
        {/* Strategy code drawer — slides in from the configured edge */}
        {backtestReportId && backtestMeta && showStrategyEditor && (
          <div
            className={`pointer-events-auto absolute z-40 flex flex-col bg-panel border-line shadow-2xl overflow-hidden ${
              drawerPosition === 'right'
                ? 'right-0 top-0 h-full border-l'
                : drawerPosition === 'left'
                  ? 'left-0 top-0 h-full border-r'
                  : drawerPosition === 'bottom'
                    ? 'bottom-0 left-0 w-full border-t'
                    : 'top-0 left-0 w-full border-b'
            }`}
            style={{
              width:
                drawerPosition === 'right' || drawerPosition === 'left'
                  ? '420px'
                  : '100%',
              height:
                drawerPosition === 'bottom' || drawerPosition === 'top'
                  ? '340px'
                  : '100%',
              maxWidth:
                drawerPosition === 'right' || drawerPosition === 'left'
                  ? '55%'
                  : undefined,
              maxHeight:
                drawerPosition === 'bottom' || drawerPosition === 'top'
                  ? '55%'
                  : undefined,
            }}
          >
            {/* Drawer header */}
            <div className='flex items-center gap-2 border-b border-line px-3 py-1.5 bg-panel shrink-0'>
              <span className='text-xs font-semibold text-ink truncate'>
                Edit Strategy Code
              </span>
              {/* Position controls */}
              <div className='flex items-center gap-0.5 ml-auto'>
                {(['right', 'bottom', 'left', 'top'] as const).map((pos) => (
                  <button
                    key={pos}
                    onClick={() => setDrawerPosition(pos)}
                    title={`Move to ${pos}`}
                    className={`cursor-pointer rounded px-1.5 py-0.5 text-[10px] border transition-colors ${
                      drawerPosition === pos
                        ? 'border-accent text-accent bg-accent/10'
                        : 'border-line text-ink-muted hover:text-ink'
                    }`}
                  >
                    {pos === 'right'
                      ? '⇥'
                      : pos === 'left'
                        ? '⇤'
                        : pos === 'bottom'
                          ? '⇓'
                          : '⇑'}
                  </button>
                ))}
                <button
                  onClick={() => setShowStrategyEditor(false)}
                  className='cursor-pointer ml-1 rounded border border-line px-1.5 py-0.5 text-[10px] text-ink-muted hover:border-err hover:text-err transition-colors'
                  title='Close drawer'
                >
                  ✕
                </button>
              </div>
            </div>
            {/* Drawer content */}
            <div className='flex-1 flex flex-col p-2 min-h-0'>
              <BacktestStrategyEditor
                strategyName={backtestMeta.strategy}
                symbol={backtestMeta.symbol}
                period={backtestMeta.period}
                className='flex-1 min-h-0'
                onSaved={(newReportId) => {
                  setShowStrategyEditor(false);
                  onReportChange?.(newReportId);
                }}
                onRunPreview={runCustomCode}
                previewBusy={customCodeBusy}
                previewError={customCodeError}
                previewResult={customCodeResult}
                onResetPreview={clearCustomCode}
              />
            </div>
          </div>
        )}
        {/* Custom script code drawer — slides in from the configured edge */}
        {showCustomCodeEditor && (
          <div
            className={`pointer-events-auto absolute z-40 flex flex-col bg-panel border-line shadow-2xl overflow-hidden ${
              drawerPosition === 'right'
                ? 'right-0 top-0 h-full border-l'
                : drawerPosition === 'left'
                  ? 'left-0 top-0 h-full border-r'
                  : drawerPosition === 'bottom'
                    ? 'bottom-0 left-0 w-full border-t'
                    : 'top-0 left-0 w-full border-b'
            }`}
            style={{
              width:
                drawerPosition === 'right' || drawerPosition === 'left'
                  ? '420px'
                  : '100%',
              height:
                drawerPosition === 'bottom' || drawerPosition === 'top'
                  ? '340px'
                  : '100%',
              maxWidth:
                drawerPosition === 'right' || drawerPosition === 'left'
                  ? '55%'
                  : undefined,
              maxHeight:
                drawerPosition === 'bottom' || drawerPosition === 'top'
                  ? '55%'
                  : undefined,
            }}
          >
            {/* Drawer header */}
            <div className='flex items-center gap-2 border-b border-line px-3 py-1.5 bg-panel shrink-0'>
              <span className='text-xs font-semibold text-ink truncate'>
                Run Custom Code
              </span>
              {/* Position controls */}
              <div className='flex items-center gap-0.5 ml-auto'>
                <button
                  onClick={handleCopyCustomCode}
                  className={`cursor-pointer mr-1.5 rounded px-2 py-0.5 text-[10px] border transition-colors ${
                    customCodeCopied
                      ? 'border-ok text-ok bg-ok/10'
                      : 'border-line text-ink-muted hover:text-accent hover:border-accent'
                  }`}
                  title='Copy code'
                >
                  {customCodeCopied ? 'Copied!' : 'Copy'}
                </button>
                {(['right', 'bottom', 'left', 'top'] as const).map((pos) => (
                  <button
                    key={pos}
                    onClick={() => setDrawerPosition(pos)}
                    title={`Move to ${pos}`}
                    className={`cursor-pointer rounded px-1.5 py-0.5 text-[10px] border transition-colors ${
                      drawerPosition === pos
                        ? 'border-accent text-accent bg-accent/10'
                        : 'border-line text-ink-muted hover:text-ink'
                    }`}
                  >
                    {pos === 'right'
                      ? '⇥'
                      : pos === 'left'
                        ? '⇤'
                        : pos === 'bottom'
                          ? '⇓'
                          : '⇑'}
                  </button>
                ))}
                <button
                  onClick={() => {
                    setShowCustomCodeEditor(false);
                    clearCustomCode();
                  }}
                  className='cursor-pointer ml-1 rounded border border-line px-1.5 py-0.5 text-[10px] text-ink-muted hover:border-err hover:text-err transition-colors'
                  title='Close drawer'
                >
                  ✕
                </button>
              </div>
            </div>
            {/* Drawer content */}
            <div className='flex-1 flex flex-col p-2 min-h-0'>
              <div className='flex-1 flex flex-col min-h-0 rounded-md border border-line bg-panel'>
                <CodeMirror
                  value={customCodeDraft}
                  height='100%'
                  className='flex-1 min-h-0 overflow-auto'
                  theme={cmTheme}
                  extensions={[python()]}
                  onChange={setCustomCodeDraft}
                  editable={!customCodeBusy}
                />

                {customCodeError && (
                  <div className='border-t border-line px-3 py-2 text-xs text-err shrink-0 max-h-32 overflow-y-auto'>
                    <p>{customCodeError}</p>
                  </div>
                )}

                {customCodeResult && (
                  <div className='border-t border-line px-3 py-1.5 text-xs text-ok shrink-0 bg-panel/30 flex items-center justify-between'>
                    <span>
                      Success: {customCodeResult.signals.length} signal(s),{' '}
                      {Object.keys(customCodeResult.indicators).length}{' '}
                      indicator(s) calculated
                    </span>
                    <button
                      onClick={clearCustomCode}
                      className='cursor-pointer px-1.5 py-0.5 rounded border border-line hover:border-ink hover:text-ink text-[10px] text-ink-muted'
                    >
                      Reset Graph
                    </button>
                  </div>
                )}

                <div className='flex items-center gap-2 border-t border-line p-3 shrink-0'>
                  <button
                    type='button'
                    className='cursor-pointer rounded border border-accent px-3 py-1 text-xs text-accent hover:bg-accent hover:text-bg disabled:cursor-not-allowed disabled:opacity-50'
                    disabled={customCodeBusy}
                    onClick={() => runCustomCode()}
                  >
                    {customCodeBusy ? 'Running code...' : 'Run & Show on Graph'}
                  </button>
                  <span className='text-[10px] text-ink-muted'>
                    Evaluates custom Python strategy. Returns moving
                    averages/indicators & buy/sell signals on graph.
                  </span>
                </div>
              </div>
            </div>
          </div>
        )}
        {/* Drawing toolbar — floats on the left edge of the chart canvas */}
        <DrawingToolbar
          activeTool={drawingTool}
          onToolSelect={setDrawingTool}
          onClearAll={() => {
            const manager = drawingManagerRef.current;
            if (manager) clearUserDrawings(manager);
          }}
          activeColor={activeColor}
          onColorChange={handleColorChange}
        />
        {contextMenu && (
          <ChartContextMenu
            x={contextMenu.x}
            y={contextMenu.y}
            price={contextMenu.price}
            containerWidth={contextMenu.containerWidth}
            containerHeight={contextMenu.containerHeight}
            onSelectOption={(side, type) => {
              setOrderPopover({
                x: contextMenu.x,
                y: contextMenu.y,
                price: contextMenu.price,
                side,
                orderType: type,
                containerWidth: contextMenu.containerWidth,
                containerHeight: contextMenu.containerHeight,
              });
              setContextMenu(null);
            }}
          />
        )}
        {orderPopover && (
          <ChartOrderPopover
            x={orderPopover.x}
            y={orderPopover.y}
            price={orderPopover.price}
            side={orderPopover.side}
            orderType={orderPopover.orderType}
            containerWidth={orderPopover.containerWidth}
            containerHeight={orderPopover.containerHeight}
            busy={editBusy}
            onClose={() => setOrderPopover(null)}
            onPlace={async (volume, price, sl, tp) => {
              await trading.placePending(
                orderPopover.side,
                orderPopover.orderType,
                volume,
                price,
                sl,
                tp,
              );
            }}
          />
        )}
        {drawingContextMenu && (
          <DrawingContextMenu
            x={drawingContextMenu.x}
            y={drawingContextMenu.y}
            drawingType={drawingContextMenu.drawingType}
            containerWidth={drawingContextMenu.containerWidth}
            containerHeight={drawingContextMenu.containerHeight}
            onSelectEdit={() => {
              setDrawingEditPopover({
                x: drawingContextMenu.x,
                y: drawingContextMenu.y,
                drawingId: drawingContextMenu.drawingId,
                drawingType: drawingContextMenu.drawingType,
                containerWidth: drawingContextMenu.containerWidth,
                containerHeight: drawingContextMenu.containerHeight,
              });
              setDrawingContextMenu(null);
            }}
            onDelete={() => {
              drawingManagerRef.current?.removeDrawing(
                drawingContextMenu.drawingId,
              );
              setDrawingContextMenu(null);
            }}
          />
        )}
        {drawingEditPopover && (
          <DrawingEditPopover
            x={drawingEditPopover.x}
            y={drawingEditPopover.y}
            drawingId={drawingEditPopover.drawingId}
            drawingType={drawingEditPopover.drawingType}
            containerWidth={drawingEditPopover.containerWidth}
            containerHeight={drawingEditPopover.containerHeight}
            manager={drawingManagerRef.current}
            originalStylesRef={originalStylesRef}
            onClose={() => setDrawingEditPopover(null)}
            onSaveAndSync={saveAndSyncRef.current}
            onColorChange={handleModifyDrawingColor}
          />
        )}
        {newsBands.map((b) => {
          const color = cssVar(
            b.phase === 'pre' ? '--color-err' : '--color-accent',
          );
          return (
            <div
              key={b.key}
              className='pointer-events-none absolute top-0 h-full border-x border-dashed'
              style={{
                left: b.left,
                width: b.width,
                backgroundColor: hexToRgba(color, 0.1),
                borderColor: color,
              }}
              title={`${b.label} (${b.phase}-event news window)`}
            />
          );
        })}
        {loadingMore && (
          <div className='pointer-events-none absolute left-2 top-2 rounded border border-line bg-panel px-2 py-1 text-xs text-ink-muted'>
            Loading history…
          </div>
        )}
        {buildPriceLines().map((spec) => {
          const dragging = drag?.key === spec.key;
          const price = dragging ? drag.price : spec.price;
          const top = candleSeriesRef.current?.priceToCoordinate(price);
          if (top === null || top === undefined) return null;
          // Placeholders (no sl/tp set yet) render faint until dragged/clicked
          // — once that happens `dragging` takes over the "live" style so the
          // user gets feedback that it's now a real, about-to-commit value.
          const faint = spec.placeholder && !dragging;
          return (
            <div
              key={spec.key}
              className='pointer-events-auto absolute left-0 right-0 h-4 -translate-y-1/2 cursor-ns-resize z-10 flex items-center select-none'
              style={{
                top: `${top}px`,
                opacity: faint ? 0.45 : 1,
              }}
              onMouseDown={(e) => {
                e.preventDefault();
                setDrag({
                  key: spec.key,
                  price: spec.price,
                  commit: spec.commit,
                });
              }}
            >
              <div
                className='w-full border-t border-dashed'
                style={{ borderColor: spec.color }}
              />
              <div
                className='absolute right-2 top-1/2 -translate-y-1/2 rounded px-1 text-[10px] font-bold'
                style={{
                  backgroundColor: spec.color,
                  color: '#04211e',
                  opacity: faint ? 0.7 : 1,
                }}
                title={
                  spec.placeholder
                    ? 'Drag to set — not saved yet'
                    : 'Drag to modify'
                }
              >
                {dragging ? price.toFixed(5) : spec.label}
              </div>
            </div>
          );
        })}
        {buildEntryLines().map((spec) => {
          const top = candleSeriesRef.current?.priceToCoordinate(
            spec.position.open_price,
          );
          if (top === null || top === undefined) return null;
          return (
            <div
              key={spec.key}
              className='pointer-events-auto absolute left-0 right-0 h-4 -translate-y-1/2 cursor-pointer z-10 flex items-center select-none'
              style={{ top: `${top}px` }}
              onDoubleClick={() => setEditingTicket(spec.position.ticket)}
            >
              <div
                className='w-full border-t-2 border-dashed'
                style={{ borderColor: spec.color }}
              />
              <div
                className='absolute left-2 top-1/2 -translate-y-1/2 rounded px-1 text-[10px] font-bold'
                style={{ backgroundColor: spec.color, color: '#04211e' }}
                title='Double-click to modify this position'
              >
                {spec.label}
              </div>
            </div>
          );
        })}
        {editingTicket !== null &&
          (() => {
            const position = trading.positions.find(
              (p) => p.ticket === editingTicket,
            );
            if (!position) return null;
            const top = candleSeriesRef.current?.priceToCoordinate(
              position.open_price,
            );
            if (top === null || top === undefined) return null;
            return (
              <PositionEditPopover
                position={position}
                top={top}
                busy={editBusy}
                onClose={() => setEditingTicket(null)}
                onSave={(sl, tp) => handleSaveEdit(position.ticket, sl, tp)}
                onClosePosition={() => handleCloseFromEdit(position.ticket)}
              />
            );
          })()}
      </div>
    </section>
  );
}
