import { memo, useState } from 'react';
import type { PositionOut } from '@/shared/api/client';
import { numOrNull } from './chartFormat';

export interface PositionEditPopoverProps {
  position: PositionOut;
  top: number;
  busy: boolean;
  onClose: () => void;
  onSave: (sl: number | null, tp: number | null) => void;
  onClosePosition: () => void;
}

/** Double-click editor for a running position's entry line: SL/TP fields
 * plus a close button, positioned at the entry line's current pixel row. */
export const PositionEditPopover = memo(function PositionEditPopover({
  position,
  top,
  busy,
  onClose,
  onSave,
  onClosePosition,
}: PositionEditPopoverProps) {
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
});
