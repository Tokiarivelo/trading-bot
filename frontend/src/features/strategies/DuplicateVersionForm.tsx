"use client";

/** "Duplicate" button + small form (new name + optional symbol retarget)
 * for forking a strategy version into a new family, then routing to the
 * new version's detail page (§5). */

import { useRouter } from "next/navigation";
import { useState } from "react";
import { ApiError, duplicateStrategyVersion } from "@/shared/api/client";
import { SymbolMultiSelect } from "./SymbolMultiSelect";

export function DuplicateVersionForm({
  versionId,
  sourceSymbols,
}: {
  versionId: string;
  sourceSymbols: string[];
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [retarget, setRetarget] = useState(false);
  const [symbols, setSymbols] = useState<string[]>(sourceSymbols);
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
      const result = await duplicateStrategyVersion(versionId, {
        name: trimmed,
        symbols: retarget ? symbols : undefined,
      });
      router.push(`/strategies/versions/${result.id}`);
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
        <span className="text-xs text-ink-muted">New strategy name</span>
        <input
          autoFocus
          className={inputCls}
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. gold_ema_pullback_btc"
        />
      </label>
      <label className="flex items-center gap-2 text-xs text-ink-muted">
        <input
          type="checkbox"
          checked={retarget}
          onChange={(e) => setRetarget(e.target.checked)}
        />
        Retarget to different symbols (rewrites the generated code and re-validates it)
      </label>
      {retarget && <SymbolMultiSelect value={symbols} onChange={setSymbols} />}
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
