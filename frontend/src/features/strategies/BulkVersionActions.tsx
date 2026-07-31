"use client";

/** Multi-row activate/archive/delete toolbar for the Bot Library table — the
 * bulk counterpart to VersionLifecycleActions. Runs one request at a time
 * rather than in parallel: activating two versions from the same strategy
 * family back-to-back would otherwise race, since each activation archives
 * whatever was previously active for that family. */

import { useState } from "react";
import { useActiveAccount } from "@/shared/api/account-context";
import {
  ApiError,
  activateStrategyVersion,
  archiveStrategyVersion,
  deleteStrategyVersion,
} from "@/shared/api/client";

type BulkAction = "activate" | "archive" | "delete";

const ACTION_FNS: Record<BulkAction, (accountId: string, id: string) => Promise<unknown>> = {
  activate: activateStrategyVersion,
  archive: archiveStrategyVersion,
  delete: deleteStrategyVersion,
};

const CONFIRM_MESSAGE: Partial<Record<BulkAction, (count: number) => string>> = {
  delete: (count) => `Permanently delete ${count} version(s)? This cannot be undone.`,
  archive: (count) => `Archive ${count} version(s)?`,
};

export function BulkVersionActions({
  selectedIds,
  onDone,
}: {
  selectedIds: string[];
  /** Called once every request has settled, whatever the per-item outcome —
   * the caller reloads the table and clears the selection. */
  onDone: () => void;
}) {
  const accountId = useActiveAccount();
  const [busy, setBusy] = useState<BulkAction | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run(action: BulkAction) {
    if (!accountId || selectedIds.length === 0) return;
    const confirmMessage = CONFIRM_MESSAGE[action]?.(selectedIds.length);
    if (confirmMessage && !window.confirm(confirmMessage)) return;

    setBusy(action);
    setError(null);
    const failures: string[] = [];
    for (const id of selectedIds) {
      try {
        await ACTION_FNS[action](accountId, id);
      } catch (e) {
        failures.push(e instanceof ApiError ? e.message : id);
      }
    }
    setBusy(null);
    if (failures.length > 0) {
      setError(`${failures.length} of ${selectedIds.length} failed: ${failures.join("; ")}`);
    }
    onDone();
  }

  if (selectedIds.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-accent/30 bg-accent/5 px-3 py-2">
      <span className="text-xs font-semibold text-ink">{selectedIds.length} selected</span>
      <button type="button" className={pillCls} disabled={busy !== null} onClick={() => run("activate")}>
        {busy === "activate" ? "Activating…" : "Activate"}
      </button>
      <button type="button" className={pillCls} disabled={busy !== null} onClick={() => run("archive")}>
        {busy === "archive" ? "Archiving…" : "Archive"}
      </button>
      <button type="button" className={pillDangerCls} disabled={busy !== null} onClick={() => run("delete")}>
        {busy === "delete" ? "Deleting…" : "Delete"}
      </button>
      {error && <span className="text-xs text-err">{error}</span>}
    </div>
  );
}

const pillCls =
  "cursor-pointer rounded border border-line bg-bg/60 px-2.5 py-1 text-xs hover:border-accent hover:text-accent disabled:cursor-not-allowed disabled:opacity-50";
const pillDangerCls =
  "cursor-pointer rounded border border-line bg-bg/60 px-2.5 py-1 text-xs hover:border-err hover:text-err disabled:cursor-not-allowed disabled:opacity-50";
