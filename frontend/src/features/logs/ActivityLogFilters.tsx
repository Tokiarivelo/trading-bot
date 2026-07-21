"use client";

export interface ActivityLogFilterState {
  level: string;
  loggerContains: string;
  q: string;
}

export const EMPTY_FILTERS: ActivityLogFilterState = {
  level: "",
  loggerContains: "",
  q: "",
};

const inputCls =
  "rounded border border-line bg-bg px-2 py-1 text-sm text-ink placeholder:text-ink-muted focus:border-accent focus:outline-none";

export function ActivityLogFilters({
  filters,
  onChange,
  autoRefresh,
  onAutoRefreshChange,
}: {
  filters: ActivityLogFilterState;
  onChange: (next: ActivityLogFilterState) => void;
  autoRefresh: boolean;
  onAutoRefreshChange: (next: boolean) => void;
}) {
  function set<K extends keyof ActivityLogFilterState>(key: K, value: ActivityLogFilterState[K]) {
    onChange({ ...filters, [key]: value });
  }

  return (
    <div className="flex flex-wrap items-end gap-2 border-b border-line p-3">
      <Field label="Level">
        <select
          className={inputCls}
          value={filters.level}
          onChange={(e) => set("level", e.target.value)}
        >
          <option value="">Any</option>
          <option value="INFO">Info</option>
          <option value="WARNING">Warning</option>
          <option value="ERROR">Error</option>
        </select>
      </Field>
      <Field label="Module">
        <input
          className={`${inputCls} w-44`}
          placeholder="e.g. trade_loop, broker"
          value={filters.loggerContains}
          onChange={(e) => set("loggerContains", e.target.value)}
        />
      </Field>
      <Field label="Search">
        <input
          className={`${inputCls} w-64`}
          placeholder="e.g. XAUUSD, vetoed, reason"
          value={filters.q}
          onChange={(e) => set("q", e.target.value)}
        />
      </Field>
      <label className="flex items-center gap-2 pb-1.5 text-xs text-ink-muted">
        <input
          type="checkbox"
          checked={autoRefresh}
          onChange={(e) => onAutoRefreshChange(e.target.checked)}
        />
        Live (auto-refresh)
      </label>
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

function hasActiveFilters(filters: ActivityLogFilterState): boolean {
  return filters.level !== "" || filters.loggerContains !== "" || filters.q !== "";
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-xs text-ink-muted">
      {label}
      {children}
    </label>
  );
}
