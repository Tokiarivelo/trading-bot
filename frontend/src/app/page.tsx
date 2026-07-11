"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AccountPanel } from "@/features/account/AccountPanel";
import { ChartPanel } from "@/features/chart/ChartPanel";
import { SymbolPicker } from "@/features/chart/SymbolPicker";
import { getAppConfig, getHealth, type AppConfig } from "@/shared/api/client";

const EXTRA_SYMBOLS_KEY = "tb.extraSymbols";
const SYMBOL_QUERY_KEY = "symbol";
const DEFAULT_SYMBOLS = ["XAUUSD", "XAGUSD", "BTCUSD"];

export default function Home() {
  const [backendUp, setBackendUp] = useState<boolean | null>(null);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [symbol, setSymbol] = useState("XAUUSD");
  const [extraSymbols, setExtraSymbols] = useState<string[]>([]);

  // Restore whatever was selected before a refresh: `?symbol=` wins over the
  // default, and if it's not a configured symbol it's re-added to the
  // browsed-extras list so it still shows as a chip (and its chart/live
  // stream can resume — see SymbolPicker/ChartPanel).
  useEffect(() => {
    getHealth()
      .then(() => setBackendUp(true))
      .catch(() => setBackendUp(false));
    getAppConfig().then(setConfig).catch(() => {});

    let storedExtras: string[] = [];
    try {
      const stored = localStorage.getItem(EXTRA_SYMBOLS_KEY);
      if (stored) storedExtras = JSON.parse(stored);
    } catch {
      // Ignore malformed/blocked localStorage — just start with no extras.
    }

    const urlSymbol = new URLSearchParams(window.location.search).get(SYMBOL_QUERY_KEY);
    if (urlSymbol && !DEFAULT_SYMBOLS.includes(urlSymbol) && !storedExtras.includes(urlSymbol)) {
      storedExtras = [...storedExtras, urlSymbol];
      localStorage.setItem(EXTRA_SYMBOLS_KEY, JSON.stringify(storedExtras));
    }
    setExtraSymbols(storedExtras);
    if (urlSymbol) setSymbol(urlSymbol);
  }, []);

  // Keep `?symbol=` in sync so a page refresh (or a shared/bookmarked link)
  // resumes the same chart. `replaceState` avoids piling up history entries.
  useEffect(() => {
    const url = new URL(window.location.href);
    url.searchParams.set(SYMBOL_QUERY_KEY, symbol);
    window.history.replaceState(null, "", url);
  }, [symbol]);

  const configuredSymbols = config?.symbols ?? DEFAULT_SYMBOLS;

  function addExtraSymbol(sym: string) {
    if (configuredSymbols.includes(sym) || extraSymbols.includes(sym)) {
      setSymbol(sym);
      return;
    }
    const updated = [...extraSymbols, sym];
    setExtraSymbols(updated);
    localStorage.setItem(EXTRA_SYMBOLS_KEY, JSON.stringify(updated));
    setSymbol(sym);
  }

  function removeExtraSymbol(sym: string) {
    const updated = extraSymbols.filter((s) => s !== sym);
    setExtraSymbols(updated);
    localStorage.setItem(EXTRA_SYMBOLS_KEY, JSON.stringify(updated));
    if (symbol === sym) setSymbol(configuredSymbols[0]);
  }

  return (
    <div className="flex h-screen flex-col">
      <header className="flex items-center gap-4 border-b border-line px-4 py-2">
        <h1 className="text-base font-bold">AI Trading Bot</h1>
        {config && (
          <span
            className={`rounded px-2 py-0.5 text-xs font-bold ${
              config.mode === "live" ? "bg-err text-[#2b0808]" : "bg-ok text-[#04211e]"
            }`}
          >
            {config.mode.toUpperCase()}
          </span>
        )}
        <nav className="flex items-center gap-1">
          {configuredSymbols.map((s) => (
            <button
              key={s}
              className={`cursor-pointer rounded border px-3 py-1 ${
                s === symbol ? "border-accent text-accent" : "border-line text-ink"
              }`}
              onClick={() => setSymbol(s)}
            >
              {s}
            </button>
          ))}
          {extraSymbols.map((s) => (
            <span
              key={s}
              className={`flex items-center gap-1 rounded border px-2 py-1 ${
                s === symbol ? "border-accent text-accent" : "border-line text-ink-muted"
              }`}
              title="Browsed from the broker's catalog — not a configured trading symbol"
            >
              <button className="cursor-pointer" onClick={() => setSymbol(s)}>
                {s}
              </button>
              <button
                className="cursor-pointer text-ink-muted hover:text-err"
                onClick={() => removeExtraSymbol(s)}
                title={`Remove ${s}`}
              >
                ×
              </button>
            </span>
          ))}
          <SymbolPicker onAdd={addExtraSymbol} />
        </nav>
        <Link href="/strategies" className="ml-auto text-sm text-ink-muted hover:text-accent">
          Strategies
        </Link>
        <Link href="/backtest" className="text-sm text-ink-muted hover:text-accent">
          Backtests
        </Link>
        <Link href="/ai-reports" className="text-sm text-ink-muted hover:text-accent">
          AI Reports
        </Link>
        <span className="text-sm">
          backend:{" "}
          {backendUp === null ? (
            "…"
          ) : backendUp ? (
            <em className="not-italic text-ok">connected</em>
          ) : (
            <em className="not-italic text-err">offline</em>
          )}
        </span>
      </header>

      <main className="flex min-h-0 flex-1">
        <ChartPanel symbol={symbol} />
        <aside className="flex w-[300px] flex-col gap-2 overflow-y-auto border-l border-line p-2">
          <AccountPanel />
          <Panel>Bot control (Phase 4)</Panel>
          <Panel>Journal (Phase 3)</Panel>
          <Panel>
            <Link href="/strategies" className="text-accent hover:underline">
              Strategies →
            </Link>{" "}
            PDF upload, spec review, AI codegen, versions
          </Panel>
          <Panel>
            <Link href="/ai-reports" className="text-accent hover:underline">
              AI reviews →
            </Link>{" "}
            10-trade reviews, refinement proposals, backtest comparisons
          </Panel>
          <Panel>News (Phase 8)</Panel>
        </aside>
      </main>
    </div>
  );
}

function Panel({ children }: { children: React.ReactNode }) {
  return (
    <section className="rounded-md border border-line bg-panel p-3 text-sm">{children}</section>
  );
}
