import { memo, type Ref } from 'react';
import type { OrderSide, PendingOrderType } from '@/shared/api/client';

export interface ChartContextMenuProps {
  x: number;
  y: number;
  price: number;
  containerWidth: number;
  containerHeight: number;
  onSelectOption: (side: OrderSide, type: PendingOrderType) => void;
  /** Forwarded to the root element so ChartPanel's outside-click detection
   * can scope to this specific instance instead of a shared global DOM id
   * (see ChartPanel.tsx's click-outside effect). */
  ref?: Ref<HTMLDivElement>;
}

export const ChartContextMenu = memo(function ChartContextMenu({
  x,
  y,
  price,
  containerWidth,
  containerHeight,
  onSelectOption,
  ref,
}: ChartContextMenuProps) {
  const menuWidth = 160;
  const menuHeight = 130;
  const left = x + menuWidth > containerWidth ? x - menuWidth : x;
  const top = y + menuHeight > containerHeight ? y - menuHeight : y;

  return (
    <div
      ref={ref}
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
});
