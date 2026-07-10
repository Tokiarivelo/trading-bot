---
name: trade-review
description: Pull the last N trades from the journal, correlate them with market snapshots, and write a human-readable review of what worked and what failed.
---

# Trade Review

Review the last N trades (`$ARGUMENTS`, default 10) from the journal.

## Steps
1. Fetch trades via the journal API/CLI, including per-trade market context
   snapshots (M5 and HTF candles at entry/exit), spread at entry, skill active,
   and strategy version.
2. Compute: win rate, R distribution, results by session hour, results by
   spread bucket, results by skill (normal vs news window).
3. Look for repeated failure patterns (e.g., losses cluster right after news,
   HTF veto misses, spread eating small TPs).
4. Write the review as markdown: findings first, evidence after, and a short
   list of hypotheses worth testing — clearly labeled as hypotheses.

## Must never
- Change any code or config. This skill is read-only analysis; refinements go
  through `/refine-bot`.
