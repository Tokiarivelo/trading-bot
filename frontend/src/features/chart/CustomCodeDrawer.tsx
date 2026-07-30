'use client';

/** "Run Custom Code" slide-in drawer for ChartPanel's backtest view: a raw
 * Python editor that evaluates a custom script in the sandbox and overlays
 * its signals/indicators on the chart without persisting a strategy version.
 * Split out of ChartPanel.tsx (which also renders the "Edit Strategy Code"
 * drawer via the dynamically-imported BacktestStrategyEditor) so this
 * drawer's own copy of @uiw/react-codemirror + @codemirror/lang-python +
 * @uiw/codemirror-theme-github can be dynamically imported too — those are
 * heavy editor/language-mode packages only needed once this drawer is
 * actually opened, not on the main chart route's initial load. */

import { python } from '@codemirror/lang-python';
import { githubDarkInit } from '@uiw/codemirror-theme-github';
import CodeMirror from '@uiw/react-codemirror';
import { memo } from 'react';
import type { EvaluateCustomCodeResponse } from '@/shared/api/client';
import type { DrawerPosition } from './useStrategyEditor';

const cmTheme = githubDarkInit({
  settings: {
    background: 'var(--color-bg)',
    gutterBackground: 'var(--color-bg)',
    lineHighlight: 'var(--color-panel)',
    foreground: 'var(--color-ink)',
    caret: 'var(--color-accent)',
    selection: 'color-mix(in srgb, var(--color-accent) 30%, transparent)',
  },
});

export interface CustomCodeDrawerProps {
  drawerPosition: DrawerPosition;
  setDrawerPosition: (pos: DrawerPosition) => void;
  customCodeDraft: string;
  setCustomCodeDraft: (value: string) => void;
  customCodeCopied: boolean;
  handleCopyCustomCode: () => void;
  customCodeBusy: boolean;
  customCodeError: string | null;
  customCodeResult: EvaluateCustomCodeResponse | null;
  runCustomCode: () => void;
  clearCustomCode: () => void;
  /** Called by the header's close button — combines hiding the drawer with
   * clearing any evaluated preview result (owned by ChartPanel, which also
   * needs to reset the chart's overlaid signals/indicators on close). */
  onClose: () => void;
}

export const CustomCodeDrawer = memo(function CustomCodeDrawer({
  drawerPosition,
  setDrawerPosition,
  customCodeDraft,
  setCustomCodeDraft,
  customCodeCopied,
  handleCopyCustomCode,
  customCodeBusy,
  customCodeError,
  customCodeResult,
  runCustomCode,
  clearCustomCode,
  onClose,
}: CustomCodeDrawerProps) {
  return (
    <div
      className={`pointer-events-auto absolute z-40 flex flex-col bg-panel border-line shadow-2xl overflow-hidden ${
        drawerPosition === 'right'
          ? 'right-0 top-0 h-full border-l'
          : drawerPosition === 'left'
            ? 'left-0 top-0 h-full border-r'
            : drawerPosition === 'bottom'
              ? 'bottom-0 left-0 w-full border-t'
              : 'top-0 left-0 w-full border-b'
      }`}
      style={{
        width:
          drawerPosition === 'right' || drawerPosition === 'left'
            ? '420px'
            : '100%',
        height:
          drawerPosition === 'bottom' || drawerPosition === 'top'
            ? '340px'
            : '100%',
        maxWidth:
          drawerPosition === 'right' || drawerPosition === 'left'
            ? '55%'
            : undefined,
        maxHeight:
          drawerPosition === 'bottom' || drawerPosition === 'top'
            ? '55%'
            : undefined,
      }}
    >
      {/* Drawer header */}
      <div className='flex items-center gap-2 border-b border-line px-3 py-1.5 bg-panel shrink-0'>
        <span className='text-xs font-semibold text-ink truncate'>
          Run Custom Code
        </span>
        {/* Position controls */}
        <div className='flex items-center gap-0.5 ml-auto'>
          <button
            onClick={handleCopyCustomCode}
            className={`cursor-pointer mr-1.5 rounded px-2 py-0.5 text-[10px] border transition-colors ${
              customCodeCopied
                ? 'border-ok text-ok bg-ok/10'
                : 'border-line text-ink-muted hover:text-accent hover:border-accent'
            }`}
            title='Copy code'
          >
            {customCodeCopied ? 'Copied!' : 'Copy'}
          </button>
          {(['right', 'bottom', 'left', 'top'] as const).map((pos) => (
            <button
              key={pos}
              onClick={() => setDrawerPosition(pos)}
              title={`Move to ${pos}`}
              className={`cursor-pointer rounded px-1.5 py-0.5 text-[10px] border transition-colors ${
                drawerPosition === pos
                  ? 'border-accent text-accent bg-accent/10'
                  : 'border-line text-ink-muted hover:text-ink'
              }`}
            >
              {pos === 'right'
                ? '⇥'
                : pos === 'left'
                  ? '⇤'
                  : pos === 'bottom'
                    ? '⇓'
                    : '⇑'}
            </button>
          ))}
          <button
            onClick={onClose}
            className='cursor-pointer ml-1 rounded border border-line px-1.5 py-0.5 text-[10px] text-ink-muted hover:border-err hover:text-err transition-colors'
            title='Close drawer'
          >
            ✕
          </button>
        </div>
      </div>
      {/* Drawer content */}
      <div className='flex-1 flex flex-col p-2 min-h-0'>
        <div className='flex-1 flex flex-col min-h-0 rounded-md border border-line bg-panel'>
          <CodeMirror
            value={customCodeDraft}
            height='100%'
            className='flex-1 min-h-0 overflow-auto'
            theme={cmTheme}
            extensions={[python()]}
            onChange={setCustomCodeDraft}
            editable={!customCodeBusy}
          />

          {customCodeError && (
            <div className='border-t border-line px-3 py-2 text-xs text-err shrink-0 max-h-32 overflow-y-auto'>
              <p>{customCodeError}</p>
            </div>
          )}

          {customCodeResult && (
            <div className='border-t border-line px-3 py-1.5 text-xs text-ok shrink-0 bg-panel/30 flex items-center justify-between'>
              <span>
                Success: {customCodeResult.signals.length} signal(s),{' '}
                {Object.keys(customCodeResult.indicators).length}{' '}
                indicator(s) calculated
              </span>
              <button
                onClick={clearCustomCode}
                className='cursor-pointer px-1.5 py-0.5 rounded border border-line hover:border-ink hover:text-ink text-[10px] text-ink-muted'
              >
                Reset Graph
              </button>
            </div>
          )}

          <div className='flex items-center gap-2 border-t border-line p-3 shrink-0'>
            <button
              type='button'
              className='cursor-pointer rounded border border-accent px-3 py-1 text-xs text-accent hover:bg-accent hover:text-bg disabled:cursor-not-allowed disabled:opacity-50'
              disabled={customCodeBusy}
              onClick={runCustomCode}
            >
              {customCodeBusy ? 'Running code...' : 'Run & Show on Graph'}
            </button>
            <span className='text-[10px] text-ink-muted'>
              Evaluates custom Python strategy. Returns moving averages/indicators
              & buy/sell signals on graph.
            </span>
          </div>
        </div>
      </div>
    </div>
  );
});
