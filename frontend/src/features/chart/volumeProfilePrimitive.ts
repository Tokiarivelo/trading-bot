/**
 * Volume Profile — a horizontal volume-by-price histogram overlaid on the
 * main price pane (TradingView-style), implemented as a lightweight-charts
 * v5 custom series primitive (`ISeriesPrimitive`, attached to the candle
 * series via `series.attachPrimitive()`) rather than a line/histogram series,
 * since it draws bars keyed by price bucket, not one value per bar time.
 *
 * Buckets `candles` (already sliced to the desired lookback window by the
 * caller — see the 'volume_profile' case in useIndicators.ts) into
 * `bucketCount` equal price bins spanning the window's low..high, summing
 * each candle's `tick_volume` (the same volume proxy `vwap()` in
 * indicators.ts and the volume histogram series use — MT5 doesn't report
 * real traded volume for most CFD/FX symbols) into whichever bucket its
 * `(high+low)/2` midpoint falls in. Drawn as semi-transparent rectangles
 * anchored to the pane's right (or left) edge, one per bucket, height set by
 * the bucket's own price span and width proportional to that bucket's share
 * of the window's total volume.
 */

import type {
  AutoscaleInfo,
  Coordinate,
  IChartApiBase,
  ISeriesApi,
  ISeriesPrimitive,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  Logical,
  SeriesAttachedParameter,
  SeriesType,
  Time,
} from 'lightweight-charts';
import type { Candle } from '@/shared/api/client';

// `fancy-canvas`'s `CanvasRenderingTarget2D` is lightweight-charts's own
// (nested, non-hoisted) dependency — not resolvable as a direct import from
// this package, and not re-exported by lightweight-charts. Extracted from
// `IPrimitivePaneRenderer['draw']`'s own parameter type instead of importing
// it directly, so this file only ever depends on the lightweight-charts
// package already installed.
type DrawTarget = Parameters<IPrimitivePaneRenderer['draw']>[0];

export interface VolumeProfileBucket {
  priceLow: number;
  priceHigh: number;
  volume: number;
}

export interface VolumeProfileOptions {
  candles: Candle[];
  bucketCount: number;
  side: 'left' | 'right';
  color: string;
  /** Fraction of the pane's width the tallest (max-volume) bucket's bar
   * reaches — the rest scale proportionally to it. */
  maxWidthFraction?: number;
}

