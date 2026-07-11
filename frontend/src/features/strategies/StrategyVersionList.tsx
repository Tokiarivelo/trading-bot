"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getStrategyVersions, type StrategyVersionSummary } from "@/shared/api/client";
import { StatusBadge } from "./StatusBadge";

/** Every recorded strategy version, newest first per name. Pass `name` to
 * restrict to one strategy family (used on the draft detail page once code
 * has been generated for it). */
export function StrategyVersionList({ name }: { name?: string }) {
  const [versions, setVersions] = useState<StrategyVersionSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

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

  return (
    <div className="overflow-x-auto p-4">
      <table className="w-full min-w-[640px] border-collapse text-sm">
        <thead>
          <tr className="border-b border-line text-left text-xs text-ink-muted">
            <th className="px-3 py-2 font-medium">Name</th>
            <th className="px-3 py-2 text-right font-medium">Version</th>
            <th className="px-3 py-2 font-medium">Source</th>
            <th className="px-3 py-2 font-medium">Status</th>
            <th className="px-3 py-2 font-medium">Created</th>
          </tr>
        </thead>
        <tbody>
          {versions.map((v) => (
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
                {v.source === "ai_generated" ? "AI generated" : "Manual"}
              </td>
              <td className="px-3 py-2">
                <StatusBadge status={v.status} />
              </td>
              <td className="px-3 py-2 text-ink-muted">{formatTime(v.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function formatTime(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toISOString().replace("T", " ").slice(0, 16);
}
