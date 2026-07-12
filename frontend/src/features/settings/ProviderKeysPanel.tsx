"use client";

import { useEffect, useState } from "react";
import {
  clearProviderKey,
  listProviders,
  setProviderKey,
  type ProviderInfo,
} from "@/shared/api/client";
import { ProviderStatusBadge } from "./ProviderStatusBadge";

const inputCls =
  "w-48 rounded border border-line bg-bg px-2 py-1 text-sm text-ink placeholder:text-ink-muted focus:border-accent focus:outline-none";

/** API-key management for every provider that takes one — separate from
 * ProviderTaskTable's per-task provider/model pick, since a key is scoped
 * to the provider itself, not any one task. Keys are never displayed once
 * saved: the input clears and the row's status flips to "Configured". */
export function ProviderKeysPanel() {
  const [providers, setProviders] = useState<ProviderInfo[] | null>(null);
  const [inputs, setInputs] = useState<Record<string, string>>({});
  const [busyProvider, setBusyProvider] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  function load() {
    return listProviders()
      .then(setProviders)
      .catch(() => setError("Failed to load AI providers."));
  }

  useEffect(() => {
    load();
  }, []);

  async function save(provider: string) {
    const apiKey = inputs[provider]?.trim();
    if (!apiKey) return;
    setBusyProvider(provider);
    setError(null);
    try {
      await setProviderKey(provider, apiKey);
      setInputs((prev) => ({ ...prev, [provider]: "" }));
      await load();
    } catch {
      setError(`Failed to save the API key for "${provider}".`);
    } finally {
      setBusyProvider(null);
    }
  }

  async function clear(provider: string) {
    setBusyProvider(provider);
    setError(null);
    try {
      await clearProviderKey(provider);
      await load();
    } catch {
      setError(`Failed to clear the API key for "${provider}".`);
    } finally {
      setBusyProvider(null);
    }
  }

  if (error && !providers) return <p className="p-4 text-sm text-err">{error}</p>;
  if (!providers) return <p className="p-4 text-sm text-ink-muted">Loading…</p>;

  const keyProviders = providers.filter((p) => p.needsSecret);

  return (
    <div className="flex flex-col gap-3 p-4">
      {error && <p className="text-sm text-err">{error}</p>}
      <div className="overflow-x-auto rounded-md border border-line bg-panel">
        <table className="w-full min-w-[640px] border-collapse text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs text-ink-muted">
              <th className="px-3 py-2 font-medium">Provider</th>
              <th className="px-3 py-2 font-medium">Status</th>
              <th className="px-3 py-2 font-medium">API key</th>
              <th className="px-3 py-2 font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {keyProviders.map((provider) => {
              const isBusy = busyProvider === provider.id;
              return (
                <tr key={provider.id} className="border-b border-line align-top last:border-0">
                  <td className="px-3 py-2">
                    <div className="font-medium text-ink">{provider.label}</div>
                    <div className="max-w-xs text-xs text-ink-muted">{provider.description}</div>
                  </td>
                  <td className="px-3 py-2">
                    <ProviderStatusBadge configured={provider.configured} />
                  </td>
                  <td className="px-3 py-2">
                    <input
                      type="password"
                      autoComplete="off"
                      className={inputCls}
                      value={inputs[provider.id] ?? ""}
                      onChange={(e) =>
                        setInputs((prev) => ({ ...prev, [provider.id]: e.target.value }))
                      }
                      placeholder={provider.configured ? "•••••••• (set)" : "paste API key"}
                    />
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <button
                        type="button"
                        disabled={!inputs[provider.id]?.trim() || isBusy}
                        onClick={() => save(provider.id)}
                        className="rounded border border-accent px-2 py-1 text-xs whitespace-nowrap text-accent disabled:opacity-40"
                      >
                        Save
                      </button>
                      <button
                        type="button"
                        disabled={!provider.configured || isBusy}
                        onClick={() => clear(provider.id)}
                        className="rounded border border-line px-2 py-1 text-xs whitespace-nowrap text-ink-muted hover:text-ink disabled:opacity-40"
                      >
                        Clear
                      </button>
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
