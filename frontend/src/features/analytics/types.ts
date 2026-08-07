/** Shared types for the `analytics` feature folder — used by more than one
 * file here, so per CLAUDE.md's hook/component-splitting rule they live in
 * this `types.ts` rather than being re-exported from a component. First
 * shared-types file in this feature folder. */

import type { RegimeAnalytics } from "@/shared/api/client";

/** The three regime axes `GET .../journal/analytics/regimes` slices bots by
 * (OBSERVABILITY_PLAN.md Phase 6) — mirrors the backend's `dimension`
 * literal union exactly, so a new dimension added there is a type error
 * here until `RegimeAnalyticsPanel`'s tabs are updated to match. */
export type RegimeDimension = RegimeAnalytics["dimension"];

/** Sortable columns on `RegimeAnalyticsPanel`'s per-dimension table. */
export type RegimeAnalyticsSortKey =
  | "bot_name"
  | "bucket"
  | "trade_count"
  | "win_rate"
  | "profit_factor"
  | "expectancy"
  | "total_profit";
