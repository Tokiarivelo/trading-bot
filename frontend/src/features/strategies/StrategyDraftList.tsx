"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getStrategyDrafts, type StrategyDraft } from "@/shared/api/client";
import { StatusBadge } from "./StatusBadge";
import { StrategyUploadForm } from "./StrategyUploadForm";

/** Every PDF-derived draft, newest first, with the upload form above it —
 * pass `showUploadForm={false}` when an embedding page (e.g. the Bots hub)
 * already renders its own generation form above this list. */
export function StrategyDraftList({ showUploadForm = true }: { showUploadForm?: boolean } = {}) {
  const [drafts, setDrafts] = useState<StrategyDraft[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getStrategyDrafts()
      .then(setDrafts)
      .catch(() => setError("failed to load strategy drafts"));
  }, []);

  return (
    <div className="flex flex-col gap-3 p-4">
      {showUploadForm && <StrategyUploadForm />}
      {error && <p className="text-sm text-err">{error}</p>}
      {drafts === null ? (
        <p className="text-sm text-ink-muted">Loading…</p>
      ) : drafts.length === 0 ? (
        <p className="text-sm text-ink-muted">
          No strategy drafts yet — upload a PDF describing a manual trading method above.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-md border border-line bg-panel">
          <table className="w-full min-w-[560px] border-collapse text-sm">
            <thead>
              <tr className="border-b border-line text-left text-xs text-ink-muted">
                <th className="px-3 py-2 font-medium">Name</th>
                <th className="px-3 py-2 font-medium">Symbols</th>
                <th className="px-3 py-2 font-medium">Source PDF</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Created</th>
              </tr>
            </thead>
            <tbody>
              {drafts.map((d) => (
                <tr key={d.id} className="border-b border-line last:border-0 hover:bg-bg/40">
                  <td className="px-3 py-2">
                    <Link
                      href={`/strategies/drafts/${d.id}`}
                      className="text-accent hover:underline"
                    >
                      {d.effective_spec.name}
                    </Link>
                  </td>
                  <td className="px-3 py-2 text-ink-muted">
                    {d.effective_spec.symbols.length ? d.effective_spec.symbols.join(", ") : "—"}
                  </td>
                  <td className="px-3 py-2 text-ink-muted">{d.source_filename}</td>
                  <td className="px-3 py-2">
                    <StatusBadge status={d.status} />
                  </td>
                  <td className="px-3 py-2 text-ink-muted">{formatTime(d.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function formatTime(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toISOString().replace("T", " ").slice(0, 16);
}
