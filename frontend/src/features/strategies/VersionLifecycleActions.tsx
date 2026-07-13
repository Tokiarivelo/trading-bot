"use client";

/** Pause/resume, archive, and delete buttons for a strategy version (§6.5).
 * Pause/resume only applies to the active version — it suspends live
 * evaluation via the StrategyRegistry without deactivating it, distinct
 * from the engine-wide kill switch. Archive retires a version (active or
 * not) with no replacement required. Delete is a hard, irreversible removal
 * and is rejected by the API while the version is active. */

import { useState } from "react";
import {
  ApiError,
  archiveStrategyVersion,
  deleteStrategyVersion,
  pauseStrategyVersion,
  resumeStrategyVersion,
  type StrategyVersionSummary,
} from "@/shared/api/client";

export function VersionLifecycleActions({
  version,
  onChanged,
  onDeleted,
}: {
  version: StrategyVersionSummary;
  /** Called after archive/pause/resume succeeds, so the caller can refetch. */
  onChanged: () => void;
  /** Called after a successful delete — the version no longer exists. */
  onDeleted: () => void;
}) {
  const [busy, setBusy] = useState<"pause" | "archive" | "delete" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run(action: "pause" | "archive" | "delete", fn: () => Promise<unknown>) {
    setBusy(action);
    setError(null);
    try {
      await fn();
      if (action === "delete") onDeleted();
      else onChanged();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : `${action} failed`);
    } finally {
      setBusy(null);
    }
  }

  function onTogglePause() {
    void run("pause", () =>
      version.paused ? resumeStrategyVersion(version.id) : pauseStrategyVersion(version.id),
    );
  }

  function onArchive() {
    if (!window.confirm(`Archive ${version.name} v${version.version}?`)) return;
    void run("archive", () => archiveStrategyVersion(version.id));
  }

  function onDelete() {
    if (
      !window.confirm(
        `Permanently delete ${version.name} v${version.version}? This cannot be undone.`,
      )
    )
      return;
    void run("delete", () => deleteStrategyVersion(version.id));
  }

  const isActive = version.status === "active";
  const isArchived = version.status === "archived";

  return (
    <div className="flex flex-wrap items-center gap-2">
      {isActive && (
        <button
          type="button"
          className={btnCls}
          disabled={busy !== null}
          onClick={onTogglePause}
        >
          {busy === "pause" ? "…" : version.paused ? "Resume" : "Pause"}
        </button>
      )}
      {!isArchived && (
        <button type="button" className={btnCls} disabled={busy !== null} onClick={onArchive}>
          {busy === "archive" ? "Archiving…" : "Archive"}
        </button>
      )}
      <button
        type="button"
        className={btnDangerCls}
        disabled={busy !== null || isActive}
        title={isActive ? "Archive this version before deleting it" : undefined}
        onClick={onDelete}
      >
        {busy === "delete" ? "Deleting…" : "Delete"}
      </button>
      {error && <span className="text-xs text-err">{error}</span>}
    </div>
  );
}

const btnCls =
  "cursor-pointer rounded border border-line px-2 py-1 text-xs hover:border-accent hover:text-accent disabled:cursor-not-allowed disabled:opacity-50";
const btnDangerCls =
  "cursor-pointer rounded border border-line px-2 py-1 text-xs hover:border-err hover:text-err disabled:cursor-not-allowed disabled:opacity-50";
