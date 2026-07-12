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
import { useEffect, useRef, useState } from 'react';
import {
  getActiveNewsWindows,
  getCandles,
  getSymbolInfo,
  getTradeMarkers,
  type Candle,
  type NewsWindow,
  type PositionOut,
  type TradeMarker,
} from '@/shared/api/client';
import { subscribeRoom } from '@/shared/api/ws';
import type { Trading } from '@/features/trading/useTrading';
import { DrawingToolbar } from './DrawingToolbar';
import { DrawingsList } from './DrawingsList';

/** Tool type strings accepted by DrawingManager.setActiveTool() */
export type DrawingToolType =
  | 'trend-line'
  | 'extended-line'
  | 'horizontal-line'
  | 'vertical-line'
  | 'rectangle'
  | 'fib-retracement'
  | 'parallel-channel';

const TIMEFRAMES: Candle['timeframe'][] = ['M1', 'M5', 'H1', 'H4', 'D1'];
const CANDLE_COUNT = 300;
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
    case "--color-bg":        return "#131722";
    case "--color-panel":     return "#1e222d";
    case "--color-line":      return "#2a2e39";
    case "--color-ink":       return "#d1d4dc";
    case "--color-ink-muted": return "#5d606b";
    case "--color-accent":    return "#2962ff";
    case "--color-ok":        return "#26a69a";
    case "--color-err":       return "#ef5350";
    case "--color-buy":       return "#42a5f5";
    case "--color-sell":      return "#ff9800";
    default:                  return "";
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

