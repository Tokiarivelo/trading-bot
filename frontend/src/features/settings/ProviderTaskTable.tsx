"use client";

import { useEffect, useState } from "react";
import {
  clearTaskProvider,
  listProviders,
  listTaskProviders,
  setTaskProvider,
  type ProviderInfo,
  type TaskProviderStatus,
} from "@/shared/api/client";
import { ProviderStatusBadge } from "./ProviderStatusBadge";
import { ProviderTestButton } from "./ProviderTestButton";

const TASK_LABELS: Record<string, string> = {
  pdf_extraction: "Document analysis (PDF → strategy)",
  code_generation: "Strategy code generation",
  ten_trade_review: "10-trade review",
  code_refinement: "Code refinement",
};

/** Not a real provider id — a settings-UI-only pseudo-provider. Picking it
 * sends `{ provider: "ollama", model: <hermes preset> }` to the backend
 * (§2.2 of AI_PROVIDER_SETTINGS_PLAN.md); there is no `hermes_agent` adapter. */
const HERMES_AGENT = "hermes_agent";

/** Sentinel `<select>` value for "none of the curated presets — type a model
 * id by hand", so the dropdown never silently forces an operator onto a
 * preset if this list of curated models goes stale. */
const CUSTOM_MODEL = "__custom__";

const inputCls =
  "rounded border border-line bg-bg px-2 py-1 text-sm text-ink placeholder:text-ink-muted focus:border-accent focus:outline-none";

interface RowDraft {
  provider: string; // a catalog provider id, or HERMES_AGENT
  model: string;
}

/** A row displays as "Hermes Agent" whenever its resolved provider/model is
 * ollama + one of the curated Hermes preset models — matched client-side
 * against the model string, per §8's note that there's no separate provider id. */
function draftFromStatus(status: { provider: string; model: string }, ollama?: ProviderInfo): RowDraft {
  if (status.provider === "ollama" && ollama?.presetModels?.some((p) => p.model === status.model)) {
    return { provider: HERMES_AGENT, model: status.model };
  }
  return { provider: status.provider, model: status.model };
}

