'use client';

/**
 * Compact view/edit panel for a saved custom indicator's Python source,
 * opened from a chip in IndicatorsDock — lets a trader see/change an
 * indicator's code without leaving the chart. Saving calls the same
 * POST /indicators/{id}/edit the full /indicators management page uses;
 * every chart currently using this indicator picks up the new code on its
 * next compute. Full history/duplicate/delete stay on the /indicators page
 * (linked at the bottom) — this stays intentionally small.
 */

import { python } from '@codemirror/lang-python';
import { githubDarkInit } from '@uiw/codemirror-theme-github';
import CodeMirror from '@uiw/react-codemirror';
import Link from 'next/link';
import { useEffect, useState } from 'react';
import { ApiError, editIndicatorCode, getIndicator } from '@/shared/api/client';

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

export function IndicatorCodePeek({
  indicatorId,
  indicatorName,
  onClose,
  onSaved,
}: {
  indicatorId: string;
  indicatorName: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [code, setCode] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getIndicator(indicatorId)
      .then((d) => {
        setCode(d.code);
        setDraft(d.code);
      })
      .catch(() => setError('failed to load indicator code'));
  }, [indicatorId]);

  async function onSave() {
    setBusy(true);
    setError(null);
    try {
      await editIndicatorCode(indicatorId, draft);
      setCode(draft);
      onSaved();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'save failed');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="pointer-events-auto fixed inset-0 z-40 flex items-center justify-center bg-black/40"
      onMouseDown={onClose}
    >
      <div
        className="flex max-h-[80vh] w-[36rem] max-w-[90vw] flex-col rounded-md border border-line bg-panel shadow-xl"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between gap-2 border-b border-line px-3 py-2 text-sm">
          <span className="font-semibold text-ink">{indicatorName}</span>
          <div className="flex items-center gap-2">
            <Link
              href={`/indicators/${indicatorId}`}
              className="text-xs text-ink-muted hover:text-accent"
            >
              Manage indicators →
            </Link>
            <button
              type="button"
              onClick={onClose}
              className="cursor-pointer text-ink-muted hover:text-ink"
              title="Close"
            >
              ×
            </button>
          </div>
        </header>
        {error && <p className="border-b border-line px-3 py-2 text-xs text-err">{error}</p>}
        {code === null ? (
          <p className="p-3 text-xs text-ink-muted">Loading…</p>
        ) : (
          <>
            <CodeMirror
              value={draft}
              height="20rem"
              theme={cmTheme}
              extensions={[python()]}
              onChange={setDraft}
            />
            <div className="flex gap-2 border-t border-line p-2">
              <button
                type="button"
                disabled={busy || draft === code}
                onClick={onSave}
                className="cursor-pointer rounded border border-accent px-2 py-1 text-xs text-accent hover:bg-accent hover:text-bg disabled:cursor-not-allowed disabled:opacity-50"
              >
                {busy ? 'Saving…' : 'Save'}
              </button>
              <button
                type="button"
                onClick={onClose}
                className="cursor-pointer rounded border border-line px-2 py-1 text-xs hover:border-accent hover:text-accent"
              >
                Close
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
