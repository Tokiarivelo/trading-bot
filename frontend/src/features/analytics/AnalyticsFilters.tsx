"use client";

function getTodayString(): string {
  const d = new Date();
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

const inputCls =
  "rounded border border-line bg-bg px-2 py-1 text-xs text-ink placeholder:text-ink-muted focus:border-accent focus:outline-none";

/** Pill-toggle and date filters for the analytics page: narrow every table and chart
 * below to specific symbols, bots, and/or open dates — an empty set means "everything," matching
 * `TradeHistoryFilters`' optional-field convention elsewhere in the journal module. The bot list is
 * pre-filtered by the caller to whatever the symbol selection allows, so
 * picking a symbol narrows which bots are even offered. */
export function AnalyticsFilters({
  availableSymbols,
  selectedSymbols,
  onToggleSymbol,
  availableBots,
  selectedBots,
  onToggleBot,
  dateFrom,
  onDateFromChange,
  dateTo,
  onDateToChange,
  onClear,
}: {
  availableSymbols: string[];
  selectedSymbols: Set<string>;
  onToggleSymbol: (symbol: string) => void;
  availableBots: { skill: string; bot_name: string; symbol: string }[];
  selectedBots: Set<string>;
  onToggleBot: (skill: string) => void;
  dateFrom: string;
  onDateFromChange: (date: string) => void;
  dateTo: string;
  onDateToChange: (date: string) => void;
  onClear: () => void;
}) {
  const hasActive = selectedSymbols.size > 0 || selectedBots.size > 0 || dateFrom !== "" || dateTo !== "";
  const todayStr = getTodayString();
  const isToday = dateFrom !== "" && dateFrom === todayStr && dateTo === todayStr;

  function handleTodayToggle(checked: boolean) {
    if (checked) {
      onDateFromChange(todayStr);
      onDateToChange(todayStr);
    } else {
      onDateFromChange("");
      onDateToChange("");
    }
  }

  return (
    <section className="rounded-xl border border-line bg-panel/30 shadow-inner overflow-hidden">
      <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-2.5">
        <div>
          <h2 className="text-sm font-bold text-ink">Filters</h2>
          <p className="text-xs text-ink-muted">
            Narrow the tables, charts, and export below to specific symbols, bots, and open date range — leave empty for
            everything.
          </p>
        </div>
        {hasActive && (
          <button
            type="button"
            onClick={onClear}
            className="shrink-0 cursor-pointer rounded border border-line px-2 py-1 text-xs text-ink-muted hover:border-accent hover:text-accent"
          >
            Clear filters
          </button>
        )}
      </header>
      <div className="flex flex-col gap-3 p-4">
        <FilterGroup label="Date">
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-1.5 text-xs text-ink-muted">
              From
              <input
                type="date"
                className={inputCls}
                value={dateFrom}
                onChange={(e) => onDateFromChange(e.target.value)}
              />
            </label>
            <label className="flex items-center gap-1.5 text-xs text-ink-muted">
              To
              <input
                type="date"
                className={inputCls}
                value={dateTo}
                onChange={(e) => onDateToChange(e.target.value)}
              />
            </label>
            <label className="ml-2 flex cursor-pointer items-center gap-1.5 text-xs text-ink-muted hover:text-ink">
              <input
                type="checkbox"
                checked={isToday}
                onChange={(e) => handleTodayToggle(e.target.checked)}
                className="cursor-pointer accent-accent"
              />
              Today
            </label>
          </div>
        </FilterGroup>
        <FilterGroup label="Symbols">
          {availableSymbols.length === 0 ? (
            <span className="text-xs text-ink-muted">No symbols yet.</span>
          ) : (
            availableSymbols.map((symbol) => (
              <Pill key={symbol} active={selectedSymbols.has(symbol)} onClick={() => onToggleSymbol(symbol)}>
                {symbol}
              </Pill>
            ))
          )}
        </FilterGroup>
        <FilterGroup label="Bots">
          {availableBots.length === 0 ? (
            <span className="text-xs text-ink-muted">No bots match the current symbol filter.</span>
          ) : (
            availableBots.map((bot) => (
              <Pill key={bot.skill} active={selectedBots.has(bot.skill)} onClick={() => onToggleBot(bot.skill)}>
                {bot.bot_name} <span className="opacity-60">· {bot.symbol}</span>
              </Pill>
            ))
          )}
        </FilterGroup>
      </div>
    </section>
  );
}

function FilterGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="mr-1 shrink-0 text-2xs font-semibold uppercase tracking-wider text-ink-muted">
        {label}
      </span>
      {children}
    </div>
  );
}

function Pill({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`cursor-pointer rounded-full border px-2.5 py-1 text-xs font-medium transition-colors ${
        active
          ? "border-accent bg-accent/10 text-accent"
          : "border-line text-ink-muted hover:border-accent hover:text-accent"
      }`}
    >
      {children}
    </button>
  );
}
