"use client";

/** Inline-removable symbol chips for a Bot Library row (§6.5). Removing a
 * chip patches the version's spec snapshot only — same annotation-only
 * write as the version detail page's spec editor, never the generated code.
 * An empty symbol list is left as-is (matches duplicateStrategyVersion's own
 * "omit symbols" case) rather than blocked client-side; the version simply
 * won't route to anything live until symbols are added back. */

import { useState } from "react";
import { useActiveAccount } from "@/shared/api/account-context";
import {
  ApiError,
  updateStrategyVersionSpec,
  type ExtractedStrategySpec,
} from "@/shared/api/client";

export function SymbolChipsEditor({
  versionId,
  spec,
  onUpdated,
}: {
  versionId: string;
  spec: ExtractedStrategySpec;
  /** Called with the confirmed post-patch spec once removal succeeds. */
  onUpdated: (spec: ExtractedStrategySpec) => void;
}) {
  const accountId = useActiveAccount();
  const [removing, setRemoving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function removeSymbol(symbol: string) {
    if (!accountId) return;
    setRemoving(symbol);
    setError(null);
    const nextSpec = { ...spec, symbols: spec.symbols.filter((s) => s !== symbol) };
    try {
      const updated = await updateStrategyVersionSpec(accountId, versionId, nextSpec);
      onUpdated(updated.spec ?? nextSpec);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : `failed to remove ${symbol}`);
    } finally {
      setRemoving(null);
    }
  }

  if (spec.symbols.length === 0) {
    return <span className="text-ink-muted">—</span>;
  }

  return (
    <div className="flex flex-col gap-1">
      <span className="flex flex-wrap gap-1">
        {spec.symbols.map((sym) => (
          <span
            key={sym}
            className="inline-flex items-center gap-1 text-2xs bg-bg px-1.5 py-0.5 rounded border border-line font-mono text-ink/80"
          >
            {sym}
            <button
              type="button"
              className="cursor-pointer leading-none text-ink-muted hover:text-err disabled:cursor-not-allowed disabled:opacity-40"
              disabled={removing !== null}
              title={`Remove ${sym} from this version`}
              onClick={() => removeSymbol(sym)}
            >
              {removing === sym ? "…" : "×"}
            </button>
          </span>
        ))}
      </span>
      {error && <span className="text-2xs text-err">{error}</span>}
    </div>
  );
}
