"use client";

import { useState } from "react";
import { ApiError, importBacktestReport } from "@/shared/api/client";

/** Upload a backtest report JSON — the exact shape produced by the
 * "Download" button on any saved report, so re-uploading a downloaded file
 * always works. A fresh id is assigned; this never overwrites an existing
 * report (§ backtest report import). */
export function BacktestReportUploadForm({ onImported }: { onImported: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onUpload(form: FormData) {
    const file = form.get("file");
    if (!(file instanceof File) || file.size === 0) {
      setError("Please choose a JSON file first");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      let parsed: unknown;
      try {
        parsed = JSON.parse(await file.text());
      } catch {
        throw new Error("That file isn't valid JSON");
      }
      await importBacktestReport(parsed as Parameters<typeof importBacktestReport>[0]);
      onImported();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : e instanceof Error ? e.message : "upload failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      action={onUpload}
      className="flex flex-col gap-3 rounded-xl border border-line bg-panel p-4 shadow-lg backdrop-blur-md mb-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <label className="text-xs font-semibold text-ink-muted uppercase tracking-wider">
          Import Backtest Report JSON
        </label>
        <div className="flex items-center gap-2">
          <input
            name="file"
            type="file"
            accept="application/json,.json"
            required
            disabled={busy}
            className="text-xs text-ink-muted file:mr-2 file:cursor-pointer file:rounded file:border file:border-line file:bg-bg/50 file:px-2 file:py-1 file:text-xs file:text-ink hover:file:border-accent"
          />
          <button
            type="submit"
            disabled={busy}
            className="cursor-pointer rounded-lg bg-accent px-3 py-1.5 text-xs font-semibold text-white hover:bg-accent/90 disabled:opacity-50 disabled:pointer-events-none transition-all duration-200"
          >
            {busy ? "Importing…" : "Import"}
          </button>
        </div>
      </div>

      {error && <p className="text-xs text-err font-medium">{error}</p>}

      <details className="text-xs text-ink-muted">
        <summary className="cursor-pointer select-none hover:text-accent">Expected JSON shape</summary>
        <div className="mt-2 space-y-1">
          <p>
            Same shape as the <strong>Download</strong> button on any saved report below — the
            fastest way to get a valid example is to download one, then re-upload that file.
          </p>
          <p>Top-level fields: strategy, symbol, period (&quot;YYYY-MM:YYYY-MM&quot;), starting_balance, ending_balance,</p>
          <p>win_rate, profit_factor, max_drawdown_pct, avg_r, worst_losing_streak,</p>
          <p>trades[] (side, volume, open_time, open_price, sl, tp, close_time, close_price, profit, r_multiple, …),</p>
          <p>equity_curve[] (time, balance), activity_log[] (time, level, logger, message).</p>
        </div>
      </details>
    </form>
  );
}
