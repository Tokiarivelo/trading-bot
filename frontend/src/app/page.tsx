"use client";

import { useEffect, useState } from "react";
import { AccountPanel } from "@/features/account/AccountPanel";
import { ChartPanel } from "@/features/chart/ChartPanel";
import { getAppConfig, getHealth, type AppConfig } from "@/shared/api/client";

export default function Home() {
  const [backendUp, setBackendUp] = useState<boolean | null>(null);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [symbol, setSymbol] = useState("XAUUSD");

  useEffect(() => {
    getHealth()
      .then(() => setBackendUp(true))
      .catch(() => setBackendUp(false));
    getAppConfig().then(setConfig).catch(() => {});
  }, []);

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
        <nav className="flex gap-1">
          {(config?.symbols ?? ["XAUUSD", "XAGUSD", "BTCUSD"]).map((s) => (
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
        </nav>
        <span className="ml-auto text-sm">
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
          <Panel>AI reports (Phase 6–7)</Panel>
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
