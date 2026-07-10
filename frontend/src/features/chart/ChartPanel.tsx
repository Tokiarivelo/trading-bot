/**
 * Chart feature — will host TradingView's lightweight-charts (Phase 2):
 * candlesticks + volume, live WS updates, trade markers from the journal,
 * news-window shading. Placeholder until the market_data API exists.
 */
export function ChartPanel({ symbol }: { symbol: string }) {
  return (
    <section className="panel chart-panel">
      <header>
        <strong>{symbol}</strong> · M5
      </header>
      <div className="chart-placeholder">Chart lands in Phase 2 (lightweight-charts)</div>
    </section>
  );
}
