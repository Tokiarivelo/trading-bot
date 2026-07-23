"use client";

/**
 * Multi-select built on the broker's real symbol catalog (same
 * `getBrokerSymbols` chart/SymbolPicker already queries), so a strategy's
 * `symbols` list is picked from tradeable symbols instead of hand-typed
 * free text (§5 of the chart/bot UX checklist).
 */

import { useEffect, useRef, useState } from "react";
import { useActiveAccount } from "@/shared/api/account-context";
import { ApiError, getBrokerSymbols, type BrokerSymbol } from "@/shared/api/client";

const DEBOUNCE_MS = 250;
const MIN_QUERY_LENGTH = 2;
const PAGE_SIZE = 20;

export function SymbolMultiSelect({
  value,
  onChange,
  disabled = false,
}: {
  value: string[];
  onChange: (symbols: string[]) => void;
  disabled?: boolean;
}) {
  const accountId = useActiveAccount();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [results, setResults] = useState<BrokerSymbol[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open || !accountId || query.trim().length < MIN_QUERY_LENGTH) {
      setResults(null);
      setError(null);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      getBrokerSymbols(accountId, query.trim(), PAGE_SIZE, 0)
        .then(({ items }) => {
          if (cancelled) return;
          setResults(items);
          setError(null);
        })
        .catch((e) => {
          if (cancelled) return;
          setResults([]);
          setError(
            e instanceof ApiError ? e.message : "couldn't reach the broker — is the gateway connected?",
          );
        });
    }, DEBOUNCE_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [accountId, open, query]);

  useEffect(() => {
    if (!open) return;
    function onClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, [open]);

  function add(symbol: string) {
    if (!value.includes(symbol)) onChange([...value, symbol]);
    setQuery("");
  }

  function remove(symbol: string) {
    onChange(value.filter((s) => s !== symbol));
  }

  const tooShort = query.trim().length > 0 && query.trim().length < MIN_QUERY_LENGTH;

  return (
    <div ref={containerRef} className="relative flex flex-col gap-1">
      <div className="flex flex-wrap gap-1">
        {value.length === 0 && (
          <span className="text-xs text-ink-muted">No symbols selected.</span>
        )}
        {value.map((s) => (
          <span
            key={s}
            className="flex items-center gap-1 rounded border border-line px-2 py-0.5 text-xs"
          >
            {s}
            {!disabled && (
              <button
                type="button"
                className="cursor-pointer text-ink-muted hover:text-err"
                onClick={() => remove(s)}
                title={`Remove ${s}`}
              >
                ×
              </button>
            )}
          </span>
        ))}
      </div>
      {!disabled && (
        <input
          className="rounded border border-line bg-bg px-2 py-1 text-sm text-ink placeholder:text-ink-muted focus:border-accent focus:outline-none"
          placeholder="Search the broker's symbol catalog…"
          value={query}
          onFocus={() => setOpen(true)}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
        />
      )}
      {open && query.trim().length > 0 && (
        <div className="absolute top-full left-0 z-10 mt-1 w-full rounded-md border border-line bg-panel p-1 shadow-lg">
          {tooShort ? (
            <p className="px-2 py-1 text-xs text-ink-muted">
              Type at least {MIN_QUERY_LENGTH} characters to search.
            </p>
          ) : error ? (
            <p className="px-2 py-1 text-xs text-err">{error}</p>
          ) : results === null ? (
            <p className="px-2 py-1 text-xs text-ink-muted">Searching…</p>
          ) : results.length === 0 ? (
            <p className="px-2 py-1 text-xs text-ink-muted">No matching symbols.</p>
          ) : (
            <ul className="max-h-56 overflow-y-auto">
              {results.map((s) => (
                <li key={s.name}>
                  <button
                    type="button"
                    className="flex w-full items-center justify-between gap-2 rounded px-2 py-1 text-left text-sm hover:bg-bg disabled:cursor-not-allowed disabled:opacity-40"
                    onClick={() => add(s.name)}
                    disabled={value.includes(s.name)}
                  >
                    <span className="font-medium">{s.name}</span>
                    <span className="text-xs text-ink-muted">{s.path}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
