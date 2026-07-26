"use client";

/**
 * Generic single-select combobox: a button that opens a search-filterable
 * dropdown, for any option list too long to scan as a plain `<select>`
 * (e.g. picking one strategy out of a growing bot library). Filtering is
 * client-side over the `options` passed in — for a list that must be
 * fetched/paginated from a remote source, compose a search box against that
 * API instead (see `SymbolMultiSelect`, which does exactly that for a
 * multi-select).
 */

import { ChevronDown, Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

export interface SearchableSelectOption {
  value: string;
  label: string;
  /** Small muted annotation shown after the label, e.g. "(inactive)". */
  hint?: string;
}

export function SearchableSelect({
  options,
  value,
  onChange,
  placeholder = "Search…",
  disabled = false,
  className = "",
  emptyMessage = "No matches.",
}: {
  options: SearchableSelectOption[];
  value: string | null;
  onChange: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
  className?: string;
  emptyMessage?: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [highlighted, setHighlighted] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const selected = options.find((o) => o.value === value) ?? null;

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (needle === "") return options;
    return options.filter(
      (o) =>
        o.label.toLowerCase().includes(needle) || o.value.toLowerCase().includes(needle),
    );
  }, [options, query]);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setHighlighted(0);
    // Focus after the dropdown mounts so the click that opened it doesn't
    // immediately blur the input.
    const id = requestAnimationFrame(() => inputRef.current?.focus());
    return () => cancelAnimationFrame(id);
  }, [open]);

  useEffect(() => {
    setHighlighted(0);
  }, [query]);

  useEffect(() => {
    if (!open) return;
    function onClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, [open]);

  function select(option: SearchableSelectOption) {
    onChange(option.value);
    setOpen(false);
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlighted((i) => Math.min(i + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlighted((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const option = filtered[highlighted];
      if (option) select(option);
    } else if (e.key === "Escape") {
      e.preventDefault();
      setOpen(false);
    }
  }

  return (
    <div ref={containerRef} className={`relative ${className}`}>
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between gap-1.5 rounded border border-line bg-bg/80 px-2 py-1 text-left text-xs text-ink focus:border-accent focus:ring-1 focus:ring-accent focus:outline-none disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-200"
      >
        <span className="truncate">
          {selected ? (
            <>
              {selected.label}
              {selected.hint && <span className="ml-1 text-ink-muted">{selected.hint}</span>}
            </>
          ) : (
            <span className="text-ink-muted">{placeholder}</span>
          )}
        </span>
        <ChevronDown size={12} className="shrink-0 text-ink-muted" />
      </button>

      {open && (
        <div className="absolute top-full left-0 z-10 mt-1 w-full min-w-[10rem] rounded-md border border-line bg-panel p-1 shadow-lg">
          <div className="flex items-center gap-1.5 rounded border border-line bg-bg px-2 py-1">
            <Search size={12} className="shrink-0 text-ink-muted" />
            <input
              ref={inputRef}
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder="Type to search…"
              className="w-full bg-transparent text-xs text-ink placeholder:text-ink-muted focus:outline-none"
            />
          </div>
          {filtered.length === 0 ? (
            <p className="px-2 py-1.5 text-xs text-ink-muted">{emptyMessage}</p>
          ) : (
            <ul className="mt-1 max-h-56 overflow-y-auto">
              {filtered.map((o, i) => (
                <li key={o.value}>
                  <button
                    type="button"
                    onMouseEnter={() => setHighlighted(i)}
                    onClick={() => select(o)}
                    className={`flex w-full items-center justify-between gap-2 rounded px-2 py-1 text-left text-xs transition-colors duration-100 ${
                      i === highlighted ? "bg-accent/15 text-accent" : "text-ink hover:bg-bg"
                    } ${o.value === value ? "font-semibold" : ""}`}
                  >
                    <span className="truncate">{o.label}</span>
                    {o.hint && <span className="shrink-0 text-ink-muted">{o.hint}</span>}
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
