"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getStrategyVersions, type StrategyVersionSummary } from "@/shared/api/client";
import { DuplicateVersionForm } from "./DuplicateVersionForm";
import { StatusBadge } from "./StatusBadge";

/** Every recorded strategy version, newest first per name. Pass `name` to
 * restrict to one strategy family (used on the draft detail page once code
 * has been generated for it). A symbols column + text filter keep the list
 * scannable now that bots aren't implicitly limited to 3 symbols (§5). */
export function StrategyVersionList({ name }: { name?: string }) {
  const [versions, setVersions] = useState<StrategyVersionSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  useEffect(() => {
    getStrategyVersions(name)
      .then(setVersions)
      .catch(() => setError("failed to load strategy versions"));
  }, [name]);

  if (error) return <p className="p-4 text-sm text-err">{error}</p>;
  if (versions === null) return <p className="p-4 text-sm text-ink-muted">Loading…</p>;
  if (versions.length === 0) {
    return (
      <p className="p-4 text-sm text-ink-muted">
        No strategy versions yet — generate code from an approved draft to create one.
      </p>
    );
  }

  const query = filter.trim().toLowerCase();
  const filtered = query
    ? versions.filter(
        (v) =>
          v.name.toLowerCase().includes(query) ||
          (v.spec?.symbols ?? []).some((s) => s.toLowerCase().includes(query)),
      )
    : versions;

  return (
    <div className="flex flex-col gap-2 p-4">
      {!name && (
        <input
          className="w-64 rounded border border-line bg-bg px-2 py-1 text-sm text-ink placeholder:text-ink-muted focus:border-accent focus:outline-none"
          placeholder="Filter by name or symbol…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
      )}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] border-collapse text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs text-ink-muted">
              <th className="px-3 py-2 font-medium">Name</th>
              <th className="px-3 py-2 text-right font-medium">Version</th>
              <th className="px-3 py-2 font-medium">Symbols</th>
              <th className="px-3 py-2 font-medium">Source</th>
              <th className="px-3 py-2 font-medium">Status</th>
              <th className="px-3 py-2 font-medium">Created</th>
              <th className="px-3 py-2 font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((v) => (
              <tr key={v.id} className="border-b border-line last:border-0 hover:bg-bg/40">
                <td className="px-3 py-2">
                  <Link
                    href={`/strategies/versions/${v.id}`}
                    className="text-accent hover:underline"
                  >
                    {v.name}
                  </Link>
                </td>
                <td className="px-3 py-2 text-right">v{v.version}</td>
                <td className="px-3 py-2 text-ink-muted">
                  {v.spec?.symbols.length ? v.spec.symbols.join(", ") : "—"}
                </td>
                <td className="px-3 py-2 text-ink-muted">
                  {v.source === "ai_generated" ? "AI generated" : "Manual"}
                </td>
                <td className="px-3 py-2">
                  <StatusBadge status={v.status} />
                </td>
                <td className="px-3 py-2 text-ink-muted">{formatTime(v.created_at)}</td>
                <td className="px-3 py-2">
                  <DuplicateVersionForm versionId={v.id} sourceSymbols={v.spec?.symbols ?? []} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {filtered.length === 0 && (
          <p className="px-3 py-2 text-sm text-ink-muted">No versions match &quot;{filter}&quot;.</p>
        )}
      </div>
    </div>
  );
}

function formatTime(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toISOString().replace("T", " ").slice(0, 16);
}
