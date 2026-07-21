import type { BacktestSignal } from "@/shared/api/client";

/** Display metadata per signal outcome, shared by the report detail page's
 * signals table and the chart's signals dock/markers so the same outcome
 * always reads the same everywhere. `token` is the design-token CSS variable
 * (from globals.css `@theme`) for canvas rendering (chart markers), where
 * Tailwind classes can't reach. */
export const SIGNAL_OUTCOME_META: Record<
  BacktestSignal["outcome"],
  { label: string; className: string; token: string }
> = {
  opened: { label: "opened", className: "text-ok", token: "--color-ok" },
  htf_veto: { label: "HTF veto", className: "text-sell", token: "--color-sell" },
  risk_rejected: { label: "risk rejected", className: "text-err", token: "--color-err" },
  spread_veto: { label: "spread veto", className: "text-err", token: "--color-err" },
  broker_rejected: { label: "broker rejected", className: "text-err", token: "--color-err" },
  skipped: { label: "skipped", className: "text-ink-muted", token: "--color-ink-muted" },
};
