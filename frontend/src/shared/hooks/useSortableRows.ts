"use client";

import { useMemo, useState } from "react";

export type SortDir = "asc" | "desc";

export interface SortState<K extends string> {
  key: K;
  dir: SortDir;
}

/** Client-side sort over an in-memory row array, driven by clicking a
 * `SortTh` column header. `getValue` maps a row + column key to the
 * comparable primitive for that column (string/number, or null to always
 * sort last) — kept separate from the rows themselves so callers can sort
 * on derived values (e.g. a skill looked up by ticket) that aren't a plain
 * field on the row type. */
export function useSortableRows<T, K extends string>(
  rows: T[],
  getValue: (row: T, key: K) => string | number | null,
  initial: SortState<K>,
) {
  const [sort, setSort] = useState<SortState<K>>(initial);

  const sorted = useMemo(() => {
    const withValues = rows.map((row) => ({ row, value: getValue(row, sort.key) }));
    withValues.sort((a, b) => {
      if (a.value === b.value) return 0;
      if (a.value === null) return 1;
      if (b.value === null) return -1;
      const cmp = a.value < b.value ? -1 : 1;
      return sort.dir === "asc" ? cmp : -cmp;
    });
    return withValues.map((w) => w.row);
  }, [rows, sort, getValue]);

  function toggle(key: K) {
    setSort((prev) =>
      prev.key === key ? { key, dir: prev.dir === "asc" ? "desc" : "asc" } : { key, dir: "asc" },
    );
  }

  return { sorted, sort, toggle };
}
