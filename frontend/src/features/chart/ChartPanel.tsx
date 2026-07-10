"use client";

/**
 * Chart feature — will host TradingView's lightweight-charts (Phase 2):
 * candlesticks + volume, live WS updates, trade markers from the journal,
 * news-window shading. Placeholder until the market_data API exists.
 */
export function ChartPanel({ symbol }: { symbol: string }) {
  return (
    <section className="flex flex-1 flex-col rounded-md border border-line bg-panel">
      <header className="border-b border-line px-4 py-2">
        <strong>{symbol}</strong> · M5
      </header>
      <div className="grid flex-1 place-items-center text-ink-muted">
        Chart lands in Phase 2 (lightweight-charts)
      </div>
    </section>
  );
}
