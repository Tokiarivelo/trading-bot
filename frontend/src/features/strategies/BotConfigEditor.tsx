"use client";

/**
 * Full per-bot configuration editor (§6.6): risk multiplier, session
 * windows, the engine's HTF veto, and every one of this bot's strategy's
 * own tunable params (e.g. `counter_trend_penalty`) — each overridable for
 * this one bot without forking its strategy's generated code. Every field
 * is a full replacement on save (PUT .../bots/{bot_name}/config), matching
 * this repo's other bot-assignment endpoints. Rendered inline inside a bot
 * card in `SymbolAssignmentPanel` when that bot's "Configure" toggle is open.
 */

import { useState } from "react";
import {
  ApiError,
  updateBotConfig,
  type NormalSkillAssignment,
  type ParamValue,
  type SessionWindowWire,
} from "@/shared/api/client";

type HtfVetoMode = "default" | "on" | "off";

function draftDiffersFromDefault(draft: string | boolean, defaultValue: ParamValue): boolean {
  if (typeof defaultValue === "boolean") return Boolean(draft) !== defaultValue;
  if (typeof defaultValue === "number") return Number(draft) !== defaultValue;
  return String(draft) !== String(defaultValue);
}

function initialParamDrafts(bot: NormalSkillAssignment): Record<string, string | boolean> {
  const drafts: Record<string, string | boolean> = {};
  for (const [key, defaultValue] of Object.entries(bot.strategy_default_params)) {
    const current = bot.param_overrides[key] ?? defaultValue;
    drafts[key] = typeof current === "boolean" ? current : String(current);
  }
  return drafts;
}

