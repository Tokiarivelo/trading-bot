"use client";

import { useVolatilityGuard } from "./useVolatilityGuard";

/** Settings-page panel for the ATR-percentile volatility guard: an on/off
 * toggle (live, not persisted — see the note in the panel body) plus
 * read-only display of the thresholds/multipliers it currently applies.
 * Shares its state with the chart toolbar's toggle via `useVolatilityGuard`
 * (TanStack Query cache), so a toggle here or there stays in sync. */
export function VolatilityGuardPanel() {
  const { config, isPending, isError, setEnabled, isSaving, saveError } = useVolatilityGuard();

  if (isError) return <p className="p-4 text-sm text-err">Failed to load the volatility guard config.</p>;
  if (isPending || !config) return <p className="p-4 text-sm text-ink-muted">Loading…</p>;

  return (
    <div className="flex flex-col gap-3 p-4">
      <p className="text-xs text-ink-muted">
        An ATR-percentile regime classifier that scales bots&apos; SL/TP and can force-close or
        trail positions in high volatility. Applies live to the running engine — not persisted, a
        backend restart reverts to <code>configs/volatility.yaml</code> (default: enabled).
      </p>

      <div className="rounded-md border border-line bg-panel p-3">
        <div className="flex flex-wrap items-center gap-4">
          <label className="flex items-center gap-2 text-sm text-ink">
            <input
              type="checkbox"
              checked={config.enabled}
              disabled={isSaving}
              onChange={(e) => setEnabled(e.target.checked)}
            />
            Enable volatility guard
          </label>
          {isSaving && <span className="text-xs text-ink-muted">Saving…</span>}
          {!isSaving && (
            <span className={`text-xs ${config.enabled ? "text-ok" : "text-err"}`}>
              {config.enabled ? "Guard is active." : "Guard is disabled — SL/TP are not adjusted for volatility."}
            </span>
          )}
        </div>
        {saveError && (
          <p className="mt-2 text-xs text-err">Failed to update the volatility guard.</p>
        )}

        <div className="mt-4 grid grid-cols-1 gap-x-6 gap-y-1.5 text-xs text-ink-muted sm:grid-cols-2">
          <div>ATR period: {config.atr_period} bars</div>
          <div>Regime lookback: {config.regime_lookback_bars} bars</div>
          <div>Low-volatility threshold: {config.low_percentile}th percentile</div>
          <div>High-volatility threshold: {config.high_percentile}th percentile</div>
          <div>Extreme-volatility threshold: {config.extreme_percentile}th percentile</div>
          <div>SL widening (low volatility): {config.sl_multiplier_low}x</div>
          <div>SL widening (normal volatility): {config.sl_multiplier_normal}x</div>
          <div>SL widening (high volatility): {config.sl_multiplier_high}x</div>
          <div>TP widening (low volatility): {config.tp_multiplier_low}x</div>
          <div>TP widening (normal volatility): {config.tp_multiplier_normal}x</div>
          <div>TP widening (high volatility): {config.tp_multiplier_high}x</div>
          <div>Close losing positions in extreme volatility: {config.extreme_close_if_losing ? "yes" : "no"}</div>
          <div>Profit lock in extreme volatility: {config.extreme_profit_lock_r_mult}R</div>
          <div>Chandelier trail ATR multiple: {config.chandelier_atr_mult}x</div>
          <div>Chandelier trail min profit: {config.chandelier_min_profit_r}R</div>
        </div>
      </div>
    </div>
  );
}