export function ChartPanel({
  symbol,
  trading,
}: {
  symbol: string;
  trading: Trading;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const seriesMarkersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  // Drawing tools: one manager instance, alive for the lifetime of the chart.
  const drawingManagerRef = useRef<DrawingManager | null>(null);
  // Guards against applying a live WS update before the REST history load
  // for the current symbol/timeframe has landed — see the effect below.
  const historyLoadedRef = useRef(false);
  // All candles currently on the chart for this symbol/timeframe, oldest
  // first — kept in sync with live updates so "load more" always pages back
  // from the true oldest bar, and mutated in place (no React re-render).
  const candlesRef = useRef<Candle[]>([]);
  const hasMoreHistoryRef = useRef(true);
  const loadingMoreRef = useRef(false);

  const [timeframe, setTimeframe] = useState<Candle['timeframe']>('M5');
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
  // How many anchor points the user has placed for the current in-progress
  // drawing (0 = none yet). Displayed as a hint in the header.
  const [pendingAnchorCount, setPendingAnchorCount] = useState(0);

  // Ticket of the running position whose entry line was double-clicked, if
  // any — drives the SL/TP/close popover rendered below the price lines.
  const [editingTicket, setEditingTicket] = useState<number | null>(null);
  const [editBusy, setEditBusy] = useState(false);

  // Stable references for symbol and symbol-switching state to avoid stale
  // closures inside the chart-creation useEffect.
  const symbolRef = useRef(symbol);
  symbolRef.current = symbol;
  const isSwitchingSymbolRef = useRef(false);

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

    // Attach the drawing manager to the chart and its primary series so the
    // drawing tools can convert pixel ↔ price/time coordinates and register
    // their mouse-event handlers on the container element.
    const manager = new DrawingManager();
    manager.attach(chart, candleSeries, container);
    drawingManagerRef.current = manager;

    // Persist drawings + keep the drawings-list panel in sync whenever any
    // drawing mutation happens.
    const syncList = () => setDrawingsList(manager.getAllDrawings());
    const saveAndSync = () => {
      if (isSwitchingSymbolRef.current) {
        syncList();
        return;
      }
      try {
        const data = manager.exportDrawings();
        localStorage.setItem(
          `chart-drawings:${symbolRef.current}`,
          JSON.stringify(data),
        );
      } catch {
        // localStorage quota or serialisation errors are non-fatal.
      }
      syncList();
    };
    const unsubAdd = manager.on('drawing:added', saveAndSync);
    const unsubRemove = manager.on('drawing:removed', saveAndSync);
    const unsubClear = manager.on('drawing:cleared', saveAndSync);
    const unsubUpdate = manager.on('drawing:updated', saveAndSync);

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

    const bump = () => bumpLines((t) => t + 1);
    container.addEventListener('mousemove', bump, { capture: true });

    return () => {
      observer.disconnect();
      container.removeEventListener('mousemove', bump, { capture: true });
      unsubAdd();
      unsubRemove();
      unsubClear();
      unsubUpdate();
      seriesMarkersRef.current?.detach();
      manager.detach();
      drawingManagerRef.current = null;
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
      seriesMarkersRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Load history + subscribe to live updates whenever symbol/timeframe changes.
  useEffect(() => {
    let cancelled = false;
    setError(null);
    setLoadingMore(false);
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

    function render() {
      const upColor = cssVar('--color-ok');
      const downColor = cssVar('--color-err');
      candleSeriesRef.current?.setData(candlesRef.current.map(toBar));
      volumeSeriesRef.current?.setData(
        candlesRef.current.map((c) => toVolumeBar(c, upColor, downColor)),
      );
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

    getCandles(symbol, timeframe, CANDLE_COUNT)
      .then((candles) => {
        if (cancelled) return;
        candlesRef.current = candles;
        hasMoreHistoryRef.current = candles.length >= CANDLE_COUNT;
        render();
        historyLoadedRef.current = true;
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
      })
      .catch(() => {
        if (!cancelled) setError('failed to load candles');
      });

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
        if (bars.length > 0 && bars[bars.length - 1].time === candle.time) {
          bars[bars.length - 1] = candle;
        } else {
          bars.push(candle);
        }
        try {
          candleSeriesRef.current?.update(toBar(candle));
          volumeSeriesRef.current?.update(
            toVolumeBar(candle, cssVar('--color-ok'), cssVar('--color-err')),
          );
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
      historyLoadedRef.current = false;
      chart
        ?.timeScale()
        .unsubscribeVisibleLogicalRangeChange(onVisibleRangeChange);
      unsubscribe();
    };
  }, [symbol, timeframe]);

  // When the symbol changes, save the current symbol's drawings and load the
  // new symbol's drawings. The chart-creation effect only handles the initial
  // symbol; this effect keeps things in sync on subsequent symbol switches.
  useEffect(() => {
    const manager = drawingManagerRef.current;
    if (!manager) return;
    isSwitchingSymbolRef.current = true;
    manager.clearAll();
    loadDrawingsFromStorage(manager, symbol);
    isSwitchingSymbolRef.current = false;
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
      const style = {
        lineColor: cssVar('--color-accent'),
        lineWidth: 2,
        showLabels: true,
        labelColor: cssVar('--color-ink'),
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

  // Poll trade markers (F7): entry arrows + exit circles from the journal.
  useEffect(() => {
    let cancelled = false;

    const poll = () => {
      getTradeMarkers(symbol)
        .then((trades) => {
          if (cancelled) return;
          const colors = {
            ok: cssVar('--color-ok'),
            err: cssVar('--color-err'),
          };
          seriesMarkersRef.current?.setMarkers(toSeriesMarkers(trades, colors));
        })
        .catch(() => {
          // Journal unreachable — leave whatever markers are already drawn.
        });
    };

    poll();
    const timer = setInterval(poll, MARKERS_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [symbol]);

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

  return (
    <section className='flex flex-1 flex-col rounded-md border border-line bg-panel'>
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
      {/* Drawings list panel — shown when the toggle is active */}
      {showDrawingsList && (
        <DrawingsList
          drawings={drawingsList}
          onRemove={(id) => drawingManagerRef.current?.removeDrawing(id)}
          onToggleVisible={(id) => {
            const d = drawingManagerRef.current?.getDrawing(id);
            if (d) d.updateOptions({ visible: !d.options.visible });
          }}
        />
      )}
      <div className='relative min-h-0 flex-1'>
        <div ref={containerRef} className='h-full w-full' />
        {/* Drawing toolbar — floats on the left edge of the chart canvas */}
        <DrawingToolbar
          activeTool={drawingTool}
          onToolSelect={setDrawingTool}
          onClearAll={() => {
            drawingManagerRef.current?.clearAll();
          }}
        />
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
