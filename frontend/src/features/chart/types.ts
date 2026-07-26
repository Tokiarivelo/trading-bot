import type { RefObject } from 'react';
import type {
  IChartApi,
  ISeriesApi,
  ISeriesMarkersPluginApi,
  Time,
} from 'lightweight-charts';
import type { DrawingManager } from 'lightweight-charts-drawing';
import { type Candle, type PositionOut, type SymbolInfo } from '@/shared/api/client';

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
  | 'snd'
  | 'snd_v2'
  | 'base'
  | 'patterns'
  | 'custom';

export type IndicatorLineStyle = 'solid' | 'dashed' | 'dotted';
export type IndicatorLineWidth = 1 | 2 | 3 | 4;

export interface ManualIndicator {
  id: string;
  type: ManualIndicatorType;
  period: number;
  color: string;
  lineStyle?: IndicatorLineStyle;
  lineWidth?: IndicatorLineWidth;
  label: string;
  /** Set only when type === 'custom': the saved backend indicator's id
   * (GET /indicators/{id}) whose compute() output this instance plots.
   * Mutually exclusive with `previewCode`. */
  indicatorId?: string;
  /** Set only when type === 'custom' and this instance is ad-hoc code not
   * (yet) saved as an indicator — computed via POST /indicators/preview
   * instead of GET /indicators/{id}/compute. Mutually exclusive with
   * `indicatorId`. See IndicatorsDock's "Write new code…" option. */
  previewCode?: string;
}

export type DrawingToolType =
  | 'trend-line'
  | 'extended-line'
  | 'horizontal-line'
  | 'vertical-line'
  | 'rectangle'
  | 'fib-retracement'
  | 'parallel-channel'
  | 'circle'
  | 'long-position'
  | 'short-position'
  | 'price-label'
  | 'text-annotation';

/** Multi-chart layout (split-window §): the primary ChartPanel's replay
 * session/cursor, mirrored into secondary MiniChartPanel windows so they
 * follow the same replayed period at their own timeframe. `sessionPeriod` is
 * an ad-hoc session replay's picked from/to, or — while viewing a saved
 * backtest report — that report's own trades'/signals' time bounds
 * (`useBacktestData.ts`'s `backtestPeriod`); either way secondary windows
 * fetch and cursor-clip it the same way. Null only while nothing is being
 * replayed (or during the live-bot eye view), meaning secondary windows have
 * nothing to sync to and fall back to their own live view. */
export interface SharedReplaySession {
  active: boolean;
  sessionPeriod: { from: number; to: number } | null;
  cursorTime: number | null;
  /** In multi-window layouts, identifies which window index initiated and drives the master replay clock. */
  masterIndex?: number;
}

export interface ReplayUIState {
  showPicker: boolean;
  pickerProps: {
    fromValue: string;
    toValue: string;
    onFromChange: (val: string) => void;
    onToChange: (val: string) => void;
    estimate: {
      candles: number;
      pages: number;
      level: 'ok' | 'warn' | 'block';
    } | null;
    onCancel: () => void;
    onStart: () => void;
  } | null;
  sessionPeriod: { from: number; to: number } | null;
  loadingPage: { page: number; loaded: number } | null;
  replayActive: boolean;
  replayControlsProps: {
    playing: boolean;
    onPlayPause: () => void;
    onStepBack: () => void;
    onStepForward: () => void;
    speed: number;
    onSpeedChange: (speed: number) => void;
    cursorIndex: number;
    totalBars: number;
    currentTime: string;
    onSeek: (index: number) => void;
    following: boolean;
    onRecenter: () => void;
  } | null;
}

export interface NewsBand {
  key: string;
  left: number;
  width: number;
  label: string;
  phase: 'pre' | 'post';
}

// User-configurable look for the selected trade's open/close lines (see
// `buildSelectedTradeLines`) — persisted globally (not per-symbol) since
// it's a display preference, like `chart-show-separators`.
export type OrderLineDash = 'solid' | 'dashed' | 'dotted';