export function ProviderTaskTable() {
  const [statuses, setStatuses] = useState<TaskProviderStatus[] | null>(null);
  const [providers, setProviders] = useState<ProviderInfo[] | null>(null);
  const [drafts, setDrafts] = useState<Record<string, RowDraft>>({});
  const [error, setError] = useState<string | null>(null);
  const [savingTask, setSavingTask] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([listTaskProviders(), listProviders()])
      .then(([taskStatuses, providerList]) => {
        const ollama = providerList.find((p) => p.id === "ollama");
        setStatuses(taskStatuses);
        setProviders(providerList);
        setDrafts(Object.fromEntries(taskStatuses.map((s) => [s.task, draftFromStatus(s, ollama)])));
      })
      .catch(() => setError("Failed to load AI provider settings."));
  }, []);

  function setDraft(task: string, next: Partial<RowDraft>) {
    setDrafts((prev) => ({ ...prev, [task]: { ...prev[task], ...next } }));
  }

  async function save(task: string) {
    const draft = drafts[task];
    if (!draft) return;
    const provider = draft.provider === HERMES_AGENT ? "ollama" : draft.provider;
    const model = draft.provider === HERMES_AGENT ? draft.model || "hermes3:8b" : draft.model;
    setSavingTask(task);
    setError(null);
    try {
      const updated = await setTaskProvider(task, provider, model);
      applyUpdatedStatus(updated);
    } catch {
      setError(`Failed to save the provider for "${task}".`);
    } finally {
      setSavingTask(null);
    }
  }

  async function reset(task: string) {
    setSavingTask(task);
    setError(null);
    try {
      const updated = await clearTaskProvider(task);
      applyUpdatedStatus(updated);
    } catch {
      setError(`Failed to reset the provider for "${task}".`);
    } finally {
      setSavingTask(null);
    }
  }

  function applyUpdatedStatus(updated: TaskProviderStatus) {
    setStatuses((prev) => (prev ? prev.map((s) => (s.task === updated.task ? updated : s)) : prev));
    setDrafts((prev) => ({
      ...prev,
      [updated.task]: draftFromStatus(updated, providers?.find((p) => p.id === "ollama")),
    }));
  }

  if (error && !statuses) return <p className="p-4 text-sm text-err">{error}</p>;
  if (!statuses || !providers) return <p className="p-4 text-sm text-ink-muted">Loading…</p>;

  const ollama = providers.find((p) => p.id === "ollama");
  const dropdownOptions = [
    ...providers.map((p) => ({ id: p.id, label: p.label })),
    ...(ollama ? [{ id: HERMES_AGENT, label: "Hermes Agent" }] : []),
  ];

  return (
    <div className="flex flex-col gap-3 p-4">
      {error && <p className="text-sm text-err">{error}</p>}
      <div className="overflow-x-auto rounded-md border border-line bg-panel">
        <table className="w-full min-w-[760px] border-collapse text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs text-ink-muted">
              <th className="px-3 py-2 font-medium">Task</th>
              <th className="px-3 py-2 font-medium">Provider</th>
              <th className="px-3 py-2 font-medium">Model</th>
              <th className="px-3 py-2 font-medium">Source</th>
              <th className="px-3 py-2 font-medium">Status</th>
              <th className="px-3 py-2 font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {statuses.map((status) => {
              const draft = drafts[status.task] ?? draftFromStatus(status, ollama);
              const statusDraft = draftFromStatus(status, ollama);
              const isHermes = draft.provider === HERMES_AGENT;
              const isDirty = draft.provider !== statusDraft.provider || draft.model !== statusDraft.model;
              const isSaving = savingTask === status.task;
              return (
                <tr key={status.task} className="border-b border-line align-top last:border-0">
                  <td className="px-3 py-2">{TASK_LABELS[status.task] ?? status.task}</td>
                  <td className="px-3 py-2">
                    <select
                      className={inputCls}
                      value={draft.provider}
                      onChange={(e) => {
                        const nextProvider = e.target.value;
                        const nextProviderId =
                          nextProvider === HERMES_AGENT ? "ollama" : nextProvider;
                        const nextPresets =
                          nextProvider === HERMES_AGENT
                            ? (ollama?.presetModels ?? [])
                            : (providers.find((p) => p.id === nextProviderId)?.presetModels ??
                              []);
                        setDraft(status.task, {
                          provider: nextProvider,
                          model: nextPresets[0]?.model ?? "",
                        });
                      }}
                    >
                      {dropdownOptions.map((opt) => (
                        <option key={opt.id} value={opt.id}>
                          {opt.label}
                        </option>
                      ))}
                    </select>
                    {draft.provider === "openclaw" && (
                      <span className="ml-2 rounded border border-err px-1.5 py-0.5 text-[10px] whitespace-nowrap text-err">
                        beta / unverified
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {(() => {
                      const presets = isHermes
                        ? (ollama?.presetModels ?? [])
                        : (providers.find((p) => p.id === draft.provider)?.presetModels ?? []);
                      if (presets.length === 0) {
                        return (
                          <input
                            className={`${inputCls} w-40`}
                            value={draft.model}
                            onChange={(e) => setDraft(status.task, { model: e.target.value })}
                            placeholder="model id"
                          />
                        );
                      }
                      const matched = presets.some((p) => p.model === draft.model);
                      const selectValue = matched ? draft.model : CUSTOM_MODEL;
                      return (
                        <div className="flex flex-col gap-1">
                          <select
                            className={`${inputCls} w-48`}
                            value={selectValue}
                            onChange={(e) => {
                              const value = e.target.value;
                              setDraft(status.task, {
                                model: value === CUSTOM_MODEL ? "" : value,
                              });
                            }}
                          >
                            {presets.map((preset) => (
                              <option key={preset.model} value={preset.model}>
                                {preset.label}
                              </option>
                            ))}
                            <option value={CUSTOM_MODEL}>Custom…</option>
                          </select>
                          {selectValue === CUSTOM_MODEL && (
                            <input
                              className={`${inputCls} w-40`}
                              value={draft.model}
                              onChange={(e) => setDraft(status.task, { model: e.target.value })}
                              placeholder="model id"
                              autoFocus
                            />
                          )}
                        </div>
                      );
                    })()}
                  </td>
                  <td className="px-3 py-2 text-ink-muted">{status.source}</td>
                  <td className="px-3 py-2">
                    <ProviderStatusBadge configured={status.configured} />
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <button
                        type="button"
                        disabled={!isDirty || isSaving}
                        onClick={() => save(status.task)}
                        className="rounded border border-accent px-2 py-1 text-xs whitespace-nowrap text-accent disabled:opacity-40"
                      >
                        Save
                      </button>
                      <button
                        type="button"
                        disabled={status.source === "default" || isSaving}
                        onClick={() => reset(status.task)}
                        className="rounded border border-line px-2 py-1 text-xs whitespace-nowrap text-ink-muted hover:text-ink disabled:opacity-40"
                      >
                        Reset to default
                      </button>
                      <ProviderTestButton
                        provider={draft.provider === HERMES_AGENT ? "ollama" : draft.provider}
                      />
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
