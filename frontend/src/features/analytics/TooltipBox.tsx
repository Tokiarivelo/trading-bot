"use client";

import { money } from "./format";
import type { TooltipState } from "./chartTooltip";

/** Floating crosshair readout shared by every bot comparison chart. */
export function TooltipBox({ tooltip, containerWidth }: { tooltip: TooltipState; containerWidth: number }) {
  return (
    <div
      className="pointer-events-none absolute z-10 rounded border border-line bg-panel/95 px-2.5 py-1.5 text-xs shadow-lg backdrop-blur-sm"
      style={{
        left: Math.min(tooltip.x + 12, Math.max(containerWidth - 170, 0)),
        top: Math.max(tooltip.y - 12, 8),
      }}
    >
      <div className="mb-1 text-ink-muted">{tooltip.time}</div>
      {tooltip.rows.map((row) => (
        <div key={row.botName} className="flex items-center gap-1.5">
          <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: row.color }} />
          <span className="text-ink">{row.botName}</span>
          <span className={row.value >= 0 ? "text-ok" : "text-err"}>{money(row.value, { sign: true })}</span>
        </div>
      ))}
    </div>
  );
}
