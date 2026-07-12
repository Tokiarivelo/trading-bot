"use client";

/**
 * Chart feature (Phase 2+3): lightweight-charts candlesticks + volume, live WS
 * updates, timeframe switcher, spread indicator, and trade markers (F7) from
 * the journal — entry arrows + exit circles, refreshed alongside the spread.
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
} from "lightweight-charts";
import { useEffect, useRef, useState } from "react";
import {
  getActiveNewsWindows,
  getCandles,
  getSymbolInfo,
  getTradeMarkers,
  type Candle,
  type NewsWindow,
  type TradeMarker,
} from "@/shared/api/client";
import { subscribeRoom } from "@/shared/api/ws";
import type { Trading } from "@/features/trading/useTrading";

const TIMEFRAMES: Candle["timeframe"][] = ["M1", "M5", "H1", "H4", "D1"];
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

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function hexToRgba(hex: string, alpha: number): string {
  const clean = hex.replace("#", "");
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
  phase: "pre" | "post";
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
): message is { type: "candle_closed" | "candle_update"; candle: Candle } {
  const type = (message as { type?: unknown } | null)?.type;
  return type === "candle_closed" || type === "candle_update";
}

function toSeriesMarkers(
  trades: TradeMarker[],
  colors: { ok: string; err: string },
): SeriesMarker<Time>[] {
  const markers: SeriesMarker<Time>[] = [];
  for (const t of trades) {
    markers.push({
      time: t.open_time as UTCTimestamp,
      position: t.side === "buy" ? "belowBar" : "aboveBar",
      color: t.side === "buy" ? colors.ok : colors.err,
      shape: t.side === "buy" ? "arrowUp" : "arrowDown",
      text: `${t.side.toUpperCase()} ${t.volume}`,
    });
    if (t.close_time !== null) {
      markers.push({
        time: t.close_time as UTCTimestamp,
        position: "inBar",
        color: (t.profit ?? 0) >= 0 ? colors.ok : colors.err,
        shape: "circle",
        text: t.profit !== null ? `${t.profit >= 0 ? "+" : ""}${t.profit.toFixed(2)}` : "close",
      });
    }
  }
  // The markers plugin requires ascending time order.
  return markers.sort((a, b) => (a.time as number) - (b.time as number));
}

export function ChartPanel({ symbol, trading }: { symbol: string; trading: Trading }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const seriesMarkersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  // Guards against applying a live WS update before the REST history load
  // for the current symbol/timeframe has landed — see the effect below.
  const historyLoadedRef = useRef(false);
  // All candles currently on the chart for this symbol/timeframe, oldest
  // first — kept in sync with live updates so "load more" always pages back
  // from the true oldest bar, and mutated in place (no React re-render).
  const candlesRef = useRef<Candle[]>([]);
  const hasMoreHistoryRef = useRef(true);
  const loadingMoreRef = useRef(false);

  const [timeframe, setTimeframe] = useState<Candle["timeframe"]>("M5");
  const [spreadPoints, setSpreadPoints] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [newsBands, setNewsBands] = useState<NewsBand[]>([]);

  // SL/TP/trigger-price draggable lines (F-manual-trading): dragging updates
  // this only for live visual feedback during the drag — the actual API
  // call fires once on mouseup, via `spec.commit`.
  const [drag, setDrag] = useState<{ key: string; price: number; commit: (p: number) => void } | null>(
    null,
  );
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

    const line = cssVar("--color-line");
    const chart = createChart(container, {
      layout: {
        background: { color: cssVar("--color-panel") },
        textColor: cssVar("--color-ink"),
        // Required by lightweight-charts' free-tier license — do not hide or
        // replace this mark. Explicit `true` (not the implicit default) so
        // the license condition is visible here in code.
        attributionLogo: true,
      },
      grid: {
        vertLines: { color: line },
        horzLines: { color: line },
      },
      timeScale: { timeVisible: true, secondsVisible: false, borderColor: line },
      rightPriceScale: { borderColor: line },
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: cssVar("--color-ok"),
      downColor: cssVar("--color-err"),
      borderVisible: false,
      wickUpColor: cssVar("--color-ok"),
      wickDownColor: cssVar("--color-err"),
    });

    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
    });
    volumeSeries.priceScale().applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;
    seriesMarkersRef.current = createSeriesMarkers(candleSeries, []);

    const resize = () => chart.applyOptions({ width: container.clientWidth, height: container.clientHeight });
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(container);

    return () => {
      observer.disconnect();
      seriesMarkersRef.current?.detach();
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
      seriesMarkersRef.current = null;
    };
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
      const upColor = cssVar("--color-ok");
      const downColor = cssVar("--color-err");
      candleSeriesRef.current?.setData(candlesRef.current.map(toBar));
      volumeSeriesRef.current?.setData(
        candlesRef.current.map((c) => toVolumeBar(c, upColor, downColor)),
      );
    }

    // Fetches the next page of older bars once the user pans near the left
    // edge of what's loaded — the chart's "fetch more" is this auto-trigger
    // plus the `loadingMore` indicator rendered below, not a manual button.
    async function loadMore() {
      if (loadingMoreRef.current || !hasMoreHistoryRef.current || candlesRef.current.length === 0) {
        return;
      }
      loadingMoreRef.current = true;
      setLoadingMore(true);
      const oldest = candlesRef.current[0];
      try {
        const older = await getCandles(symbol, timeframe, CANDLE_COUNT, oldest.time);
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
          const range = chart?.timeScale().getVisibleLogicalRange();
          render();
          if (range) {
            chart?.timeScale().setVisibleLogicalRange({
              from: range.from + older.length,
              to: range.to + older.length,
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
      })
      .catch(() => {
        if (!cancelled) setError("failed to load candles");
      });

    // `candle_update` streams the in-progress bar every ~1.5s so the
    // rightmost candle moves continuously like MT5; `candle_closed` is the
    // authoritative final print once the bar completes. Both are handled
    // identically here — lightweight-charts' `update()` amends the last bar
    // in place when the timestamp matches, or appends a new one otherwise.
    const unsubscribe = subscribeRoom(
      ["candle_closed", "candle_update"],
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
            toVolumeBar(candle, cssVar("--color-ok"), cssVar("--color-err")),
          );
        } catch (err) {
          // Defensive: lightweight-charts throws if a live update's time
          // is older than what's on the chart. Shouldn't happen once
          // gated by historyLoadedRef, but a dropped frame beats a crash.
          console.warn("chart: dropped out-of-order live update", err);
        }
      },
    );

    return () => {
      cancelled = true;
      historyLoadedRef.current = false;
      chart?.timeScale().unsubscribeVisibleLogicalRangeChange(onVisibleRangeChange);
      unsubscribe();
    };
  }, [symbol, timeframe]);

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
          const colors = { ok: cssVar("--color-ok"), err: cssVar("--color-err") };
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
        const x2 = chart.timeScale().timeToCoordinate(Math.min(to, w.window_end) as UTCTimestamp);
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
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  function buildPriceLines(): PriceLineSpec[] {
    const okColor = cssVar("--color-ok");
    const errColor = cssVar("--color-err");
    const accentColor = cssVar("--color-accent");
    const specs: PriceLineSpec[] = [];
    for (const p of trading.positions) {
      const offset = defaultOffset(p.open_price);
      const direction = p.side === "buy" ? 1 : -1;
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
          label: "+ SL",
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
          label: "+ TP",
          placeholder: true,
          commit: (np) => trading.modifyPositionSlTp(p.ticket, p.sl, np),
        });
      }
    }
    for (const o of trading.pendingOrders) {
      const offset = defaultOffset(o.price);
      const direction = o.side === "buy" ? 1 : -1;
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
          label: "+ SL",
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
          label: "+ TP",
          placeholder: true,
          commit: (np) => trading.modifyPending(o.ticket, null, o.sl, np),
        });
      }
    }
    return specs;
  }

  return (
    <section className="flex flex-1 flex-col rounded-md border border-line bg-panel">
      <header className="flex items-center gap-3 border-b border-line px-4 py-2">
        <strong>{symbol}</strong>
        <nav className="flex gap-1">
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf}
              className={`cursor-pointer rounded border px-2 py-0.5 text-xs ${
                tf === timeframe ? "border-accent text-accent" : "border-line text-ink-muted"
              }`}
              onClick={() => setTimeframe(tf)}
            >
              {tf}
            </button>
          ))}
        </nav>
        <div className="flex gap-1">
          <button
            className="cursor-pointer rounded border border-line px-2 py-0.5 text-xs text-ink-muted"
            onClick={() => chartRef.current?.timeScale().scrollToRealTime()}
          >
            Latest
          </button>
          <button
            className="cursor-pointer rounded border border-line px-2 py-0.5 text-xs text-ink-muted"
            onClick={() => chartRef.current?.timeScale().resetTimeScale()}
          >
            Reset zoom
          </button>
        </div>
        <span className="ml-auto text-xs text-ink-muted">
          spread: {spreadPoints === null ? "—" : `${spreadPoints} pts`}
        </span>
      </header>
      {error && <p className="px-4 py-1 text-xs text-err">{error}</p>}
      <div className="relative min-h-0 flex-1">
        <div ref={containerRef} className="h-full w-full" />
        {newsBands.map((b) => {
          const color = cssVar(b.phase === "pre" ? "--color-err" : "--color-accent");
          return (
            <div
              key={b.key}
              className="pointer-events-none absolute top-0 h-full border-x border-dashed"
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
          <div className="pointer-events-none absolute left-2 top-2 rounded border border-line bg-panel px-2 py-1 text-xs text-ink-muted">
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
              className="pointer-events-none absolute left-0 right-0 border-t border-dashed"
              style={{ top, borderColor: spec.color, opacity: faint ? 0.45 : 1 }}
            >
              <div
                className="pointer-events-auto absolute right-2 -translate-y-1/2 cursor-ns-resize select-none rounded px-1 text-[10px] font-bold"
                style={{
                  backgroundColor: spec.color,
                  color: "#04211e",
                  opacity: faint ? 0.7 : 1,
                }}
                title={spec.placeholder ? "Drag to set — not saved yet" : "Drag to modify"}
                onMouseDown={(e) => {
                  e.preventDefault();
                  setDrag({ key: spec.key, price: spec.price, commit: spec.commit });
                }}
              >
                {dragging ? price.toFixed(5) : spec.label}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
