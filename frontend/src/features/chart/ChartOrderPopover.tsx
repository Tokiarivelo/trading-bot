import { memo, useState, type Ref } from 'react';
import type { OrderSide, PendingOrderType } from '@/shared/api/client';
import { numOrNull } from './chartFormat';

export interface ChartOrderPopoverProps {
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
  /** Forwarded to the root element so ChartPanel's outside-click detection
   * can scope to this specific instance instead of a shared global DOM id
   * (see ChartPanel.tsx's click-outside effect). */
  ref?: Ref<HTMLDivElement>;
}

export const ChartOrderPopover = memo(function ChartOrderPopover({
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
  ref,
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
  const buttonTextClass = 'text-white';

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
      ref={ref}
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
});
