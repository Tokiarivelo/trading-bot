"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import {
  Group as ResizableGroup,
  Panel as ResizablePanel,
  type PanelImperativeHandle,
  Separator as ResizableSeparator,
} from "react-resizable-panels";
import { AccountPanel } from "@/features/account/AccountPanel";
import { ChartPanel } from "@/features/chart/ChartPanel";
import { SymbolPicker } from "@/features/chart/SymbolPicker";
import { EngineControlPanel } from "@/features/engine/EngineControlPanel";
import { ActiveNewsWindowsSummary } from "@/features/news/ActiveNewsWindowsSummary";
import { BotSelector } from "@/features/strategies/BotSelector";
import { useActiveStrategyForSymbol } from "@/features/strategies/useActiveStrategyForSymbol";
import { OrdersDock } from "@/features/trading/OrdersDock";
import { TradePanel } from "@/features/trading/TradePanel";
import { useAllPositions } from "@/features/trading/useAllPositions";
import { useTrading } from "@/features/trading/useTrading";
import { getAppConfig, getHealth, type AppConfig } from "@/shared/api/client";
import { MenuButton } from "@/shared/ui/NavigationDrawer";

const EXTRA_SYMBOLS_KEY = "tb.extraSymbols";
const FAVORITE_SYMBOLS_KEY = "tb.favoriteSymbols";
const FAVORITES_MIGRATED_KEY = "tb.favoritesMigrated";
const LAST_SYMBOL_KEY = "tb.lastSymbol";
const SYMBOL_QUERY_KEY = "symbol";
const BACKTEST_REPORT_QUERY_KEY = "backtestReport";
// Last-resort fallback when nothing else (URL, last-viewed, favorites,
// engine config) can resolve an initial symbol — e.g. the very first load
// with the backend unreachable. Not used as the nav bar's default chip set
// anymore — see favoriteSymbols below.
const DEFAULT_SYMBOLS = ["XAUUSD", "XAGUSD", "BTCUSD"];

function readJsonList(key: string): string[] {
  try {
    const stored = localStorage.getItem(key);
    return stored ? JSON.parse(stored) : [];
  } catch {
    return [];
  }
}

function writeJsonList(key: string, value: string[]) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Ignore blocked/full localStorage — favorites/extras just won't persist.
  }
}

