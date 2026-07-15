"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ApiError, uploadStrategyPdf } from "@/shared/api/client";
import { SymbolMultiSelect } from "./SymbolMultiSelect";

// Same URL param / localStorage key the chart page (app/page.tsx) uses for
// its active symbol, so "Strategies" links from the chart carry it over and
// this form defaults to whatever the trader was actually looking at.
const SYMBOL_QUERY_KEY = "symbol";
const LAST_SYMBOL_KEY = "tb.lastSymbol";

/** Upload a PDF describing a manual trading method; on success, jumps to the
 * new draft's review screen (§8.1 — nothing is ever activated automatically,
 * this only produces something for the user to review).
 */
export function StrategyUploadForm() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [symbol, setSymbol] = useState<string | null>(null);

  useEffect(() => {
    const urlSymbol = new URLSearchParams(window.location.search).get(SYMBOL_QUERY_KEY);
    if (urlSymbol) {
      setSymbol(urlSymbol);
      return;
    }
    try {
      setSymbol(localStorage.getItem(LAST_SYMBOL_KEY));
    } catch {
      // Ignore blocked localStorage — the picker just starts empty.
    }
  }, []);

  async function onUpload(form: FormData) {
    const file = form.get("file");
    if (!(file instanceof File) || file.size === 0) {
      setError("Please choose a PDF file first");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const draft = await uploadStrategyPdf(file, symbol ?? undefined);
      router.push(`/strategies/drafts/${draft.id}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "upload failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      action={onUpload}
      className="flex flex-col gap-4 rounded-xl border border-line bg-panel p-5 shadow-lg backdrop-blur-md"
    >
      <div className="flex flex-col gap-1.5">
        <label className="text-xs font-semibold text-ink-muted uppercase tracking-wider">
          Upload Strategy PDF Spec
        </label>
        <div className="relative flex items-center justify-center border-2 border-dashed border-line hover:border-accent/50 rounded-lg p-6 bg-bg/30 hover:bg-bg/50 transition-all duration-200">
          <input
            className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
            name="file"
            type="file"
            accept="application/pdf"
            required
            disabled={busy}
          />
          <div className="text-center pointer-events-none">
            <svg className="mx-auto h-8 w-8 text-ink-muted mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
            </svg>
            <p className="text-sm text-ink font-medium">Click to upload or drag & drop</p>
            <p className="text-xs text-ink-muted mt-1">PDF strategy guide, rules or cheat sheets</p>
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-end justify-between gap-4 border-t border-line/50 pt-4">
        <div className="flex flex-col gap-1.5">
          <span className="text-xs font-semibold text-ink-muted uppercase tracking-wider">Target Symbol</span>
          <SymbolMultiSelect
            value={symbol ? [symbol] : []}
            onChange={(symbols) => setSymbol(symbols[symbols.length - 1] ?? null)}
            disabled={busy}
          />
        </div>
        <button
          className="cursor-pointer rounded-lg bg-accent px-5 py-2 text-sm font-semibold text-white hover:bg-accent/90 shadow-md shadow-accent/20 active:scale-95 disabled:opacity-50 disabled:pointer-events-none transition-all duration-200"
          disabled={busy}
          type="submit"
        >
          {busy ? (
            <span className="flex items-center gap-2">
              <svg className="animate-spin h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
              </svg>
              Extracting PDF...
            </span>
          ) : (
            "Upload PDF"
          )}
        </button>
      </div>

      {error && <p className="text-sm text-err font-medium mt-1">{error}</p>}
      {!symbol && (
        <p className="text-xs text-ink-muted italic">
          💡 No symbol picked — the draft will use whatever the PDF mentions, and you can change it on the review screen.
        </p>
      )}
    </form>
  );
}
