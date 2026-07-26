'use client';

/**
 * Secondary chart window (multi-chart layout, split-window §): a lightweight
 * sibling of ChartPanel for the up-to-3 extra windows in MultiChartLayout —
 * candles, volume, and trade markers only. No drawing tools, indicators
 * dock, order popovers, or trade placement; those stay exclusive to the
 * primary ChartPanel window (see MultiChartLayout's module doc for why).
 * Its own timeframe is independent of the primary window's, but it always
 * follows the primary window's symbol and, when a shared replay session is
 * active, its replay cursor (see useMiniCandleData.ts).
 */

import {
  CandlestickSeries,
  createChart,
  createSeriesMarkers,
  HistogramSeries,
  type IChartApi,
  type ISeriesApi,
} from 'lightweight-charts';
import { Check, ChevronDown, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { getTradeMarkers, type Candle } from '@/shared/api/client';
import { useActiveAccount } from '@/shared/api/account-context';
import { cssVar, TIMEFRAMES } from './chartFormat';
import { toBar, toVolumeBar } from './chartData';
import { toSeriesMarkers } from './chartMarkers';
import { useMiniCandleData } from './useMiniCandleData';
import type { SharedReplaySession } from './types';

const MARKERS_POLL_MS = 5000;

export function MiniChartPanel({
  symbol,
  timeframe,
  onTimeframeChange,
  sharedReplay,
  onClose,
}: {
  symbol: string;
  timeframe: Candle['timeframe'];
  onTimeframeChange: (tf: Candle['timeframe']) => void;
  /** Null outside a multi-chart layout — this window then just shows its
   * own live view, same as if replay never existed. */
  sharedReplay: SharedReplaySession | null;
  onClose: () => void;
}) {
  const accountId = useActiveAccount();
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const [showTfDropdown, setShowTfDropdown] = useState(false);

  const { visibleCandles, error, replaying } = useMiniCandleData({
    accountId,
    symbol,
    timeframe,
    sharedReplay,
  });

  // Create the chart once; destroy on unmount — same base setup as
  // useChartEngine's candlestick+volume series, minus drawing tools/markers
  // plumbing this window doesn't need.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const line = cssVar('--color-line');
    const chart = createChart(container, {
      layout: {
        background: { color: cssVar('--color-panel') },
        textColor: cssVar('--color-ink'),
        attributionLogo: true,
      },
      grid: { vertLines: { color: line }, horzLines: { color: line } },
      timeScale: { timeVisible: true, secondsVisible: false, borderColor: line },
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
    volumeSeries.priceScale().applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;

    const resize = () => {
      const width = container.clientWidth;
      const height = container.clientHeight;
      if (width === 0 || height === 0) return;
      chart.applyOptions({ width, height });
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(container);

    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
    };
  }, []);

  // Repaint on every candle change (history load, live tick, or replay
  // cursor clip) — cheap `setData()` fill, same as the primary window's
  // `render()`.
  useEffect(() => {
    const upColor = cssVar('--color-ok');
    const downColor = cssVar('--color-err');
    candleSeriesRef.current?.setData(visibleCandles.map(toBar));
    volumeSeriesRef.current?.setData(
      visibleCandles.map((c) => toVolumeBar(c, upColor, downColor)),
    );
    chartRef.current?.timeScale().fitContent();
  }, [visibleCandles]);

  // Trade markers — polled independently of replay state; this window has
  // no backtest-report view, so it always shows the live journal's trades
  // for this symbol, same set the primary window shows outside backtest/
  // live-bot-eye view.
  useEffect(() => {
    if (!accountId) return;
    let cancelled = false;
    const seriesMarkers = candleSeriesRef.current
      ? createSeriesMarkers(candleSeriesRef.current, [])
      : null;

    function poll() {
      getTradeMarkers(accountId!, symbol)
        .then((trades) => {
          if (cancelled) return;
          seriesMarkers?.setMarkers(
            toSeriesMarkers(trades, { ok: cssVar('--color-ok'), err: cssVar('--color-err') }, false),
          );
        })
        .catch(() => {
          // Transient failure — next poll retries.
        });
    }
    poll();
    const timer = setInterval(poll, MARKERS_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
      seriesMarkers?.setMarkers([]);
    };
  }, [accountId, symbol]);

  return (
    <div className="flex min-w-0 flex-1 flex-col rounded-md border border-line bg-panel">
      <div className="flex items-center gap-2 border-b border-line px-2 py-1 text-xs">
        <span className="font-bold text-ink">{symbol}</span>
        {replaying && <span className="rounded bg-accent/20 px-1 text-accent">replay</span>}
        <div className="relative ml-auto">
          <button
            onClick={() => setShowTfDropdown((v) => !v)}
            className="flex cursor-pointer items-center gap-0.5 rounded border border-line px-1.5 py-0.5 text-ink-muted hover:border-accent hover:text-accent"
          >
            {timeframe}
            <ChevronDown size={12} />
          </button>
          {showTfDropdown && (
            <div className="absolute top-full right-0 z-10 mt-1 flex flex-col rounded border border-line bg-panel py-1 shadow-lg">
              {TIMEFRAMES.map((tf) => (
                <button
                  key={tf}
                  onClick={() => {
                    onTimeframeChange(tf);
                    setShowTfDropdown(false);
                  }}
                  className="flex cursor-pointer items-center justify-between gap-4 px-3 py-1 text-left hover:bg-line/40"
                >
                  {tf}
                  {tf === timeframe && <Check size={12} className="text-accent" />}
                </button>
              ))}
            </div>
          )}
        </div>
        <button
          onClick={onClose}
          className="cursor-pointer text-ink-muted hover:text-err"
          title="Close window"
        >
          <X size={14} />
        </button>
      </div>
      <div className="relative min-h-0 flex-1">
        <div ref={containerRef} className="absolute inset-0" />
        {error && (
          <div className="absolute inset-x-0 top-0 bg-err/90 px-2 py-1 text-center text-xs text-white">
            {error}
          </div>
        )}
      </div>
    </div>
  );
}