function hexToRgbaLocal(hex: string, alpha: number): string {
  const clean = hex.replace('#', '');
  const full =
    clean.length === 3
      ? clean
          .split('')
          .map((c) => c + c)
          .join('')
      : clean;
  const r = parseInt(full.slice(0, 2), 16) || 0;
  const g = parseInt(full.slice(2, 4), 16) || 0;
  const b = parseInt(full.slice(4, 6), 16) || 0;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function computeBuckets(candles: Candle[], bucketCount: number): VolumeProfileBucket[] {
  if (candles.length === 0 || bucketCount < 1) return [];
  let low = Infinity;
  let high = -Infinity;
  for (const c of candles) {
    if (c.low < low) low = c.low;
    if (c.high > high) high = c.high;
  }
  if (!Number.isFinite(low) || !Number.isFinite(high) || high <= low) return [];

  const step = (high - low) / bucketCount;
  const buckets: VolumeProfileBucket[] = Array.from({ length: bucketCount }, (_, i) => ({
    priceLow: low + i * step,
    priceHigh: low + (i + 1) * step,
    volume: 0,
  }));

  for (const c of candles) {
    const mid = (c.high + c.low) / 2;
    let idx = Math.floor((mid - low) / step);
    if (idx < 0) idx = 0;
    if (idx >= bucketCount) idx = bucketCount - 1;
    buckets[idx].volume += c.tick_volume;
  }
  return buckets;
}

class VolumeProfilePaneRenderer implements IPrimitivePaneRenderer {
  constructor(
    private readonly bars: {
      yTop: Coordinate | null;
      yBottom: Coordinate | null;
      widthFraction: number;
    }[],
    private readonly side: 'left' | 'right',
    private readonly color: string,
    private readonly maxWidthFraction: number,
  ) {}

  draw(target: DrawTarget): void {
    target.useBitmapCoordinateSpace((scope) => {
      const ctx = scope.context;
      const paneWidth = scope.bitmapSize.width;
      const fill = hexToRgbaLocal(this.color, 0.35);
      const stroke = hexToRgbaLocal(this.color, 0.7);
      ctx.save();
      for (const bar of this.bars) {
        if (bar.yTop === null || bar.yBottom === null) continue;
        const top = bar.yTop * scope.verticalPixelRatio;
        const bottom = bar.yBottom * scope.verticalPixelRatio;
        const h = Math.max(1, bottom - top);
        const w = Math.max(1, paneWidth * this.maxWidthFraction * bar.widthFraction);
        const x = this.side === 'right' ? paneWidth - w : 0;
        ctx.fillStyle = fill;
        ctx.strokeStyle = stroke;
        ctx.lineWidth = 1;
        ctx.fillRect(x, top, w, h);
        ctx.strokeRect(x, top, w, h);
      }
      ctx.restore();
    });
  }
}

class VolumeProfilePaneView implements IPrimitivePaneView {
  constructor(private readonly source: VolumeProfilePrimitive) {}

  zOrder(): 'bottom' {
    return 'bottom';
  }

  renderer(): IPrimitivePaneRenderer | null {
    const series = this.source.getSeries();
    if (!series) return null;
    const buckets = this.source.getBuckets();
    if (buckets.length === 0) return null;
    const maxVolume = Math.max(...buckets.map((b) => b.volume), 1);
    const bars = buckets.map((b) => ({
      yTop: series.priceToCoordinate(b.priceHigh),
      yBottom: series.priceToCoordinate(b.priceLow),
      widthFraction: b.volume / maxVolume,
    }));
    return new VolumeProfilePaneRenderer(
      bars,
      this.source.getOptions().side,
      this.source.getOptions().color,
      this.source.getOptions().maxWidthFraction ?? 0.25,
    );
  }
}

/**
 * The volume-profile primitive itself — implements `ISeriesPrimitive` and is
 * attached via `candleSeries.attachPrimitive(primitive)` / detached via
 * `candleSeries.detachPrimitive(primitive)` (see useIndicators.ts, which
 * tracks live instances in `volumeProfilePrimitivesRef` and detaches/
 * recreates them every recompute, same "wholesale replace" convention as
 * every other manual-indicator series there).
 */
export class VolumeProfilePrimitive implements ISeriesPrimitive<Time> {
  private options: VolumeProfileOptions;
  private buckets: VolumeProfileBucket[];
  private series: ISeriesApi<SeriesType, Time> | null = null;
  private chart: IChartApiBase<Time> | null = null;
  private readonly paneViewInstance: VolumeProfilePaneView;

  constructor(options: VolumeProfileOptions) {
    this.options = options;
    this.buckets = computeBuckets(options.candles, options.bucketCount);
    this.paneViewInstance = new VolumeProfilePaneView(this);
  }

  getOptions(): VolumeProfileOptions {
    return this.options;
  }

  getBuckets(): VolumeProfileBucket[] {
    return this.buckets;
  }

  getSeries(): ISeriesApi<SeriesType, Time> | null {
    return this.series;
  }

  attached(param: SeriesAttachedParameter<Time, SeriesType>): void {
    this.series = param.series;
    this.chart = param.chart;
  }

  detached(): void {
    this.series = null;
    this.chart = null;
  }

  updateAllViews(): void {
    // Buckets are static per attach (computed once from the sliced candle
    // window at construction) — only pixel coordinates need to refresh, and
    // those are recomputed lazily in `renderer()` above on every draw.
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return [this.paneViewInstance];
  }

  autoscaleInfo(_startTimePoint: Logical, _endTimePoint: Logical): AutoscaleInfo | null {
    // The profile itself shouldn't widen the main price scale beyond what
    // the candles already require — it's drawn inside the pane's existing
    // vertical extent, not something that should pull the axis wider.
    return null;
  }
}
