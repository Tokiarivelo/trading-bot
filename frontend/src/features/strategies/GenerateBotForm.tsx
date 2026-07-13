"use client";

/**
 * Create a new bot two ways: type a free-text description of a manual
 * trading method (no PDF needed), or upload a PDF (existing pipeline). Both
 * land on the same draft review screen — nothing is ever activated
 * automatically (§8.1).
 */

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ApiError, createStrategyDraftFromText } from "@/shared/api/client";
import { StrategyUploadForm } from "./StrategyUploadForm";
import { SymbolMultiSelect } from "./SymbolMultiSelect";

const SYMBOL_QUERY_KEY = "symbol";
const LAST_SYMBOL_KEY = "tb.lastSymbol";

function PromptTab() {
  const router = useRouter();
  const [description, setDescription] = useState("");
  const [symbol, setSymbol] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

  async function onGenerate() {
    if (!description.trim()) {
      setError("describe the trading method first");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const draft = await createStrategyDraftFromText(description.trim(), symbol ?? undefined);
      router.push(`/strategies/drafts/${draft.id}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "generation failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-2 rounded-md border border-line bg-panel p-3 text-sm">
      <textarea
        className="min-h-24 rounded border border-line bg-bg px-2 py-1 text-sm text-ink placeholder:text-ink-muted focus:border-accent focus:outline-none"
        placeholder="Describe the trading method, e.g. 'buy when price pulls back to the 200 EMA on H1 with RSI below 40, stop below the last swing low, target 2R'…"
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        disabled={busy}
      />
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex flex-col gap-1">
          <span className="text-xs text-ink-muted">Symbol this bot is for</span>
          <SymbolMultiSelect
            value={symbol ? [symbol] : []}
            onChange={(symbols) => setSymbol(symbols[symbols.length - 1] ?? null)}
            disabled={busy}
          />
        </div>
        <button
          type="button"
          className="cursor-pointer rounded border border-accent px-3 py-1 text-accent hover:bg-accent hover:text-bg disabled:opacity-50"
          onClick={onGenerate}
          disabled={busy}
        >
          {busy ? "Generating…" : "Generate with AI"}
        </button>
      </div>
      {error && <p className="text-err">{error}</p>}
      {!symbol && (
        <p className="text-xs text-ink-muted">
          No symbol picked — the draft will use whatever (if anything) the description names,
          and you can set it later on the review screen.
        </p>
      )}
    </div>
  );
}

export function GenerateBotForm() {
  const [tab, setTab] = useState<"prompt" | "pdf">("prompt");

  return (
    <div className="flex flex-col gap-2">
      <div className="flex gap-1 text-xs">
        {(["prompt", "pdf"] as const).map((t) => (
          <button
            key={t}
            type="button"
            className={`cursor-pointer rounded px-2 py-1 ${
              tab === t
                ? "bg-accent text-bg"
                : "border border-line text-ink-muted hover:text-ink"
            }`}
            onClick={() => setTab(t)}
          >
            {t === "prompt" ? "From prompt" : "From PDF"}
          </button>
        ))}
      </div>
      {tab === "prompt" ? <PromptTab /> : <StrategyUploadForm />}
    </div>
  );
}
