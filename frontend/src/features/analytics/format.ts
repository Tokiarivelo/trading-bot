/** Shared number/time formatting for the analytics tables and charts —
 * kept in one place so "∞ vs null" and "positive vs negative" conventions
 * stay consistent across the symbol table, bot table, and overview strip. */

export function pct(ratio: number): string {
  return `${(ratio * 100).toFixed(1)}%`;
}

export function money(value: number, opts: { sign?: boolean } = {}): string {
  const sign = opts.sign && value >= 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}`;
}

export function profitFactor(value: number | null): string {
  return value === null ? "∞" : value.toFixed(2);
}

export function duration(seconds: number | null): string {
  if (seconds === null) return "—";
  const abs = Math.abs(seconds);
  if (abs < 60) return `${Math.round(abs)}s`;
  if (abs < 3600) return `${Math.round(abs / 60)}m`;
  if (abs < 86400) return `${(abs / 3600).toFixed(1)}h`;
  return `${(abs / 86400).toFixed(1)}d`;
}

export function timeAgo(epochSeconds: number | null): string {
  if (epochSeconds === null) return "—";
  return new Date(epochSeconds * 1000).toISOString().replace("T", " ").slice(0, 16);
}

export function plTone(value: number): string {
  return value >= 0 ? "text-ok" : "text-err";
}
