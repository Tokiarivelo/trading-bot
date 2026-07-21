"use client";

/**
 * SignalsDock — TradingView-style panel listing every signal and trade (order taken)
 * a backtest report's strategy emitted, so the trader can audit each setup.
 * Clicking navigation buttons scrolls/centers the chart on that bar.
 *
 * Rendered on the right side of the chart inside ChartPanel.
 */

import { useState } from "react";
import { Clock, Search, MapPin } from "lucide-react";
import { SIGNAL_OUTCOME_META } from "@/features/backtest/signalOutcome";
import type { BacktestSignal, BacktestTrade, IndicatorSpec } from "@/shared/api/client";

export function SignalsDock({
  signals,
  trades,
  indicators,
  selectedTradeIndex = null,
  onSelectTrade,
  onNavigateTrade,
  selectedSignalIndex = null,
  onSelectSignal,
}: {
  signals: BacktestSignal[];
  trades: BacktestTrade[];
  /** The bot/strategy version's own indicator specs (from its `StrategySpec`)
   * — undefined hides the tab entirely (e.g. no version resolved yet), an
   * empty array shows the tab with an empty state. */
  indicators?: IndicatorSpec[];
  /** Index (into the original, unsorted `trades` array) of the trade
   * currently highlighted on the chart with entry/SL/TP/close lines — drives
   * this row's selected style. Null when nothing's selected. */
  selectedTradeIndex?: number | null;
  /** Card click: toggles the trade's chart highlight off if it's already
   * selected, otherwise selects it and jumps the chart to its entry. */
  onSelectTrade?: (index: number) => void;
  /** Entry/Exit buttons: always selects (never toggles off) and jumps to
   * the given time — an explicit "look at this", not a selection toggle. */
  onNavigateTrade?: (index: number, time: number) => void;
  /** Index (into the original, unsorted `signals` array) of the signal
   * currently highlighted on the chart with a vertical dashed line — drives
   * this row's selected style. Null when nothing's selected. */
  selectedSignalIndex?: number | null;
  /** Row click: toggles the signal's chart highlight off if it's already
   * selected, otherwise selects it and jumps the chart to its time. */
  onSelectSignal?: (index: number) => void;
}) {
  const [activeTab, setActiveTab] = useState<"signals" | "trades" | "indicators">("signals");
  
  // Search & Filter state
  const [searchText, setSearchText] = useState("");
  const [outcomeFilter, setOutcomeFilter] = useState("");
  const [sideFilter, setSideFilter] = useState("");
  const [profitFilter, setProfitFilter] = useState("");

  const searchLower = searchText.toLowerCase();

  // Process signals (newest first)
  const filteredSignals = signals
    .map((s, idx) => ({ ...s, originalIndex: idx }))
    .filter((s) => {
      if (outcomeFilter && s.outcome !== outcomeFilter) return false;
      if (searchText && !s.reason.toLowerCase().includes(searchLower)) return false;
      return true;
    })
    .sort((a, b) => b.time - a.time);

  // Process trades (newest first)
  const filteredTrades = trades
    .map((t, idx) => ({ ...t, originalIndex: idx }))
    .filter((t) => {
      if (sideFilter && t.side !== sideFilter) return false;
      if (profitFilter === "win" && t.profit <= 0) return false;
      if (profitFilter === "loss" && t.profit >= 0) return false;
      const patternText = (t.pattern || "").toLowerCase();
      if (searchText && !patternText.includes(searchLower)) return false;
      return true;
    })
    .sort((a, b) => b.open_time - a.open_time);

  return (
    <div className="w-[340px] border-l border-line bg-panel flex flex-col h-full shrink-0 min-w-0">
      {/* Tabs */}
      <div className="flex border-b border-line bg-panel-dark/50 shrink-0">
        <button
          type="button"
          onClick={() => {
            setActiveTab("signals");
            setSearchText("");
          }}
          className={`flex-1 py-2 px-3 text-xs font-semibold border-b-2 text-center transition-colors cursor-pointer ${
            activeTab === "signals"
              ? "border-accent text-accent bg-accent/5"
              : "border-transparent text-ink-muted hover:text-ink hover:bg-panel-dark/20"
          }`}
        >
          Signals ({signals.length})
        </button>
        <button
          type="button"
          onClick={() => {
            setActiveTab("trades");
            setSearchText("");
          }}
          className={`flex-1 py-2 px-3 text-xs font-semibold border-b-2 text-center transition-colors cursor-pointer ${
            activeTab === "trades"
              ? "border-accent text-accent bg-accent/5"
              : "border-transparent text-ink-muted hover:text-ink hover:bg-panel-dark/20"
          }`}
        >
          Trades ({trades.length})
        </button>
        {indicators !== undefined && (
          <button
            type="button"
            onClick={() => {
              setActiveTab("indicators");
              setSearchText("");
            }}
            className={`flex-1 py-2 px-3 text-xs font-semibold border-b-2 text-center transition-colors cursor-pointer ${
              activeTab === "indicators"
                ? "border-accent text-accent bg-accent/5"
                : "border-transparent text-ink-muted hover:text-ink hover:bg-panel-dark/20"
            }`}
          >
            Indicators ({indicators.length})
          </button>
        )}
      </div>

      {/* Filters Area — indicators tab has too few rows to need search/filter */}
      {activeTab !== "indicators" && (
      <div className="p-2 border-b border-line flex flex-col gap-1.5 bg-panel-dark/20 shrink-0">
        {/* Search */}
        <div className="relative">
          <Search size={12} className="absolute left-2 top-2 text-ink-muted" />
          <input
            type="text"
            placeholder={activeTab === "signals" ? "Search signals..." : "Search trades..."}
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            className="w-full pl-7 pr-2 py-1 bg-panel border border-line rounded text-xs text-ink placeholder-ink-muted focus:border-accent focus:outline-none"
          />
        </div>

        {/* Dropdowns */}
        <div className="flex gap-1.5">
          {activeTab === "signals" ? (
            <select
              value={outcomeFilter}
              onChange={(e) => setOutcomeFilter(e.target.value)}
              className="flex-1 cursor-pointer rounded border border-line bg-panel px-1.5 py-1 text-xs text-ink focus:border-accent focus:outline-none"
            >
              <option value="">All outcomes</option>
              {Object.entries(SIGNAL_OUTCOME_META).map(([value, meta]) => (
                <option key={value} value={value}>
                  {meta.label}
                </option>
              ))}
            </select>
          ) : (
            <>
              <select
                value={sideFilter}
                onChange={(e) => setSideFilter(e.target.value)}
                className="flex-1 cursor-pointer rounded border border-line bg-panel px-1.5 py-1 text-xs text-ink focus:border-accent focus:outline-none"
              >
                <option value="">All sides</option>
                <option value="buy">Buy</option>
                <option value="sell">Sell</option>
              </select>
              <select
                value={profitFilter}
                onChange={(e) => setProfitFilter(e.target.value)}
                className="flex-1 cursor-pointer rounded border border-line bg-panel px-1.5 py-1 text-xs text-ink focus:border-accent focus:outline-none"
              >
                <option value="">All results</option>
                <option value="win">Win</option>
                <option value="loss">Loss</option>
              </select>
            </>
          )}
        </div>
      </div>
      )}

      {/* List Container */}
      <div className="flex-1 overflow-y-auto min-h-0 divide-y divide-line">
        {activeTab === "indicators" ? (
          !indicators || indicators.length === 0 ? (
            <p className="px-3 py-4 text-xs text-ink-muted text-center">
              No indicators recorded for this bot&apos;s strategy spec.
            </p>
          ) : (
            <ul className="divide-y divide-line">
              {indicators.map((ind, idx) => (
                <li key={`${ind.type}-${ind.source}-${idx}`} className="p-2.5 flex flex-col gap-1">
                  <div className="flex items-center gap-1.5">
                    <span className="text-[10px] font-bold uppercase px-1 rounded bg-accent/10 text-accent border border-accent/20">
                      {ind.type}
                    </span>
                    <span className="text-xs font-medium text-ink truncate">{ind.label}</span>
                  </div>
                  <div className="text-[10px] text-ink-muted">
                    period {ind.period} · source {ind.source}
                  </div>
                </li>
              ))}
            </ul>
          )
        ) : activeTab === "signals" ? (
          filteredSignals.length === 0 ? (
            <p className="px-3 py-4 text-xs text-ink-muted text-center">
              {signals.length === 0
                ? "No signals recorded for this report."
                : "No matching signals found."}
            </p>
          ) : (
            <ul className="divide-y divide-line">
              {filteredSignals.map((s) => {
                // Anything that didn't become a trade and wasn't merely
                // unresolved (`skipped`) was actively vetoed/rejected —
                // matches BotSelector's "Rej" chip count logic.
                const isRejected = s.outcome !== "opened" && s.outcome !== "skipped";
                return (
                  <li key={`${s.time}-${s.originalIndex}`}>
                    <button
                      type="button"
                      onClick={() => onSelectSignal?.(s.originalIndex)}
                      title="Highlight this signal on the chart"
                      className={`w-full text-left p-2.5 hover:bg-accent/5 transition-colors flex flex-col gap-1 cursor-pointer ${
                        selectedSignalIndex === s.originalIndex ? "bg-accent/10 border-l-2 border-accent" : ""
                      }`}
                    >
                      <div className="flex items-center gap-1.5 text-[10px] text-ink-muted">
                        <Clock size={10} />
                        <span>{formatTime(s.time)}</span>
                        <span
                          className={`ml-auto font-mono text-[9px] uppercase tracking-wider px-1 rounded border ${
                            isRejected
                              ? "bg-err/10 text-err border-err/30"
                              : "bg-panel-dark/50 border-line"
                          }`}
                        >
                          {SIGNAL_OUTCOME_META[s.outcome]?.label || s.outcome}
                        </span>
                      </div>
                      <div className="flex items-center gap-1.5 mt-0.5">
                        <span className={`text-[10px] font-bold px-1 rounded ${
                          s.direction === "buy"
                            ? "bg-ok/10 text-ok border border-ok/20"
                            : "bg-err/10 text-err border border-err/20"
                        }`}>
                          {s.direction.toUpperCase()}
                        </span>
                        <span
                          className={`text-xs font-medium text-ink flex-1 min-w-0 ${
                            isRejected ? "whitespace-pre-wrap break-words" : "truncate"
                          }`}
                          title={s.reason}
                        >
                          {s.reason}
                        </span>
                      </div>
                    </button>
                  </li>
                );
              })}
            </ul>
          )
        ) : (
          filteredTrades.length === 0 ? (
            <p className="px-3 py-4 text-xs text-ink-muted text-center">
              {trades.length === 0
                ? "No trades recorded for this report."
                : "No matching trades found."}
            </p>
          ) : (
            <ul className="divide-y divide-line">
              {filteredTrades.map((t) => (
                <li key={`${t.open_time}-${t.originalIndex}`}>
                  <div
                    onClick={() => onSelectTrade?.(t.originalIndex)}
                    title="Highlight this trade's entry/SL/TP/close on the chart"
                    className={`p-2.5 hover:bg-accent/5 transition-colors flex flex-col gap-1.5 relative border-l-2 cursor-pointer ${
                      selectedTradeIndex === t.originalIndex
                        ? "bg-accent/10 border-accent"
                        : "border-transparent"
                    }`}
                  >
                    {/* Header info */}
                    <div className="flex items-center gap-1.5 text-[10px] text-ink-muted">
                      <span className="font-semibold text-ink">
                        Trade #{t.originalIndex + 1}
                      </span>
                      <span>•</span>
                      <span>{formatTime(t.open_time)}</span>
                      <span className={`ml-auto font-mono font-bold ${t.profit >= 0 ? "text-ok" : "text-err"}`}>
                        {t.profit >= 0 ? "+" : ""}{t.profit.toFixed(2)} USD
                      </span>
                    </div>

                    {/* Volume and price */}
                    <div className="flex items-center gap-1.5">
                      <span className={`text-[10px] font-bold px-1 rounded ${
                        t.side === "buy"
                          ? "bg-ok/10 text-ok border border-ok/20"
                          : "bg-err/10 text-err border border-err/20"
                      }`}>
                        {t.side.toUpperCase()}
                      </span>
                      <span className="text-[11px] text-ink-muted">
                        {t.volume.toFixed(2)} lots @ {t.open_price.toFixed(2)}
                      </span>
                      {t.r_multiple !== null && (
                        <span className="text-[10px] font-medium px-1 rounded bg-panel-dark/50 border border-line">
                          {t.r_multiple.toFixed(1)} R
                        </span>
                      )}
                    </div>

                    {/* Pattern/Reason if present */}
                    {t.pattern && (
                      <div className="text-[10px] text-ink-muted truncate font-mono bg-panel-dark/30 p-1.5 rounded border border-line/30">
                        {t.pattern}
                      </div>
                    )}

                    {/* Navigation buttons */}
                    <div className="flex items-center gap-1.5 mt-1 border-t border-line/25 pt-1.5">
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          onNavigateTrade?.(t.originalIndex, t.open_time);
                        }}
                        className="flex-1 py-1 px-2 rounded bg-panel border border-line text-[10px] text-ink hover:text-accent hover:border-accent transition-colors flex items-center justify-center gap-1 cursor-pointer"
                      >
                        <MapPin size={10} /> Entry
                      </button>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          onNavigateTrade?.(t.originalIndex, t.close_time);
                        }}
                        className="flex-1 py-1 px-2 rounded bg-panel border border-line text-[10px] text-ink hover:text-accent hover:border-accent transition-colors flex items-center justify-center gap-1 cursor-pointer"
                      >
                        <MapPin size={10} /> Exit
                      </button>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )
        )}
      </div>
    </div>
  );
}

function formatTime(epochSeconds: number): string {
  // Returns "MM-DD HH:MM" format
  return new Date(epochSeconds * 1000).toISOString().replace("T", " ").slice(5, 16);
}
