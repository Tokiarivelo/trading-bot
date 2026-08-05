"use client";

import { useEffect, useState } from "react";
import { useActiveAccount } from "@/shared/api/account-context";
import {
  getRiskCaps,
  putCoreRiskCaps,
  putMaxTradesPerDayEnabled,
  putMinLotFallback,
  type RiskCaps,
} from "@/shared/api/client";

const inputCls =
  "rounded border border-line bg-bg px-2 py-1 text-sm text-ink placeholder:text-ink-muted focus:border-accent focus:outline-none";

interface CoreCapsForm {
  risk_per_trade_pct: string;
  daily_loss_limit_pct: string;
  max_open_positions: string;
  consecutive_loss_pause: string;
}

function toCoreCapsForm(caps: RiskCaps): CoreCapsForm {
  return {
    risk_per_trade_pct: String(caps.risk_per_trade_pct),
    daily_loss_limit_pct: String(caps.daily_loss_limit_pct),
    max_open_positions: String(caps.max_open_positions),
    consecutive_loss_pause: String(caps.consecutive_loss_pause),
  };
}

export function RiskSettingsPanel() {
  const accountId = useActiveAccount();
  const [caps, setCaps] = useState<RiskCaps | null>(null);
  const [enabled, setEnabled] = useState(false);
  const [ceiling, setCeiling] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const [killSwitchOn, setKillSwitchOn] = useState(false);
  const [killSwitchError, setKillSwitchError] = useState<string | null>(null);
  const [killSwitchSaving, setKillSwitchSaving] = useState(false);

  const [coreForm, setCoreForm] = useState<CoreCapsForm | null>(null);
  const [coreError, setCoreError] = useState<string | null>(null);
  const [coreSaving, setCoreSaving] = useState(false);
  const [coreSaved, setCoreSaved] = useState(false);

  useEffect(() => {
    if (!accountId) return;
    getRiskCaps(accountId)
      .then((c) => {
        setCaps(c);
        setEnabled(c.min_lot_fallback_enabled);
        setCeiling(c.max_risk_per_trade_pct != null ? String(c.max_risk_per_trade_pct) : "");
        setKillSwitchOn(c.max_trades_per_day_enabled);
        setCoreForm(toCoreCapsForm(c));
      })
      .catch(() => setError("Failed to load risk caps."));
  }, [accountId]);

  const parsedCeiling = ceiling.trim() === "" ? null : Number(ceiling);
  const isCeilingValid =
    parsedCeiling === null || (Number.isFinite(parsedCeiling) && parsedCeiling > 0 && parsedCeiling <= 100);
  const isDirty =
    caps !== null &&
    (enabled !== caps.min_lot_fallback_enabled || parsedCeiling !== caps.max_risk_per_trade_pct);

  async function save() {
    if (!isCeilingValid || !accountId) return;
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const updated = await putMinLotFallback(accountId, enabled, parsedCeiling);
      setCaps(updated);
      setSaved(true);
    } catch {
      setError("Failed to update the min-lot fallback.");
    } finally {
      setSaving(false);
    }
  }

  async function toggleKillSwitch(next: boolean) {
    if (!accountId) return;
    setKillSwitchSaving(true);
    setKillSwitchError(null);
    const previous = killSwitchOn;
    setKillSwitchOn(next); // optimistic — this is a manual kill switch, feedback should feel instant
    try {
      const updated = await putMaxTradesPerDayEnabled(accountId, next);
      setCaps(updated);
    } catch {
      setKillSwitchOn(previous);
      setKillSwitchError("Failed to update the daily trading kill switch.");
    } finally {
      setKillSwitchSaving(false);
    }
  }

  const parsedCore =
    coreForm === null
      ? null
      : {
          risk_per_trade_pct: Number(coreForm.risk_per_trade_pct),
          daily_loss_limit_pct: Number(coreForm.daily_loss_limit_pct),
          max_open_positions: Number(coreForm.max_open_positions),
          consecutive_loss_pause: Number(coreForm.consecutive_loss_pause),
        };
  const isCoreValid =
    parsedCore !== null &&
    Number.isFinite(parsedCore.risk_per_trade_pct) &&
    parsedCore.risk_per_trade_pct > 0 &&
    parsedCore.risk_per_trade_pct <= 100 &&
    Number.isFinite(parsedCore.daily_loss_limit_pct) &&
    parsedCore.daily_loss_limit_pct > 0 &&
    parsedCore.daily_loss_limit_pct <= 100 &&
    Number.isInteger(parsedCore.max_open_positions) &&
    parsedCore.max_open_positions > 0 &&
    Number.isInteger(parsedCore.consecutive_loss_pause) &&
    parsedCore.consecutive_loss_pause > 0;
  const isCoreDirty =
    caps !== null &&
    parsedCore !== null &&
    (parsedCore.risk_per_trade_pct !== caps.risk_per_trade_pct ||
      parsedCore.daily_loss_limit_pct !== caps.daily_loss_limit_pct ||
      parsedCore.max_open_positions !== caps.max_open_positions ||
      parsedCore.consecutive_loss_pause !== caps.consecutive_loss_pause);

  function updateCoreField(field: keyof CoreCapsForm, value: string) {
    setCoreForm((prev) => (prev ? { ...prev, [field]: value } : prev));
  }

  async function saveCore() {
    if (!isCoreValid || !parsedCore || !accountId) return;
    setCoreSaving(true);
    setCoreError(null);
    setCoreSaved(false);
    try {
      const updated = await putCoreRiskCaps(accountId, parsedCore);
      setCaps(updated);
      setCoreForm(toCoreCapsForm(updated));
      setCoreSaved(true);
    } catch {
      setCoreError("Failed to update the core risk caps.");
    } finally {
      setCoreSaving(false);
    }
  }

  if (error && !caps) return <p className="p-4 text-sm text-err">{error}</p>;
  if (!caps || !coreForm) return <p className="p-4 text-sm text-ink-muted">Loading…</p>;

  return (
    <div className="flex flex-col gap-3 p-4">
      <p className="text-xs text-ink-muted">
        Adjusting these below applies live to the running engine — not persisted, a backend
        restart reverts to <code>configs/risk.yaml</code>, which is what to edit directly to
        change the default (see CLAUDE.md: risk caps are user-owned).
      </p>

      <div className="rounded-md border border-line bg-panel p-3">
        <h3 className="text-sm font-semibold text-ink">Core caps</h3>
        <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <label className="flex flex-col gap-1 text-xs text-ink-muted">
            Risk per trade %
            <input
              type="number"
              min="0"
              max="100"
              step="0.1"
              className={inputCls}
              value={coreForm.risk_per_trade_pct}
              onChange={(e) => updateCoreField("risk_per_trade_pct", e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-ink-muted">
            Daily loss limit %
            <input
              type="number"
              min="0"
              max="100"
              step="0.5"
              className={inputCls}
              value={coreForm.daily_loss_limit_pct}
              onChange={(e) => updateCoreField("daily_loss_limit_pct", e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-ink-muted">
            Max open positions
            <input
              type="number"
              min="1"
              step="1"
              className={inputCls}
              value={coreForm.max_open_positions}
              onChange={(e) => updateCoreField("max_open_positions", e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-ink-muted">
            Consecutive-loss pause
            <input
              type="number"
              min="1"
              step="1"
              className={inputCls}
              value={coreForm.consecutive_loss_pause}
              onChange={(e) => updateCoreField("consecutive_loss_pause", e.target.value)}
            />
          </label>
        </div>
        <div className="mt-3 flex items-center gap-3">
          <button
            type="button"
            disabled={!isCoreDirty || !isCoreValid || coreSaving}
            onClick={saveCore}
            className="rounded border border-accent px-3 py-1 text-xs whitespace-nowrap text-accent disabled:opacity-40"
          >
            {coreSaving ? "Saving…" : "Save"}
          </button>
          {coreSaved && !isCoreDirty && <span className="text-xs text-ok">Applied live.</span>}
        </div>
        {!isCoreValid && (
          <p className="mt-2 text-xs text-err">
            Percentages must be between 0 and 100; counts must be whole numbers of 1 or more.
          </p>
        )}
        {coreError && <p className="mt-2 text-xs text-err">{coreError}</p>}
      </div>

      <div className="rounded-md border border-line bg-panel p-3">
        <h3 className="text-sm font-semibold text-ink">Daily trading kill switch</h3>
        <p className="mt-1 text-xs text-ink-muted">
          Not a trade count — a manual switch. Turning it on rejects every new trade (automated
          or manual) for the rest of the trading day; turning it off lifts the block
          immediately. Applies live to the running engine — not persisted, a backend restart
          reverts to <code>configs/risk.yaml</code>.
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-4">
          <label className="flex items-center gap-2 text-sm text-ink">
            <input
              type="checkbox"
              checked={killSwitchOn}
              disabled={killSwitchSaving}
              onChange={(e) => toggleKillSwitch(e.target.checked)}
            />
            Block new trades for the rest of today
          </label>
          {killSwitchSaving && <span className="text-xs text-ink-muted">Saving…</span>}
          {!killSwitchSaving && (
            <span className={`text-xs ${killSwitchOn ? "text-err" : "text-ok"}`}>
              {killSwitchOn ? "New trades are currently blocked." : "Trading is unrestricted."}
            </span>
          )}
        </div>
        {killSwitchError && <p className="mt-2 text-xs text-err">{killSwitchError}</p>}
      </div>

      <div className="rounded-md border border-line bg-panel p-3">
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
