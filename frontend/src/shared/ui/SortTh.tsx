"use client";

import type { SortDir, SortState } from "@/shared/hooks/useSortableRows";

export function SortTh<K extends string>({
  label,
  sortKey,
  sort,
  onSort,
  align = "left",
  className = "",
}: {
  label: React.ReactNode;
  sortKey: K;
  sort: SortState<K>;
  onSort: (key: K) => void;
  align?: "left" | "right";
  /** Padding/font utilities — no default, since callers embed this in
   * tables with different row density (e.g. a compact docked panel vs. a
   * full-page history table). */
  className: string;
}) {
  const active = sort.key === sortKey;
  return (
    <th
      onClick={() => onSort(sortKey)}
      className={`cursor-pointer select-none hover:text-ink ${
        align === "right" ? "text-right" : "text-left"
      } ${active ? "text-ink" : ""} ${className}`}
      title={`Sort by ${typeof label === "string" ? label : sortKey}`}
    >
      {label}
      <SortArrow active={active} dir={sort.dir} />
    </th>
  );
}

function SortArrow({ active, dir }: { active: boolean; dir: SortDir }) {
  return (
    <span className={`ml-1 inline-block w-2 text-[10px] ${active ? "" : "opacity-0"}`}>
      {dir === "asc" ? "▲" : "▼"}
    </span>
  );
}
