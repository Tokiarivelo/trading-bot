import { memo, useEffect, useRef } from 'react';
import type { BacktestSignal } from '@/shared/api/client';
import { SIGNAL_OUTCOME_META } from '@/features/backtest/signalOutcome';

export interface SignalInfoPopoverProps {
  x: number;
  y: number;
  /** Every non-`opened` signal that landed on the clicked bar — the markers
   * builder groups same-bar/same-outcome signals into one square, so a click
   * can legitimately resolve to more than one rejection reason. */
  signals: BacktestSignal[];
  containerWidth: number;
  containerHeight: number;
  onClose: () => void;
}

function formatTime(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toLocaleString();
}

/** Read-only card shown when a rejected/vetoed signal marker (the square
 * markers from `toSignalSeriesMarkers`) is clicked — answers "why didn't the
 * bot take this setup?" with the strategy's own `reason` text. Opened by
 * ChartPanel.tsx's signal-click hit-test effect; positioning and
 * dismiss-on-outside-click mirror `ZoneInfoPopover.tsx`. */
export const SignalInfoPopover = memo(function SignalInfoPopover({
  x,
  y,
  signals,
  containerWidth,
  containerHeight,
  onClose,
}: SignalInfoPopoverProps) {
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

  const popoverWidth = 288;
  const popoverHeight = 240;
  const left = x + popoverWidth > containerWidth ? x - popoverWidth : x;
  const top = y + popoverHeight > containerHeight ? y - popoverHeight : y;

  return (
    <div
      ref={ref}
      className='pointer-events-auto absolute z-30 flex w-72 flex-col gap-2 rounded border border-line bg-panel p-3 text-xs shadow-xl backdrop-blur-sm bg-opacity-95'
      style={{ left: `${left}px`, top: `${top}px` }}
      onMouseDown={(e) => e.stopPropagation()}
    >
      <div className='flex items-center justify-between border-b border-line pb-1'>
        <span className='font-bold text-ink'>
          {signals.length > 1 ? `Rejected signals (${signals.length})` : 'Rejected signal'}
        </span>
        <button
          onClick={onClose}
          className='cursor-pointer text-ink-muted hover:text-ink text-sm font-bold'
          title='Close'
        >
          ×
        </button>
      </div>

      <div className='flex max-h-64 flex-col gap-3 overflow-y-auto'>
        {signals.map((s, i) => {
          const meta = SIGNAL_OUTCOME_META[s.outcome];
          const buy = s.direction === 'buy';
          return (
            <div key={`${s.time}:${s.direction}:${s.outcome}:${i}`} className='flex flex-col gap-1'>
              <div className='flex items-center gap-1.5'>
                <span
                  className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${
                    buy ? 'bg-buy/15 text-buy' : 'bg-sell/15 text-sell'
                  }`}
                >
                  {buy ? 'BUY' : 'SELL'}
                </span>
                <span
                  className={`rounded bg-line/60 px-1.5 py-0.5 text-[10px] font-bold ${meta.className}`}
                >
                  {meta.label}
                </span>
              </div>
              <div className='flex justify-between gap-2 text-ink-muted'>
                <span>Time</span>
                <span className='text-ink text-right'>{formatTime(s.time)}</span>
              </div>
              {s.price !== undefined && s.price !== null && (
                <div className='flex justify-between gap-2 text-ink-muted'>
                  <span>Price</span>
                  <span className='text-ink text-right'>{s.price}</span>
                </div>
              )}
              <p className='whitespace-pre-wrap break-words text-ink'>
                {s.reason || 'No reason recorded.'}
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
});
