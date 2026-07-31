import { memo, type MutableRefObject, type Ref } from 'react';
import type { DrawingManager } from 'lightweight-charts-drawing';

export interface DrawingEditPopoverProps {
  x: number;
  y: number;
  drawingId: string;
  drawingType: string;
  containerWidth: number;
  containerHeight: number;
  manager: DrawingManager | null;
  originalStylesRef: MutableRefObject<Record<string, any>>;
  onClose: () => void;
  onSaveAndSync: () => void;
  onColorChange: (id: string, color: string) => void;
  onWidthChange?: (width: number) => void;
  /** Forwarded to the root element so ChartPanel's outside-click detection
   * can scope to this specific instance instead of a shared global DOM id
   * (see ChartPanel.tsx's click-outside effect). */
  ref?: Ref<HTMLDivElement>;
}

export const DrawingEditPopover = memo(function DrawingEditPopover({
  x,
  y,
  drawingId,
  drawingType,
  containerWidth,
  containerHeight,
  manager,
  originalStylesRef,
  onClose,
  onSaveAndSync,
  onColorChange,
  onWidthChange,
  ref,
}: DrawingEditPopoverProps) {
  const popoverWidth = 180;
  const popoverHeight = 160;
  const left = x + popoverWidth > containerWidth ? x - popoverWidth : x;
  const top = y + popoverHeight > containerHeight ? y - popoverHeight : y;

  const drawing = manager?.getDrawing(drawingId);
  const isLocked = drawing?.options?.locked === true;
  const isVisible = drawing?.options?.visible !== false;

  const backup = originalStylesRef.current[drawingId];
  const activeColor =
    backup?.lineColor || drawing?.style?.lineColor || '#2962ff';
  const activeWidth = backup?.lineWidth || drawing?.style?.lineWidth || 2;

  const PRESET_COLORS = [
    '#2962ff', // Blue
    '#26a69a', // Green
    '#ef5350', // Red
    '#ff9800', // Orange
    '#9c27b0', // Purple
    '#ffffff', // White
  ];

  const handleLockToggle = () => {
    if (drawing) {
      const nextLocked = !isLocked;
      drawing.updateOptions({ locked: nextLocked });
      onSaveAndSync();
    }
  };

  const handleVisibleToggle = () => {
    if (drawing) {
      const nextVisible = !isVisible;
      drawing.updateOptions({ visible: nextVisible });
      onSaveAndSync();
    }
  };

  const handleWidthChange = (width: number) => {
    if (drawing) {
      if (originalStylesRef.current[drawingId]) {
        originalStylesRef.current[drawingId].lineWidth = width;
      } else {
        drawing.updateStyle({ lineWidth: width });
      }
      onSaveAndSync();
      onWidthChange?.(width);
    }
  };

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
      className='pointer-events-auto absolute z-30 flex w-44 flex-col gap-2 rounded border border-line bg-panel p-3 text-xs shadow-xl backdrop-blur-sm bg-opacity-95'
      style={{ left: `${left}px`, top: `${top}px` }}
      onMouseDown={(e) => e.stopPropagation()}
    >
      <div className='flex items-center justify-between border-b border-line pb-1'>
        <span className='font-bold text-ink'>
          {typeLabels[drawingType] || 'Edit Drawing'}
        </span>
        <button
          onClick={onClose}
          className='cursor-pointer text-ink-muted hover:text-ink text-sm font-bold'
          title='Close'
        >
          ×
        </button>
      </div>

      <div className='flex flex-col gap-1'>
        <label className='text-[10px] text-ink-muted'>Color</label>
        <div className='flex items-center gap-1 flex-wrap'>
          {PRESET_COLORS.map((c) => (
            <button
              key={c}
              onClick={() => onColorChange(drawingId, c)}
              className={`cursor-pointer rounded-full border hover:scale-110 transition-transform ${
                activeColor === c ? 'border-ink scale-105' : 'border-line'
              }`}
              style={{
                width: 16,
                height: 16,
                backgroundColor: c,
              }}
              title={c}
            />
          ))}
          <input
            type='color'
            value={activeColor}
            onChange={(e) => onColorChange(drawingId, e.target.value)}
            className='color-picker-input cursor-pointer'
            style={{
              width: 16,
              height: 16,
              border: 'none',
              padding: 0,
              background: 'none',
            }}
            title='Custom color'
          />
        </div>
      </div>

      <div className='flex flex-col gap-1'>
        <label className='text-[10px] text-ink-muted'>Thickness</label>
        <div className='flex gap-1'>
          {[1, 2, 3, 4].map((w) => (
            <button
              key={w}
              onClick={() => handleWidthChange(w)}
              className={`flex-1 py-0.5 rounded border text-[10px] text-center transition-colors cursor-pointer ${
                activeWidth === w
                  ? 'border-accent text-accent font-bold bg-line'
                  : 'border-line text-ink-muted hover:text-ink'
              }`}
            >
              {w}px
            </button>
          ))}
        </div>
      </div>

      <div className='flex items-center justify-between mt-1 border-t border-line pt-2'>
        <button
          onClick={handleVisibleToggle}
          className={`flex items-center gap-1.5 px-2 py-1 rounded border text-[10px] cursor-pointer transition-colors ${
            isVisible
              ? 'border-line text-ink hover:bg-line'
              : 'border-err border-opacity-50 text-err hover:bg-err hover:bg-opacity-10'
          }`}
          title={isVisible ? 'Hide drawing' : 'Show drawing'}
        >
          <span>{isVisible ? '👁️ Visible' : '🚫 Hidden'}</span>
        </button>

        <button
          onClick={handleLockToggle}
          className={`flex items-center gap-1.5 px-2 py-1 rounded border text-[10px] cursor-pointer transition-colors ${
            isLocked
              ? 'border-err border-opacity-50 text-err hover:bg-err hover:bg-opacity-10'
              : 'border-line text-ink hover:bg-line'
          }`}
          title={isLocked ? 'Unlock drawing' : 'Lock drawing'}
        >
          <span>{isLocked ? '🔒 Locked' : '🔓 Unlocked'}</span>
        </button>
      </div>
    </div>
  );
});