export interface OrderLineStyle {
  visible: boolean;
  dash: OrderLineDash;
  width: 1 | 2 | 3 | 4;
  customColors: boolean;
  openColor: string;
  closeColor: string;
  showExitLine: boolean;
  exitLineDash: OrderLineDash;
  exitLineWidth: 1 | 2 | 3 | 4;
  exitLineCustomColor: boolean;
  exitLineWinColor: string;
  exitLineLossColor: string;
}

export interface PriceLineSpec {
  key: string;
  ticket: number;
  price: number;
  color: string;
  label: string;
  commit: (newPrice: number) => void;
  placeholder?: boolean; // no sl/tp set yet — drag (or click) this to add one
}

export interface EntryLineSpec {
  key: string;
  position: PositionOut;
  color: string;
  label: string;
}

/** Handle onto the lightweight-charts engine — chart instance, the two base
 * series, the drawing manager, and the two series-markers plugin instances
 * (trade markers + the independent structure/QML marker layer) — created
 * once by `useChartEngine` and consumed by every other chart hook that needs
 * to read or draw onto the chart (`useIndicators`, and later phases'
 * `useCandleData`/`useDrawingTools`/`useReplayEngine`). Getter functions
 * (rather than plain fields) so a stable controller object can always report
 * the current instance without itself needing to change identity on every
 * chart mutation — only `isReady` flipping true (mount) or false (unmount)
 * changes the controller's identity, which is what consumer effects should
 * key off of. */
export interface ChartEngineController {
  containerRef: RefObject<HTMLDivElement | null>;
  getChart(): IChartApi | null;
  getCandleSeries(): ISeriesApi<'Candlestick'> | null;
  getVolumeSeries(): ISeriesApi<'Histogram'> | null;
  getDrawingManager(): DrawingManager | null;
  /** Trade entry/exit markers (backtest/live/custom-code) — see chartMarkers.ts. */
  getSeriesMarkersPrimitive(): ISeriesMarkersPluginApi<Time> | null;
  /** Independent marker layer for the 'structure'/'qml'/'snd'/'patterns'
   * manual-indicator types — kept separate so toggling structure markers
   * never touches the trade-marker plugin instance above. */
  getStructureMarkersPrimitive(): ISeriesMarkersPluginApi<Time> | null;
  /** True once `createChart`/series/`DrawingManager` setup has completed
   * (mount), false again once torn down (unmount). Consumers should treat
   * `false` as "nothing above is safe to call yet" rather than relying on
   * null-checking every getter individually. */
  isReady: boolean;
}

/** Handle onto the current symbol/timeframe's candle data and its paint
 * pipeline — created by `useCandleData` (phase 7), consumed by ChartPanel's
 * not-yet-extracted replay code (`seekTo`/`handleEnterReplay`/
 * `handleExitReplay`/`navigateToTime`, phase 9's `useReplayEngine`
 * territory) wherever it used to reach for the old `renderRef.current()`
 * ref-hack. */
export interface ChartRenderController {
  /** All candles currently loaded for this symbol/timeframe, oldest first.
   * Still a ref (not React state) — it's mutated on every live tick and by
   * `loadMore`'s pagination, and re-rendering the whole component on every
   * tick would be wasteful; consumers that need to react to it read through
   * `paintUpTo()`/`visibleCandles()` instead of expecting fresh renders.
   * Owned (created) by ChartPanel.tsx, not this controller, because
   * `useChartEngine`/`useIndicators` are called before `useCandleData` can
   * exist (they need `chartController`, which only `useChartEngine` can
   * produce) yet both need a `visibleCandles()` reader over this same ref —
   * see useCandleData.ts's module doc for the full explanation. */
  candlesRef: RefObject<Candle[]>;
  /** Repaints the candle/volume series from the current `visibleCandles()`
   * window (the full loaded history, or a prefix up to the replay cursor)
   * and schedules an indicator recompute — a real, stable-identity function
   * replacing the old `renderRef.current()` mutable-ref-assignment hack. */
  paintUpTo(): void;
  symbolInfo: SymbolInfo | null;
  spreadPoints: number | null;
  error: string | null;
  loadingMore: boolean;
  switchingChart: boolean;
  newsBands: NewsBand[];
}
