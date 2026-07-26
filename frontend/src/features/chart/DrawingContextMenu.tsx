import { memo, type Ref } from 'react';

export interface DrawingContextMenuProps {
  x: number;
  y: number;
  drawingType: string;
  containerWidth: number;
  containerHeight: number;
  onSelectEdit: () => void;
  onDelete: () => void;
  /** Forwarded to the root element so ChartPanel's outside-click detection
   * can scope to this specific instance instead of a shared global DOM id
   * (see ChartPanel.tsx's click-outside effect). */
  ref?: Ref<HTMLDivElement>;
}

export const DrawingContextMenu = memo(function DrawingContextMenu({
  x,
  y,
  drawingType,
  containerWidth,
  containerHeight,
  onSelectEdit,
  onDelete,
  ref,
}: DrawingContextMenuProps) {
  const menuWidth = 160;
  const menuHeight = 100;
  const left = x + menuWidth > containerWidth ? x - menuWidth : x;
  const top = y + menuHeight > containerHeight ? y - menuHeight : y;

  const typeLabels: Record<string, string> = {
    'trend-line': 'Trend Line',
    'extended-line': 'Extended Line',
    'horizontal-line': 'Horizontal Line',
    'vertical-line': 'Vertical Line',
    rectangle: 'Rectangle',
    'fib-retracement': 'Fibonacci Retr.',
    'parallel-channel': 'Parallel Channel',
    circle: 'Circle',
    'long-position': 'Long Position',
    'short-position': 'Short Position',
  };

  return (
    <div
      ref={ref}
      className='pointer-events-auto absolute z-30 flex w-40 flex-col rounded border border-line bg-panel py-1 text-xs shadow-xl backdrop-blur-sm bg-opacity-95'
      style={{ left: `${left}px`, top: `${top}px` }}
      onMouseDown={(e) => e.stopPropagation()}
    >
      <div className='border-b border-line px-2 py-1 text-[10px] font-semibold text-ink-muted'>
        {typeLabels[drawingType] || drawingType}
      </div>
      <button
        onClick={onSelectEdit}
        className='w-full text-left px-2 py-1.5 hover:bg-line text-ink transition-colors font-semibold flex items-center gap-1.5 cursor-pointer'
      >
        <span>✏️</span> Edit Style
      </button>
      <button
        onClick={onDelete}
        className='w-full text-left px-2 py-1.5 hover:bg-line text-err transition-colors font-semibold flex items-center gap-1.5 cursor-pointer'
      >
        <span>🗑️</span> Delete
      </button>
    </div>
  );
});
