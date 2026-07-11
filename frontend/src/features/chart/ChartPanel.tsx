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
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef, useState } from "react";
import {
  getCandles,
  getSymbolInfo,
  getTradeMarkers,
  type Candle,
  type TradeMarker,
} from "@/shared/api/client";
import { subscribeRoom } from "@/shared/api/ws";

const TIMEFRAMES: Candle["timeframe"][] = ["M1", "M5", "H1", "H4", "D1"];
const CANDLE_COUNT = 300;
const SPREAD_POLL_MS = 3000;
const MARKERS_POLL_MS = 5000;

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
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

export function ChartPanel({ symbol }: { symbol: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const seriesMarkersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  // Guards against applying a live WS update before the REST history load
  // for the current symbol/timeframe has landed — see the effect below.
  const historyLoadedRef = useRef(false);

  const [timeframe, setTimeframe] = useState<Candle["timeframe"]>("M5");
  const [spreadPoints, setSpreadPoints] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Create the chart once; destroy on unmount.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const line = cssVar("--color-line");
    const chart = createChart(container, {
      layout: {
        background: { color: cssVar("--color-panel") },
        textColor: cssVar("--color-ink"),
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
    // WS updates for the new room can start arriving before the REST
    // history call below resolves. Applying one to the still-stale
    // previous symbol/timeframe's data can move time backwards (e.g.
    // switching from M1 to D1: the D1 forming bar's open time is earlier
    // than the M1 bar still on screen) and lightweight-charts throws.
    // Dropping live updates until history for *this* symbol/timeframe is
    // actually on the chart avoids that race.
    historyLoadedRef.current = false;

    getCandles(symbol, timeframe, CANDLE_COUNT)
      .then((candles) => {
        if (cancelled) return;
        const upColor = cssVar("--color-ok");
        const downColor = cssVar("--color-err");
        candleSeriesRef.current?.setData(candles.map(toBar));
        volumeSeriesRef.current?.setData(candles.map((c) => toVolumeBar(c, upColor, downColor)));
        historyLoadedRef.current = true;
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
        <span className="ml-auto text-xs text-ink-muted">
          spread: {spreadPoints === null ? "—" : `${spreadPoints} pts`}
        </span>
      </header>
      {error && <p className="px-4 py-1 text-xs text-err">{error}</p>}
      <div ref={containerRef} className="min-h-0 flex-1" />
    </section>
  );
}
