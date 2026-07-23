"use client";

/** Pencil-icon inline rename for a strategy family — renames every version
 * that shares the current name, not just the one shown (§5). */

import { useState } from "react";
import { useActiveAccount } from "@/shared/api/account-context";
import { ApiError, renameStrategyVersion } from "@/shared/api/client";

export function RenameVersionInline({
  versionId,
  name,
  onRenamed,
}: {
  versionId: string;
  name: string;
  onRenamed: (newName: string) => void;
}) {
  const accountId = useActiveAccount();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(name);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function commit() {
    const trimmed = value.trim();
    if (!trimmed || trimmed === name) {
      setEditing(false);
      setValue(name);
      return;
    }
    if (!accountId) return;
    setBusy(true);
    setError(null);
    try {
      const renamed = await renameStrategyVersion(accountId, versionId, trimmed);
      onRenamed(renamed.name);
      setEditing(false);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "rename failed");
    } finally {
      setBusy(false);
    }
  }

  if (!editing) {
    return (
      <button
        type="button"
        className="cursor-pointer text-ink-muted hover:text-accent"
        onClick={() => {
          setValue(name);
          setError(null);
          setEditing(true);
        }}
        title="Rename this strategy"
      >
        ✎
      </button>
    );
  }

  return (
    <span className="inline-flex items-center gap-1">
      <input
        autoFocus
        className="rounded border border-accent bg-bg px-1 py-0.5 text-sm"
        value={value}
        disabled={busy}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit();
          if (e.key === "Escape") {
            setEditing(false);
            setValue(name);
          }
        }}
        onBlur={commit}
      />
      {error && <span className="text-xs text-err">{error}</span>}
    </span>
  );
}
