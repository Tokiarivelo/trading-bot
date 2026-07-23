"use client";

/**
 * Create a new bot two ways: type a free-text description of a manual
 * trading method (no PDF needed), or upload a PDF (existing pipeline). Both
 * land on the same draft review screen — nothing is ever activated
 * automatically (§8.1).
 */

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useActiveAccount } from "@/shared/api/account-context";
import { ApiError, createStrategyDraftFromText } from "@/shared/api/client";
import { StrategyJsonUploadForm } from "./StrategyJsonUploadForm";
import { StrategyUploadForm } from "./StrategyUploadForm";
import { SymbolMultiSelect } from "./SymbolMultiSelect";

const SYMBOL_QUERY_KEY = "symbol";
const LAST_SYMBOL_KEY = "tb.lastSymbol";

const PROMPT_TEMPLATES = [
  {
    label: "📈 EMA Pullback",
    text: "buy when price pulls back to the 200 EMA on H1 with RSI below 40, stop below the last swing low, target 2R",
  },
  {
    label: "⚡ Breakout Scalper",
    text: "buy when price breaks above the 20-period high on M15 with high volume, set stop 10 pips below entry, take profit at 20 pips",
  },
  {
    label: "🔄 Mean Reversion",
    text: "sell when price crosses above the upper Bollinger Band on H4 and MACD histogram turns down, stop above band high, target SMA line",
  },
];

function PromptTab() {
  const router = useRouter();
  const accountId = useActiveAccount();
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
      setError("Please describe the trading method first");
      return;
    }
    if (!accountId) return;
    setBusy(true);
    setError(null);
    try {
      const draft = await createStrategyDraftFromText(
        accountId,
        description.trim(),
        symbol ?? undefined,
      );
      router.push(`/strategies/drafts/${draft.id}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "generation failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-4 rounded-xl border border-line bg-panel p-5 shadow-lg backdrop-blur-md">
      <div className="flex flex-col gap-2">
        <label className="text-xs font-semibold text-ink-muted uppercase tracking-wider">
          AI Prompt Template Examples
        </label>
        <div className="flex flex-wrap gap-2">
          {PROMPT_TEMPLATES.map((tmpl) => (
            <button
              key={tmpl.label}
              type="button"
              onClick={() => setDescription(tmpl.text)}
              disabled={busy}
              className="cursor-pointer text-xs px-3 py-1.5 rounded-lg border border-line bg-bg/50 hover:bg-bg hover:border-accent text-ink hover:text-accent transition-all duration-200"
            >
              {tmpl.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-xs font-semibold text-ink-muted uppercase tracking-wider">
          Describe your Strategy
        </label>
        <textarea
          className="min-h-28 rounded-lg border border-line bg-bg/60 p-3 text-sm text-ink placeholder:text-ink-muted focus:border-accent focus:ring-1 focus:ring-accent focus:outline-none transition-all duration-200 resize-y"
          placeholder="Describe the trading method in natural language, e.g. 'buy when price pulls back to the 200 EMA on H1 with RSI below 40...'"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          disabled={busy}
        />
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
          type="button"
          className="cursor-pointer rounded-lg bg-accent px-5 py-2 text-sm font-semibold text-white hover:bg-accent/90 shadow-md shadow-accent/20 active:scale-95 disabled:opacity-50 disabled:pointer-events-none transition-all duration-200"
          onClick={onGenerate}
          disabled={busy}
        >
          {busy ? (
            <span className="flex items-center gap-2">
              <svg className="animate-spin h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
              </svg>
              Generating Bot...
            </span>
          ) : (
            "Generate with AI"
          )}
        </button>
      </div>

      {error && <p className="text-sm text-err font-medium mt-1">{error}</p>}
      {!symbol && (
        <p className="text-xs text-ink-muted italic">
          💡 No symbol picked — the draft will use whatever the description names (if any), and you can assign it on the review screen.
        </p>
      )}
    </div>
  );
}

const TAB_LABELS = {
  prompt: "✍️ Prompt Engine",
  pdf: "📄 PDF spec upload",
  json: "🧾 JSON spec upload",
} as const;

export function GenerateBotForm() {
  const [tab, setTab] = useState<"prompt" | "pdf" | "json">("prompt");

  return (
    <div className="flex flex-col gap-4">
      <div className="flex p-0.5 rounded-lg bg-panel border border-line self-start">
        {(Object.keys(TAB_LABELS) as (keyof typeof TAB_LABELS)[]).map((t) => (
          <button
            key={t}
            type="button"
            className={`cursor-pointer rounded-md px-4 py-1.5 text-xs font-semibold tracking-wide transition-all duration-200 ${
              tab === t
                ? "bg-accent text-white shadow-sm"
                : "text-ink-muted hover:text-ink"
            }`}
            onClick={() => setTab(t)}
          >
            {TAB_LABELS[t]}
          </button>
        ))}
      </div>
      {tab === "prompt" ? (
        <PromptTab />
      ) : tab === "pdf" ? (
        <StrategyUploadForm />
      ) : (
        <StrategyJsonUploadForm />
      )}
    </div>
  );
}
