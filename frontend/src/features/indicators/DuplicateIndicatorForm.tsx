"use client";

/** "Duplicate" button + small inline form (new name only) for cloning an
 * indicator's code into a brand-new row — mirrors
 * features/strategies/DuplicateVersionForm.tsx, minus the symbol-retarget
 * option (indicators aren't symbol-scoped). */

import { useRouter } from "next/navigation";
import { useState } from "react";
import { ApiError, duplicateIndicator } from "@/shared/api/client";

export function DuplicateIndicatorForm({
  indicatorId,
  onDuplicated,
}: {
  indicatorId: string;
  onDuplicated?: () => void;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    e.stopPropagation();
    const trimmed = name.trim();
    if (!trimmed) {
      setError("name is required");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await duplicateIndicator(indicatorId, trimmed);
      onDuplicated?.();
      router.push(`/indicators/${result.id}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "duplicate failed");
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        className={btnCls}
        onClick={(e) => {
          e.stopPropagation();
          e.preventDefault();
          setOpen(true);
        }}
      >
        Duplicate
      </button>
    );
  }

  return (
    <form
      onClick={(e) => e.stopPropagation()}
      onSubmit={onSubmit}
      className="flex flex-col gap-2 rounded-md border border-line bg-panel p-3 text-sm"
    >
      <label className="flex flex-col gap-1">
        <span className="text-xs text-ink-muted">New indicator name</span>
        <input
          autoFocus
          className={inputCls}
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. sma_20_copy"
        />
      </label>
      {error && <p className="text-xs text-err">{error}</p>}
      <div className="flex gap-2">
        <button type="submit" disabled={busy} className={btnAccentCls}>
          {busy ? "Duplicating…" : "Duplicate"}
        </button>
        <button
          type="button"
          className={btnCls}
          onClick={() => {
            setOpen(false);
            setError(null);
          }}
        >
          Cancel
        </button>
      </div>
    </form>
  );
}

const inputCls =
  "rounded border border-line bg-bg px-2 py-1 text-ink placeholder:text-ink-muted focus:border-accent focus:outline-none";
const btnCls =
  "cursor-pointer rounded border border-line px-2 py-1 text-xs hover:border-accent hover:text-accent";
const btnAccentCls =
  "cursor-pointer rounded border border-accent px-3 py-1 text-accent hover:bg-accent hover:text-bg disabled:cursor-not-allowed disabled:opacity-50";
