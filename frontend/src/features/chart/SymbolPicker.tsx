"use client";

/**
 * Search/add any symbol the connected broker offers (chart/watchlist only —
 * picking one shows its chart on demand, including live candle-close
 * updates while it's open, but does not by itself put the automated engine
 * live on it). A symbol only starts trading once a bot is applied to it via
 * BotSelector's "Apply to <symbol>" — that's the one deliberate step that
 * activates automated trading, persisting the symbol into
 * `configs/app.yaml` and hot-starting candle streaming for it.
 */

import { useEffect, useRef, useState } from "react";
import { ApiError, getBrokerSymbols, type BrokerSymbol } from "@/shared/api/client";

const DEBOUNCE_MS = 250;
const MIN_QUERY_LENGTH = 2;
const PAGE_SIZE = 20;

export function SymbolPicker({
  onAdd,
  favorites,
  onToggleFavorite,
}: {
  onAdd: (symbol: string) => void;
  favorites: string[];
  onToggleFavorite: (symbol: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const [results, setResults] = useState<BrokerSymbol[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const searching = query.trim().length >= MIN_QUERY_LENGTH;

  // Reset to the first page whenever the query changes or the picker opens —
  // otherwise a stale `page` from a previous search would apply to the new one.
  useEffect(() => {
    setPage(0);
  }, [query, open]);

  useEffect(() => {
    if (!open) return;
    if (query.trim().length > 0 && !searching) {
      // Between 1 char and MIN_QUERY_LENGTH: too short to search, not empty
      // enough to mean "browse everything" — just show the hint below.
      setResults(null);
      setError(null);
      return;
    }
    let cancelled = false;
    const runFetch = () =>
      getBrokerSymbols(searching ? query.trim() : undefined, PAGE_SIZE, page * PAGE_SIZE)
        .then(({ items, total: matchCount }) => {
          if (cancelled) return;
          setResults(items);
          setTotal(matchCount);
          setError(null);
        })
        .catch((e) => {
          if (cancelled) return;
          setResults([]);
          setTotal(0);
          setError(
            e instanceof ApiError
              ? e.message
              : "couldn't reach the broker — is the gateway connected?",
          );
        });
    // Only debounce actual searches — browsing (query empty) should feel
    // instant since it's triggered by an explicit click on Prev/Next/open.
    if (searching) {
      const timer = setTimeout(runFetch, DEBOUNCE_MS);
      return () => {
        cancelled = true;
        clearTimeout(timer);
      };
    }
    runFetch();
    return () => {
      cancelled = true;
    };
  }, [open, query, page, searching]);

  useEffect(() => {
    if (!open) return;
    function onClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, [open]);

  function select(symbol: BrokerSymbol) {
    onAdd(symbol.name);
    setOpen(false);
    setQuery("");
    setResults(null);
  }

  const tooShort = query.trim().length > 0 && !searching;
  const hasNextPage = (page + 1) * PAGE_SIZE < total;

  return (
    <div ref={containerRef} className="relative">
      <button
        className="cursor-pointer rounded border border-line px-2 py-1 text-xs text-ink-muted hover:border-accent hover:text-accent"
        onClick={() => setOpen((v) => !v)}
        type="button"
        title="Browse the broker's other symbols"
      >
        + Symbol
      </button>
      {open && (
        <div className="absolute top-full left-0 z-10 mt-1 w-72 rounded-md border border-line bg-panel p-2 shadow-lg">
          <input
            autoFocus
            className="w-full rounded border border-line bg-bg px-2 py-1 text-sm text-ink placeholder:text-ink-muted focus:border-accent focus:outline-none"
            placeholder="Search, or leave blank to browse all"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <div className="mt-2 max-h-64 overflow-y-auto">
            {tooShort ? (
              <p className="px-1 py-1 text-xs text-ink-muted">
                Type at least {MIN_QUERY_LENGTH} characters to search, or clear the box to browse
                all symbols.
              </p>
            ) : error ? (
              <p className="px-1 py-1 text-xs text-err">{error}</p>
            ) : results === null ? (
              <p className="px-1 py-1 text-xs text-ink-muted">
                {searching ? "Searching…" : "Loading…"}
              </p>
            ) : results.length === 0 ? (
              <p className="px-1 py-1 text-xs text-ink-muted">No matching symbols.</p>
            ) : (
              <ul className="flex flex-col">
                {results.map((s) => {
                  const isFavorite = favorites.includes(s.name);
                  return (
                    <li key={s.name} className="flex items-center gap-1 rounded hover:bg-bg">
                      <button
                        className="flex-1 cursor-pointer rounded px-2 py-1.5 text-left text-sm"
                        onClick={() => select(s)}
                        type="button"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-medium">{s.name}</span>
                          <span className="text-xs text-ink-muted">{s.path}</span>
                        </div>
                        <div className="truncate text-xs text-ink-muted">{s.description}</div>
                      </button>
                      <button
                        className={`cursor-pointer px-1.5 text-sm ${
                          isFavorite ? "text-accent" : "text-ink-muted hover:text-accent"
                        }`}
                        onClick={() => onToggleFavorite(s.name)}
                        type="button"
                        title={isFavorite ? `Unpin ${s.name}` : `Pin ${s.name}`}
                      >
                        {isFavorite ? "★" : "☆"}
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
          {!tooShort && !error && results !== null && total > 0 && (
            <div className="mt-2 flex items-center justify-between border-t border-line pt-2 text-xs text-ink-muted">
              <button
                className="cursor-pointer disabled:cursor-not-allowed disabled:opacity-40"
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                disabled={page === 0}
                type="button"
              >
                ← Prev
              </button>
              <span>
                {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, total)} of {total}
              </span>
              <button
                className="cursor-pointer disabled:cursor-not-allowed disabled:opacity-40"
                onClick={() => setPage((p) => (hasNextPage ? p + 1 : p))}
                disabled={!hasNextPage}
                type="button"
              >
                Next →
              </button>
            </div>
          )}
          <p className="mt-2 border-t border-line pt-2 text-xs text-ink-muted">
            Chart only — doesn&apos;t start automated trading. Applying a bot to this symbol
            from its chart is the step that does.
          </p>
        </div>
      )}
    </div>
  );
}