export default function Home() {
  const sidebarPanelRef = useRef<PanelImperativeHandle>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  function toggleSidebar() {
    const panel = sidebarPanelRef.current;
    if (!panel) return;
    if (panel.isCollapsed()) {
      panel.expand();
      setSidebarCollapsed(false);
    } else {
      panel.collapse();
      setSidebarCollapsed(true);
    }
  }

  const [backendUp, setBackendUp] = useState<boolean | null>(null);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [symbol, setSymbol] = useState<string | null>(null);
  const [extraSymbols, setExtraSymbols] = useState<string[]>([]);
  const [favoriteSymbols, setFavoriteSymbols] = useState<string[]>([]);
  // Set from `?backtestReport=` (arrived via "View on chart" on a backtest
  // report) — tells ChartPanel to overlay that report's trades on the
  // candle history they actually traded on, instead of the live journal's.
  const [backtestReportId, setBacktestReportId] = useState<string | null>(null);
  // Which bot's "eye" is on — its live signal trail + own positions/profit
  // overlaid on the chart, mutually exclusive with backtest view (see
  // toggleLiveBotSignals below and BotSelector's `signalsDisabled`).
  const [liveBotSkill, setLiveBotSkill] = useState<string | null>(null);
  // Ticket clicked in the account-wide Active Orders / Positions panel
  // (OrdersDock -> AllOrdersPanel) — highlighted on the chart with a
  // thicker, glowing line while everything else dims, mirroring
  // TradingView's "selected position" look. Cleared by clicking the same
  // row again.
  const [selectedOrderTicket, setSelectedOrderTicket] = useState<{
    ticket: number;
    symbol: string;
  } | null>(null);
  useEffect(() => {
    setBacktestReportId(
      new URLSearchParams(window.location.search).get(BACKTEST_REPORT_QUERY_KEY),
    );
  }, []);

  function exitBacktestView() {
    setBacktestReportId(null);
    const url = new URL(window.location.href);
    url.searchParams.delete(BACKTEST_REPORT_QUERY_KEY);
    window.history.replaceState(null, "", url);
  }

  // Called by the chart's inline strategy editor after it saves an edit and
  // re-runs the backtest — swaps in the new report id so the chart's trade
  // markers refresh without leaving the chart.
  function handleBacktestReportChange(reportId: string) {
    setBacktestReportId(reportId);
    setLiveBotSkill(null);
    const url = new URL(window.location.href);
    url.searchParams.set(BACKTEST_REPORT_QUERY_KEY, reportId);
    window.history.replaceState(null, "", url);
  }

  // Toggling the same bot's eye again turns the overlay off; toggling a
  // different bot switches straight to it. Entering live-bot view always
  // exits backtest view — the two overlays can't coexist.
  function toggleLiveBotSignals(skill: string) {
    setLiveBotSkill((current) => (current === skill ? null : skill));
    if (backtestReportId) exitBacktestView();
  }
  // A bot's `skill` embeds its symbol — stale after switching symbols, so
  // clear the eye rather than firing requests for a bot the new symbol's
  // BotSelector list won't even show as active.
  useEffect(() => setLiveBotSkill(null), [symbol]);

  // Row click from the Active Orders / Positions panel: clicking the
  // already-selected ticket toggles it off; clicking any other ticket
  // selects it and, if it belongs to a symbol that isn't on screen, switches
  // the chart to it first — same as TradingView's positions panel.
  function handleSelectOrderTicket(ticket: number, orderSymbol: string) {
    if (selectedOrderTicket && selectedOrderTicket.ticket === ticket) {
      setSelectedOrderTicket(null);
      return;
    }
    if (orderSymbol !== symbol) setSymbol(orderSymbol);
    setSelectedOrderTicket({ ticket, symbol: orderSymbol });
  }

  // Escape clears the chart highlight from anywhere — a second, always-
  // available way out besides re-clicking the selected row or the panel's
  // own "Clear selection" button.
  useEffect(() => {
    if (!selectedOrderTicket) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setSelectedOrderTicket(null);
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [selectedOrderTicket]);

  // ChartPanel needs a symbol string even while the real one is still
  // resolving on mount (see the effect below) — the empty-string placeholder
  // is never rendered since ChartPanel itself is gated on `symbol` below.
  const trading = useTrading(symbol ?? "");
  const activeStrategy = useActiveStrategyForSymbol(symbol ?? "");
  // Account-wide positions/pending orders — feeds both the header's total
  // floating P/L and the Active Orders / Positions panel (OrdersDock ->
  // AllOrdersPanel), so the two never fall out of sync or double-poll.
  const allPositions = useAllPositions();

  // Resolve the symbol to open on load — `?symbol=` wins over the last one
  // viewed (`tb.lastSymbol`), which wins over the first favorite, which wins
  // over the first engine-configured symbol. Nothing here is hardcoded to
  // XAUUSD: DEFAULT_SYMBOLS only kicks in if the backend is unreachable *and*
  // there's no favorite/last-viewed symbol yet.
  useEffect(() => {
    getHealth()
      .then(() => setBackendUp(true))
      .catch(() => setBackendUp(false));

    const storedExtras = readJsonList(EXTRA_SYMBOLS_KEY);
    let storedFavorites = readJsonList(FAVORITE_SYMBOLS_KEY);
    const migrated = localStorage.getItem(FAVORITES_MIGRATED_KEY) === "1";

    const urlSymbol = new URLSearchParams(window.location.search).get(SYMBOL_QUERY_KEY);
    let lastSymbol: string | null = null;
    try {
      lastSymbol = localStorage.getItem(LAST_SYMBOL_KEY);
    } catch {
      // Ignore blocked localStorage.
    }
    const resolved = urlSymbol ?? lastSymbol;

    setExtraSymbols(storedExtras);
    setFavoriteSymbols(storedFavorites);

    getAppConfig()
      .then((cfg) => {
        setConfig(cfg);
        const engineSymbols = cfg.symbols ?? DEFAULT_SYMBOLS;

        // One-time migration: the nav bar used to be seeded implicitly from
        // configuredSymbols — carry that over into favorites so existing
        // users don't lose their nav bar contents now that it's user-owned.
        if (!migrated) {
          storedFavorites = Array.from(new Set([...storedFavorites, ...engineSymbols]));
          writeJsonList(FAVORITE_SYMBOLS_KEY, storedFavorites);
          localStorage.setItem(FAVORITES_MIGRATED_KEY, "1");
          setFavoriteSymbols(storedFavorites);
        }

        const initial = resolved ?? storedFavorites[0] ?? engineSymbols[0] ?? DEFAULT_SYMBOLS[0];
        if (
          initial &&
          !engineSymbols.includes(initial) &&
          !storedFavorites.includes(initial) &&
          !storedExtras.includes(initial)
        ) {
          const updatedExtras = [...storedExtras, initial];
          writeJsonList(EXTRA_SYMBOLS_KEY, updatedExtras);
          setExtraSymbols(updatedExtras);
        }
        setSymbol((prev) => prev ?? initial);
      })
      .catch(() => {
        const initial = resolved ?? storedFavorites[0] ?? DEFAULT_SYMBOLS[0];
        setSymbol((prev) => prev ?? initial);
      });
  }, []);

  // Keep `?symbol=` and `tb.lastSymbol` in sync so a refresh (or a
  // bookmarked/bare link) resumes the same chart even if the query string
  // gets dropped.
  useEffect(() => {
    if (!symbol) return;
    const url = new URL(window.location.href);
    url.searchParams.set(SYMBOL_QUERY_KEY, symbol);
    window.history.replaceState(null, "", url);
    try {
      localStorage.setItem(LAST_SYMBOL_KEY, symbol);
    } catch {
      // Ignore blocked localStorage.
    }
  }, [symbol]);

  const configuredSymbols = config?.symbols ?? DEFAULT_SYMBOLS;

  function addExtraSymbol(sym: string) {
    if (favoriteSymbols.includes(sym) || extraSymbols.includes(sym)) {
      setSymbol(sym);
      return;
    }
    const updated = [...extraSymbols, sym];
    setExtraSymbols(updated);
    writeJsonList(EXTRA_SYMBOLS_KEY, updated);
    setSymbol(sym);
  }

  function removeExtraSymbol(sym: string) {
    const updated = extraSymbols.filter((s) => s !== sym);
    setExtraSymbols(updated);
    writeJsonList(EXTRA_SYMBOLS_KEY, updated);
    if (symbol === sym) setSymbol(favoriteSymbols[0] ?? configuredSymbols[0]);
  }

  function toggleFavorite(sym: string) {
    if (favoriteSymbols.includes(sym)) {
      const updated = favoriteSymbols.filter((s) => s !== sym);
      setFavoriteSymbols(updated);
      writeJsonList(FAVORITE_SYMBOLS_KEY, updated);
      // Unfavoriting the symbol currently on screen shouldn't make its chip
      // disappear outright — keep it around as a browsed/transient extra.
      if (symbol === sym && !extraSymbols.includes(sym)) {
        const updatedExtras = [...extraSymbols, sym];
        setExtraSymbols(updatedExtras);
        writeJsonList(EXTRA_SYMBOLS_KEY, updatedExtras);
      }
    } else {
      const updated = [...favoriteSymbols, sym];
      setFavoriteSymbols(updated);
      writeJsonList(FAVORITE_SYMBOLS_KEY, updated);
      // Favorited symbols are shown via the favorites chip list — drop the
      // duplicate from the transient extras list, if it was there.
      if (extraSymbols.includes(sym)) {
        const updatedExtras = extraSymbols.filter((s) => s !== sym);
        setExtraSymbols(updatedExtras);
        writeJsonList(EXTRA_SYMBOLS_KEY, updatedExtras);
      }
    }
  }

  return (
    <div className="flex h-screen flex-col">
      <header className="flex items-center gap-4 border-b border-line px-4 py-2">
        <MenuButton />
        <h1 className="text-base font-bold">AI Trading Bot</h1>
        {config && (
          <span
            className={`rounded px-2 py-0.5 text-xs font-bold ${
              config.mode === "live" ? "bg-err text-white" : "bg-ok text-white"
            }`}
          >
            {config.mode.toUpperCase()}
          </span>
        )}
        <nav className="flex items-center gap-1">
          {favoriteSymbols.map((s) => (
            <span
              key={s}
              className={`flex items-center gap-1 rounded border px-2 py-1 ${
                s === symbol ? "border-accent text-accent" : "border-line text-ink"
              }`}
              title={
                configuredSymbols.includes(s)
                  ? "Engine-traded symbol (configs/app.yaml)"
                  : "Favorited symbol"
              }
            >
              <button className="cursor-pointer" onClick={() => setSymbol(s)}>
                {s}
              </button>
              {configuredSymbols.includes(s) && (
                <span className="text-[10px] text-accent" title="Traded live by the engine">
                  ●
                </span>
              )}
              <button
                className="cursor-pointer text-accent hover:text-ink-muted"
                onClick={() => toggleFavorite(s)}
                title={`Unpin ${s}`}
              >
                ★
              </button>
            </span>
          ))}
          {extraSymbols.map((s) => (
            <span
              key={s}
              className={`flex items-center gap-1 rounded border px-2 py-1 ${
                s === symbol ? "border-accent text-accent" : "border-line text-ink-muted"
              }`}
              title="Browsed from the broker's catalog — not pinned to the nav bar"
            >
              <button className="cursor-pointer" onClick={() => setSymbol(s)}>
                {s}
              </button>
              <button
                className="cursor-pointer text-ink-muted hover:text-accent"
                onClick={() => toggleFavorite(s)}
                title={`Pin ${s}`}
              >
                ☆
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
          <SymbolPicker
            onAdd={addExtraSymbol}
            favorites={favoriteSymbols}
            onToggleFavorite={toggleFavorite}
          />
        </nav>
        <Link
          href={symbol ? `/bots?symbol=${encodeURIComponent(symbol)}` : "/bots"}
          className="ml-auto text-sm text-ink-muted hover:text-accent"
        >
          Bots
        </Link>
        <Link href="/backtest" className="text-sm text-ink-muted hover:text-accent">
          Backtests
        </Link>
        <Link href="/history" className="text-sm text-ink-muted hover:text-accent">
          History
        </Link>
        <Link href="/ai-reports" className="text-sm text-ink-muted hover:text-accent">
          AI Reports
        </Link>
        <Link href="/news" className="text-sm text-ink-muted hover:text-accent">
          News
        </Link>
        <Link href="/settings" className="text-sm text-ink-muted hover:text-accent">
          Settings
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
        <ResizableGroup orientation="horizontal" className="min-h-0 flex-1">
          <ResizablePanel id="chart" defaultSize="78%" minSize="360px" className="flex min-w-0">
            <OrdersDock
              allPositions={allPositions}
              selectedTicket={selectedOrderTicket?.ticket ?? null}
              onSelectTicket={handleSelectOrderTicket}
              onClearSelection={() => setSelectedOrderTicket(null)}
            >
              {symbol ? (
                <ChartPanel
                  symbol={symbol}
                  trading={trading}
                  activeStrategy={activeStrategy}
                  backtestReportId={backtestReportId}
                  onExitBacktestView={exitBacktestView}
                  onReportChange={handleBacktestReportChange}
                  liveBotSkill={liveBotSkill}
                  highlightedTicket={
                    selectedOrderTicket?.symbol === symbol ? selectedOrderTicket.ticket : null
                  }
                  onSelectTicket={handleSelectOrderTicket}
                />
              ) : (
                <div className="flex flex-1 items-center justify-center rounded-md border border-line bg-panel text-sm text-ink-muted">
                  Loading chart…
                </div>
              )}
            </OrdersDock>
          </ResizablePanel>
          <ResizableSeparator className="group relative w-2 cursor-col-resize bg-transparent outline-none">
            <div className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-line transition-colors group-hover:bg-accent group-data-[separator=active]:bg-accent group-data-[separator=focus]:bg-accent" />
            <button
              onClick={toggleSidebar}
              className="pointer-events-auto absolute top-3 left-1/2 z-10 flex h-6 w-6 -translate-x-1/2 cursor-pointer items-center justify-center rounded border border-line bg-panel text-ink-muted shadow hover:border-accent hover:text-accent"
              title={sidebarCollapsed ? "Show sidebar" : "Hide sidebar"}
            >
              {sidebarCollapsed ? <ChevronLeft size={14} /> : <ChevronRight size={14} />}
            </button>
          </ResizableSeparator>
          <ResizablePanel
            id="sidebar"
            panelRef={sidebarPanelRef}
            defaultSize="22%"
            minSize="280px"
            maxSize="45%"
            collapsible
            collapsedSize="0px"
            onResize={(size) => setSidebarCollapsed(size.inPixels <= 0.5)}
            className="flex min-w-0 flex-col"
          >
            <aside className="flex min-w-0 flex-1 flex-col gap-2 overflow-y-auto overflow-x-hidden border-l border-line p-2">
              <AccountPanel />
              <Panel>
                <EngineControlPanel />
              </Panel>
              <Panel>
                {symbol ? (
                  <BotSelector
                    symbol={symbol}
                    activeSignalsSkill={liveBotSkill}
                    onToggleSignals={toggleLiveBotSignals}
                    signalsDisabled={!!backtestReportId}
                  />
                ) : (
                  <Link href="/bots" className="text-accent hover:underline">
                    Bots →
                  </Link>
                )}
              </Panel>
              {symbol && (
                <Panel>
                  <TradePanel symbol={symbol} trading={trading} />
                </Panel>
              )}
              <Panel>Journal (Phase 3)</Panel>
              <Panel>
                <Link href="/ai-reports" className="text-accent hover:underline">
                  AI reviews →
                </Link>{" "}
                10-trade reviews, refinement proposals, backtest comparisons
              </Panel>
              <Panel>
                <ActiveNewsWindowsSummary />
              </Panel>
            </aside>
          </ResizablePanel>
        </ResizableGroup>
      </main>
    </div>
  );
}

function Panel({ children }: { children: React.ReactNode }) {
  return (
    <section className="min-w-0 rounded-md border border-line bg-panel p-3 text-sm">
      {children}
    </section>
  );
}