export function BotConfigEditor({
  symbol,
  bot,
  onSaved,
}: {
  symbol: string;
  bot: NormalSkillAssignment;
  onSaved: () => void;
}) {
  const [riskMultiplier, setRiskMultiplier] = useState(String(bot.risk_multiplier));
  const [sessions, setSessions] = useState<SessionWindowWire[]>(bot.sessions);
  const [htfVetoMode, setHtfVetoMode] = useState<HtfVetoMode>(
    bot.htf_veto_override === null ? "default" : bot.htf_veto_override ? "on" : "off",
  );
  const [paramDrafts, setParamDrafts] = useState<Record<string, string | boolean>>(() =>
    initialParamDrafts(bot),
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const paramKeys = Object.keys(bot.strategy_default_params).sort();
  const riskValid = Number.isFinite(Number(riskMultiplier)) && Number(riskMultiplier) > 0;
  const numericDraftsValid = paramKeys.every((key) => {
    const defaultValue = bot.strategy_default_params[key];
    if (typeof defaultValue !== "number") return true;
    return Number.isFinite(Number(paramDrafts[key]));
  });
  const canSave = riskValid && numericDraftsValid && !saving;

  function updateSession(index: number, field: "start" | "end", value: string) {
    setSessions((prev) => prev.map((s, i) => (i === index ? { ...s, [field]: value } : s)));
  }
  function addSession() {
    setSessions((prev) => [...prev, { start: "00:00", end: "23:59" }]);
  }
  function removeSession(index: number) {
    setSessions((prev) => prev.filter((_, i) => i !== index));
  }
  function resetParam(key: string) {
    const defaultValue = bot.strategy_default_params[key];
    setParamDrafts((prev) => ({
      ...prev,
      [key]: typeof defaultValue === "boolean" ? defaultValue : String(defaultValue),
    }));
  }

  async function save() {
    if (!canSave) return;
    setSaving(true);
    setError(null);
    try {
      const param_overrides: Record<string, ParamValue> = {};
      for (const key of paramKeys) {
        const defaultValue = bot.strategy_default_params[key];
        const draft = paramDrafts[key];
        if (!draftDiffersFromDefault(draft, defaultValue)) continue;
        param_overrides[key] =
          typeof defaultValue === "boolean"
            ? Boolean(draft)
            : typeof defaultValue === "number"
              ? Number(draft)
              : String(draft);
      }
      await updateBotConfig(symbol, bot.bot_name, {
        risk_multiplier: Number(riskMultiplier),
        sessions,
        param_overrides,
        htf_veto_override: htfVetoMode === "default" ? null : htfVetoMode === "on",
      });
      onSaved();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "failed to save bot config");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mt-2 flex flex-col gap-2 rounded-lg border border-line bg-bg/50 p-2">
      <div className="flex items-center gap-2">
        <label className="w-20 shrink-0 text-3xs font-semibold text-ink-muted uppercase tracking-wider">
          Risk mult.
        </label>
        <input
          type="number"
          min="0"
          step="0.1"
          value={riskMultiplier}
          onChange={(e) => setRiskMultiplier(e.target.value)}
          className="w-20 rounded border border-line bg-bg/80 px-1.5 py-0.5 text-xs text-ink focus:border-accent focus:outline-none"
        />
        {!riskValid && <span className="text-[10px] text-err">must be &gt; 0</span>}
      </div>

      <div className="flex flex-col gap-1">
        <div className="flex items-center justify-between">
          <span className="text-3xs font-semibold text-ink-muted uppercase tracking-wider">
            Sessions
          </span>
          <button
            type="button"
            onClick={addSession}
            className="text-3xs font-semibold text-accent hover:underline"
          >
            + Add
          </button>
        </div>
        {sessions.length === 0 && (
          <p className="text-[10px] text-ink-muted">Always active (no session windows)</p>
        )}
        {sessions.map((s, i) => (
          <div key={i} className="flex items-center gap-1">
            <input
              type="time"
              value={s.start}
              onChange={(e) => updateSession(i, "start", e.target.value)}
              className="rounded border border-line bg-bg/80 px-1 py-0.5 text-3xs text-ink focus:border-accent focus:outline-none"
            />
            <span className="text-3xs text-ink-muted">–</span>
            <input
              type="time"
              value={s.end}
              onChange={(e) => updateSession(i, "end", e.target.value)}
              className="rounded border border-line bg-bg/80 px-1 py-0.5 text-3xs text-ink focus:border-accent focus:outline-none"
            />
            <button
              type="button"
              onClick={() => removeSession(i)}
              className="text-3xs text-err hover:underline"
            >
              ×
            </button>
          </div>
        ))}
      </div>

      <div className="flex items-center gap-2">
        <label className="w-20 shrink-0 text-3xs font-semibold text-ink-muted uppercase tracking-wider">
          HTF veto
        </label>
        <select
          value={htfVetoMode}
          onChange={(e) => setHtfVetoMode(e.target.value as HtfVetoMode)}
          className="rounded border border-line bg-bg/80 px-1.5 py-0.5 text-xs text-ink focus:border-accent focus:outline-none"
        >
          <option value="default">
            Default ({bot.strategy_default_htf_veto ? "on" : "off"})
          </option>
          <option value="on">Force ON</option>
          <option value="off">Force OFF</option>
        </select>
      </div>

      {paramKeys.length > 0 && (
        <div className="flex flex-col gap-1">
          <span className="text-3xs font-semibold text-ink-muted uppercase tracking-wider">
            Strategy params
          </span>
          <div className="flex max-h-48 flex-col gap-1 overflow-y-auto pr-1">
            {paramKeys.map((key) => {
              const defaultValue = bot.strategy_default_params[key];
              const draft = paramDrafts[key];
              const overridden = draftDiffersFromDefault(draft, defaultValue);
              return (
                <div key={key} className="flex items-center gap-1.5">
                  <span
                    className="min-w-0 flex-1 truncate text-[10px] text-ink"
                    title={`${key} (default: ${String(defaultValue)})`}
                  >
                    {key}
                  </span>
                  {typeof defaultValue === "boolean" ? (
                    <input
                      type="checkbox"
                      checked={Boolean(draft)}
                      onChange={(e) =>
                        setParamDrafts((prev) => ({ ...prev, [key]: e.target.checked }))
                      }
                      className="h-3 w-3"
                    />
                  ) : (
                    <input
                      type={typeof defaultValue === "number" ? "number" : "text"}
                      step={typeof defaultValue === "number" ? "any" : undefined}
                      value={String(draft)}
                      onChange={(e) =>
                        setParamDrafts((prev) => ({ ...prev, [key]: e.target.value }))
                      }
                      className="w-20 rounded border border-line bg-bg/80 px-1 py-0.5 text-[10px] text-ink focus:border-accent focus:outline-none"
                    />
                  )}
                  <button
                    type="button"
                    onClick={() => resetParam(key)}
                    disabled={!overridden}
                    title="Reset to default"
                    className="text-[10px] text-ink-muted hover:text-accent disabled:opacity-30"
                  >
                    ↺
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {error && <p className="text-[10px] text-err">{error}</p>}
      <button
        type="button"
        onClick={save}
        disabled={!canSave}
        className="self-start rounded border border-accent px-2 py-0.5 text-3xs font-semibold text-accent hover:bg-accent hover:text-bg disabled:opacity-40"
      >
        {saving ? "Saving…" : "Save config"}
      </button>
    </div>
  );
}
