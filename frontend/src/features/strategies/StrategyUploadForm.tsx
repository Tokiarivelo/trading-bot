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
 *
 * The PDF's text rarely names a broker instrument, so the LLM's own guess
 * defaults to XAUUSD almost every time — the symbol picker here lets the
 * trader pin the draft to the actual symbol they want a bot for (defaulting
 * to whatever's active on the chart) instead of relying on that guess. */
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
      setError("choose a PDF file first");
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
      className="flex flex-wrap items-center gap-2 rounded-md border border-line bg-panel p-3 text-sm"
    >
      <input
        className="flex-1 text-ink-muted file:mr-3 file:cursor-pointer file:rounded file:border file:border-line file:bg-bg file:px-2 file:py-1 file:text-ink"
        name="file"
        type="file"
        accept="application/pdf"
        required
      />
      <div className="flex flex-col gap-1">
        <span className="text-xs text-ink-muted">Symbol this bot is for</span>
        <SymbolMultiSelect
          value={symbol ? [symbol] : []}
          onChange={(symbols) => setSymbol(symbols[symbols.length - 1] ?? null)}
        />
      </div>
      <button
        className="cursor-pointer rounded border border-accent px-3 py-1 text-accent hover:bg-accent hover:text-bg disabled:opacity-50"
        disabled={busy}
        type="submit"
      >
        {busy ? "Extracting…" : "Upload PDF"}
      </button>
      {error && <p className="w-full text-err">{error}</p>}
      {!symbol && (
        <p className="w-full text-xs text-ink-muted">
          No symbol picked — the draft will use whatever (if anything) the PDF text names, and
          you can set it later on the review screen.
        </p>
      )}
    </form>
  );
}
