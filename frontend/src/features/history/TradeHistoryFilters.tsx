"use client";

import type { TradeHistoryOrderBy, TradeOutcome } from "@/shared/api/client";
import type { OrderSide } from "@/shared/api/client";
import type { GroupBy } from "./groupTrades";

export interface TradeHistoryFilterState {
  symbol: string;
  side: OrderSide | "";
  strategyVersion: string;
  skill: string;
  outcome: TradeOutcome | "";
  openFrom: string; // yyyy-mm-dd, local date input value
  openTo: string;
  orderBy: TradeHistoryOrderBy;
  orderDir: "asc" | "desc";
}

export const EMPTY_FILTERS: TradeHistoryFilterState = {
  symbol: "",
  side: "",
  strategyVersion: "",
  skill: "",
  outcome: "",
  openFrom: "",
  openTo: "",
  orderBy: "open_time",
  orderDir: "desc",
};

const inputCls =
  "rounded border border-line bg-bg px-2 py-1 text-sm text-ink placeholder:text-ink-muted focus:border-accent focus:outline-none";

export function TradeHistoryFilters({
  filters,
  onChange,
  groupBy,
  onGroupByChange,
}: {
  filters: TradeHistoryFilterState;
  onChange: (next: TradeHistoryFilterState) => void;
  groupBy: GroupBy;
  onGroupByChange: (next: GroupBy) => void;
}) {
  function set<K extends keyof TradeHistoryFilterState>(key: K, value: TradeHistoryFilterState[K]) {
    onChange({ ...filters, [key]: value });
  }

  return (
    <div className="flex flex-wrap items-end gap-2 border-b border-line p-3">
      <Field label="Symbol">
        <input
          className={`${inputCls} w-28`}
          placeholder="e.g. XAUUSD"
          value={filters.symbol}
          onChange={(e) => set("symbol", e.target.value.toUpperCase())}
        />
      </Field>
      <Field label="Side">
        <select
          className={inputCls}
          value={filters.side}
          onChange={(e) => set("side", e.target.value as OrderSide | "")}
        >
          <option value="">Any</option>
          <option value="buy">Buy</option>
          <option value="sell">Sell</option>
        </select>
      </Field>
      <Field label="Outcome">
        <select
          className={inputCls}
          value={filters.outcome}
          onChange={(e) => set("outcome", e.target.value as TradeOutcome | "")}
        >
          <option value="">Any</option>
          <option value="win">Win</option>
          <option value="loss">Loss</option>
          <option value="breakeven">Breakeven</option>
          <option value="open">Open</option>
        </select>
      </Field>
      <Field label="Strategy version">
        <input
          className={`${inputCls} w-36`}
          placeholder="e.g. breakout_v1:v1"
          value={filters.strategyVersion}
          onChange={(e) => set("strategyVersion", e.target.value)}
        />
      </Field>
      <Field label="Skill">
        <input
          className={`${inputCls} w-32`}
          placeholder="e.g. normal/xauusd"
          value={filters.skill}
          onChange={(e) => set("skill", e.target.value)}
        />
      </Field>
      <Field label="Opened from">
        <input
          type="date"
          className={inputCls}
          value={filters.openFrom}
          onChange={(e) => set("openFrom", e.target.value)}
        />
      </Field>
      <Field label="Opened to">
        <input
          type="date"
          className={inputCls}
          value={filters.openTo}
          onChange={(e) => set("openTo", e.target.value)}
        />
      </Field>
      <Field label="Sort by">
        <select
          className={inputCls}
          value={filters.orderBy}
          onChange={(e) => set("orderBy", e.target.value as TradeHistoryOrderBy)}
        >
          <option value="open_time">Open time</option>
          <option value="close_time">Close time</option>
          <option value="profit">Profit</option>
        </select>
      </Field>
      <Field label="Direction">
        <select
          className={inputCls}
          value={filters.orderDir}
          onChange={(e) => set("orderDir", e.target.value as "asc" | "desc")}
        >
          <option value="desc">Newest / highest first</option>
          <option value="asc">Oldest / lowest first</option>
        </select>
      </Field>
      <Field label="Group by">
        <select
          className={inputCls}
          value={groupBy}
          onChange={(e) => onGroupByChange(e.target.value as GroupBy)}
        >
          <option value="none">None</option>
          <option value="symbol">Symbol</option>
          <option value="date">Date opened</option>
          <option value="side">Side</option>
          <option value="strategy_version">Strategy version</option>
          <option value="skill">Skill</option>
          <option value="outcome">Outcome</option>
        </select>
      </Field>
      {hasActiveFilters(filters) && (
        <button
          type="button"
          className="cursor-pointer rounded border border-line px-2 py-1 text-xs text-ink-muted hover:border-accent hover:text-accent"
          onClick={() => onChange(EMPTY_FILTERS)}
        >
          Clear filters
        </button>
      )}
    </div>
  );
}

function hasActiveFilters(filters: TradeHistoryFilterState): boolean {
  return (
    filters.symbol !== "" ||
    filters.side !== "" ||
    filters.strategyVersion !== "" ||
    filters.skill !== "" ||
    filters.outcome !== "" ||
    filters.openFrom !== "" ||
    filters.openTo !== ""
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-xs text-ink-muted">
      {label}
      {children}
    </label>
  );
}
