import { memo, useEffect, useRef } from 'react';
import type { ZoneMeta } from './types';

export interface ZoneInfoPopoverProps {
  x: number;
  y: number;
  meta: ZoneMeta;
  containerWidth: number;
  containerHeight: number;
  onClose: () => void;
}

const STATE_LABEL: Record<ZoneMeta['state'], string> = {
  fresh: 'Fresh — still valid',
  touched: 'Touched — consumed',
  triggered: 'Triggered a trade',
};

function formatTime(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toLocaleString();
}

/** Read-only card shown when a zone rectangle (Quasimodo, S&D v1/v2, or a
 * per-trade backend zone) is clicked — see the click effect in
 * ChartPanel.tsx that resolves a clicked drawing id to a `ZoneMeta` via
 * `chartController.getZoneMetaMap()`. Positioning mirrors
 * `DrawingEditPopover.tsx`'s edge-flipping so it never renders off-canvas. */
export const ZoneInfoPopover = memo(function ZoneInfoPopover({
  x,
  y,
  meta,
  containerWidth,
  containerHeight,
  onClose,
}: ZoneInfoPopoverProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleMouseDownOutside = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onClose();
      }
    };
    window.addEventListener('mousedown', handleMouseDownOutside);
    return () => window.removeEventListener('mousedown', handleMouseDownOutside);
  }, [onClose]);

  const popoverWidth = 220;
  const popoverHeight = 220;
  const left = x + popoverWidth > containerWidth ? x - popoverWidth : x;
  const top = y + popoverHeight > containerHeight ? y - popoverHeight : y;

  const demand = meta.kind === 'demand';

  return (
    <div
      ref={ref}
      className='pointer-events-auto absolute z-30 flex w-56 flex-col gap-2 rounded border border-line bg-panel p-3 text-xs shadow-xl backdrop-blur-sm bg-opacity-95'
      style={{ left: `${left}px`, top: `${top}px` }}
      onMouseDown={(e) => e.stopPropagation()}
    >
      <div className='flex items-center justify-between border-b border-line pb-1'>
        <span className='font-bold text-ink'>{meta.indicatorLabel}</span>
        <button
          onClick={onClose}
          className='cursor-pointer text-ink-muted hover:text-ink text-sm font-bold'
          title='Close'
        >
          ×
        </button>
      </div>

      <div className='flex items-center gap-1.5'>
        <span
          className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${
            demand ? 'bg-buy/15 text-buy' : 'bg-sell/15 text-sell'
          }`}
        >
          {demand ? 'DEMAND (BUY)' : 'SUPPLY (SELL)'}
        </span>
        {meta.pattern && (
          <span className='rounded bg-line/60 px-1.5 py-0.5 text-[10px] font-medium text-ink'>
            {meta.pattern}
          </span>
        )}
      </div>

      <div className='flex flex-col gap-1 text-ink-muted'>
        <div className='flex justify-between'>
          <span>State</span>
          <span className='text-ink'>{STATE_LABEL[meta.state]}</span>
        </div>
        <div className='flex justify-between'>
          <span>High</span>
          <span className='text-ink'>{meta.priceHigh}</span>
        </div>
        <div className='flex justify-between'>
          <span>Low</span>
          <span className='text-ink'>{meta.priceLow}</span>
        </div>
        <div className='flex justify-between gap-2'>
          <span>Start</span>
          <span className='text-ink text-right'>{formatTime(meta.timeStart)}</span>
        </div>
        <div className='flex justify-between gap-2'>
          <span>End</span>
          <span className='text-ink text-right'>
            {meta.timeEnd !== null ? formatTime(meta.timeEnd) : 'Still open'}
          </span>
        </div>
        {meta.extra &&
          Object.entries(meta.extra).map(([label, value]) => (
            <div key={label} className='flex justify-between gap-2'>
              <span>{label}</span>
              <span className='text-ink text-right truncate max-w-[130px]' title={String(value)}>
                {value}
              </span>
            </div>
          ))}
      </div>
    </div>
  );
});
