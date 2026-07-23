"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useActiveAccount } from "@/shared/api/account-context";
import { ApiError, createStrategyDraftFromJson } from "@/shared/api/client";
import { SymbolMultiSelect } from "./SymbolMultiSelect";

const SYMBOL_QUERY_KEY = "symbol";
const LAST_SYMBOL_KEY = "tb.lastSymbol";

const EXAMPLE_SPEC = `{
  "name": "gold_ema_pullback",
  "symbols": ["XAUUSD"],
  "entry_timeframe": "M5",
  "confirmation_timeframes": ["H1"],
  "indicators": [{ "type": "ema", "period": 200, "label": "EMA200" }],
  "entry_rules": "Buy when price pulls back to EMA200 in an uptrend.",
  "exit_rules": "SL below the last swing low, TP at 2R.",
  "risk_notes": "Risk 0.5% per trade.",
  "params": { "ema_period": 200 }
}`;

/** Upload a strategy spec already structured as JSON (name, entry/exit
 * rules, indicators, …) — skips the LLM extraction step, landing on the
 * same draft review screen as PDF/prompt upload; nothing is ever activated
 * automatically (§8.1). */
export function StrategyJsonUploadForm() {
  const router = useRouter();
  const accountId = useActiveAccount();
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
      setError("Please choose a JSON file first");
      return;
    }
    if (!accountId) return;
    setBusy(true);
    setError(null);
    try {
      let parsed: unknown;
      try {
        parsed = JSON.parse(await file.text());
      } catch {
        throw new Error("That file isn't valid JSON");
      }
      if (
        typeof parsed !== "object" ||
        parsed === null ||
        !("name" in parsed) ||
        !("entry_timeframe" in parsed) ||
        !("indicators" in parsed)
      ) {
        throw new Error(
          "That JSON doesn't look like a strategy spec — see 'Expected JSON shape' below",
        );
      }
      const draft = await createStrategyDraftFromJson(
        accountId,
        parsed as Parameters<typeof createStrategyDraftFromJson>[1],
        symbol ?? undefined,
      );
      router.push(`/strategies/drafts/${draft.id}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : e instanceof Error ? e.message : "upload failed");
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
          Upload Strategy Spec JSON
        </label>
        <div className="relative flex items-center justify-center border-2 border-dashed border-line hover:border-accent/50 rounded-lg p-6 bg-bg/30 hover:bg-bg/50 transition-all duration-200">
          <input
            className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
            name="file"
            type="file"
            accept="application/json,.json"
            required
            disabled={busy}
          />
          <div className="text-center pointer-events-none">
            <svg className="mx-auto h-8 w-8 text-ink-muted mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
            </svg>
            <p className="text-sm text-ink font-medium">Click to upload or drag & drop</p>
            <p className="text-xs text-ink-muted mt-1">A structured strategy spec — see the example below</p>
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
          {busy ? "Uploading..." : "Upload JSON"}
        </button>
      </div>

      {error && <p className="text-sm text-err font-medium mt-1">{error}</p>}
      {!symbol && (
        <p className="text-xs text-ink-muted italic">
          💡 No symbol picked — the draft will use whatever the JSON's `symbols` field says, and
          you can change it on the review screen.
        </p>
      )}

      <details className="text-xs text-ink-muted">
        <summary className="cursor-pointer select-none hover:text-accent">Expected JSON shape</summary>
        <pre className="mt-2 overflow-x-auto rounded-lg border border-line bg-bg/60 p-3 text-[11px] leading-relaxed">
{EXAMPLE_SPEC}
        </pre>
        <p className="mt-1">
          Fields: name, symbols[], entry_timeframe, confirmation_timeframes[], indicators[]
          (type: ema/sma/rsi/macd/bollinger, period, label), entry_rules, exit_rules, risk_notes,
          params. Optional: unrecognized_indicators[], price_levels[], chart_notes[]. Tip: approve
          any AI-generated draft and inspect its spec on the review screen for a real example.
        </p>
      </details>
    </form>
  );
}
