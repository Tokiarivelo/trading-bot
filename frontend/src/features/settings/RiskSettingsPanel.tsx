"use client";

import { useEffect, useState } from "react";
import { getRiskCaps, putMinLotFallback, type RiskCaps } from "@/shared/api/client";

const inputCls =
  "rounded border border-line bg-bg px-2 py-1 text-sm text-ink placeholder:text-ink-muted focus:border-accent focus:outline-none";

export function RiskSettingsPanel() {
  const [caps, setCaps] = useState<RiskCaps | null>(null);
  const [enabled, setEnabled] = useState(false);
  const [ceiling, setCeiling] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    getRiskCaps()
      .then((c) => {
        setCaps(c);
        setEnabled(c.min_lot_fallback_enabled);
        setCeiling(c.max_risk_per_trade_pct != null ? String(c.max_risk_per_trade_pct) : "");
      })
      .catch(() => setError("Failed to load risk caps."));
  }, []);

  const parsedCeiling = ceiling.trim() === "" ? null : Number(ceiling);
  const isCeilingValid =
    parsedCeiling === null || (Number.isFinite(parsedCeiling) && parsedCeiling > 0 && parsedCeiling <= 100);
  const isDirty =
    caps !== null &&
    (enabled !== caps.min_lot_fallback_enabled || parsedCeiling !== caps.max_risk_per_trade_pct);

  async function save() {
    if (!isCeilingValid) return;
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const updated = await putMinLotFallback(enabled, parsedCeiling);
      setCaps(updated);
      setSaved(true);
    } catch {
      setError("Failed to update the min-lot fallback.");
    } finally {
      setSaving(false);
    }
  }

  if (error && !caps) return <p className="p-4 text-sm text-err">{error}</p>;
  if (!caps) return <p className="p-4 text-sm text-ink-muted">Loading…</p>;

  return (
    <div className="flex flex-col gap-3 p-4">
      <p className="text-xs text-ink-muted">
        Circuit breakers below are read-only here — edit <code>configs/risk.yaml</code> directly to
        change them (see CLAUDE.md: risk caps are user-owned).
      </p>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-3">
        <ReadOnlyCap label="Risk per trade" value={`${caps.risk_per_trade_pct}%`} />
        <ReadOnlyCap label="Daily loss limit" value={`${caps.daily_loss_limit_pct}%`} />
        <ReadOnlyCap label="Max open positions" value={String(caps.max_open_positions)} />
        <ReadOnlyCap label="Max trades/day" value={String(caps.max_trades_per_day)} />
        <ReadOnlyCap label="Consecutive-loss pause" value={String(caps.consecutive_loss_pause)} />
      </dl>

      <div className="mt-2 rounded-md border border-line bg-panel p-3">
        <h3 className="text-sm font-semibold text-ink">Small-balance min-lot fallback</h3>
        <p className="mt-1 text-xs text-ink-muted">
          When a balance is too small for &quot;risk per trade&quot; to reach the broker&apos;s
          minimum lot, sizing normally rejects the trade outright. Enabling this trades the minimum
          lot anyway, as long as <em>that lot&apos;s</em> effective risk stays under the ceiling
          below. Applies immediately to the live/paper engine — not persisted, a backend restart
          reverts to <code>configs/risk.yaml</code>.
        </p>

        <div className="mt-3 flex flex-wrap items-center gap-4">
          <label className="flex items-center gap-2 text-sm text-ink">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
            />
            Enable fallback
          </label>
          <label className="flex items-center gap-2 text-sm text-ink">
            Max effective risk on the minimum lot
            <input
              type="number"
              min="0"
              max="100"
              step="0.5"
              disabled={!enabled}
              className={`${inputCls} w-20 disabled:opacity-40`}
              value={ceiling}
              onChange={(e) => setCeiling(e.target.value)}
              placeholder={`${caps.risk_per_trade_pct}`}
            />
            %
          </label>
          <button
            type="button"
            disabled={!isDirty || !isCeilingValid || saving}
            onClick={save}
            className="rounded border border-accent px-3 py-1 text-xs whitespace-nowrap text-accent disabled:opacity-40"
          >
            {saving ? "Saving…" : "Save"}
          </button>
          {saved && !isDirty && <span className="text-xs text-ok">Applied live.</span>}
        </div>
        {!isCeilingValid && (
          <p className="mt-2 text-xs text-err">Ceiling must be between 0 and 100.</p>
        )}
        {error && <p className="mt-2 text-xs text-err">{error}</p>}
      </div>
    </div>
  );
}

function ReadOnlyCap({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-2 sm:block">
      <dt className="text-xs text-ink-muted">{label}</dt>
      <dd className="font-medium text-ink">{value}</dd>
    </div>
  );
}
