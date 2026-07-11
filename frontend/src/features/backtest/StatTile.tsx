/** Plain stat tile: label + value, no delta/sparkline — a backtest report is
 * a one-shot result, not a metric tracked against a prior period. */
export function StatTile({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "neutral" | "ok" | "err";
}) {
  const valueCls =
    tone === "ok" ? "text-ok" : tone === "err" ? "text-err" : "text-ink";
  return (
    <div className="rounded-md border border-line bg-panel p-3">
      <div className="text-xs text-ink-muted">{label}</div>
      <div className={`mt-1 text-lg font-semibold ${valueCls}`}>{value}</div>
    </div>
  );
}
