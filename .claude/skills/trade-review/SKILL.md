---
name: trade-review
description: Pull the last N trades from the journal, correlate them with market snapshots, and write a human-readable review of what worked and what failed.
---

# Trade Review

Review the last N trades (`$ARGUMENTS`, default 10) from the journal. Purely
read-only analysis — no code or config changes, and nothing here is saved to
the DB. There is already a fully automated version of this same idea
(`RefinementLoopService` fires an LLM review + `AnalysisReport` every
`review_every_n_trades` closed trades, see `.claude/skills/refine-bot`) — this
skill is the on-demand, human-facing equivalent: the analyst-style deep dive
a trader asks for by name, not a duplicate of that pipeline's output.

## Getting the trades — the REST API is not enough

`GET /journal/trades?symbol=&limit=` (last N for one symbol) and
`GET /journal/history?...` (filtered, paginated, any symbol) both return
`TradeRecordOut`, which **deliberately excludes the four candle snapshots** —
they're documented as AI-review-only and never serialized over HTTP. To get
real market context around each trade you need the domain object directly,
via `JournalRepository` (`backend/src/journal/adapters/repository.py`):

```bash
cd backend && uv run python -c "
from src.shared.config.settings import Settings
from src.shared.db.base import make_session_factory
from src.journal.adapters.repository import JournalRepository
import json

repo = JournalRepository(make_session_factory(Settings().database_url))
trades = repo.get_last_n_closed('<symbol>', <N>)   # one symbol, most-recently-closed first
# Cross-symbol / filtered instead: repo.search(symbol=None, outcome='loss', limit=<N>, order_by='close_time', order_dir='desc')
for t in trades:
    print(t.id, t.symbol, t.side, t.open_time, t.close_time, t.profit, t.strategy_version, t.skill, t.spread_points_at_entry)
"
```

`TradeRecord` fields worth pulling: `symbol, side, volume, open_price,
close_price, open_time, close_time, sl, tp, profit, spread_points_at_entry,
strategy_version, skill, m5_entry_snapshot, h1_entry_snapshot,
m5_exit_snapshot, h1_exit_snapshot`.

**Snapshot caveat** — `m5_entry_snapshot`/`h1_entry_snapshot` are the most
recent 50 M5 / 20 H1 candles *as of fill time*, not a true window centered on
entry (`MarketContextPort.capture`'s docstring: "approximated as the most
recent bars, since trades are journaled at fill time"). There is no
look-ahead beyond the fill — don't describe or reason about them as if they
show what happened just after entry; only the separate exit snapshots do
that, as of close time.

## Steps
1. Pull the trades as above — one symbol via `get_last_n_closed`, or across
   symbols/filtered (e.g. only losses, only one strategy version) via
   `search(...)`.
2. Compute, from scratch — there is no existing helper over `TradeRecord`
   (`backend/src/backtest/application/metrics.py`'s `win_rate`/`profit_factor`/
   `avg_r`/etc. operate on backtest's own `BacktestTrade`, not the journal's
   `TradeRecord`; nothing bridges the two):
   - Win rate: `profit > 0` fraction.
   - R-multiple per trade (if `sl` is set): `profit / (abs(open_price - sl) *
     volume * contract_size)`, where `contract_size` comes from
     `configs/symbols/<symbol>.yaml` or the `symbol_specs` DB table (same
     source `_resolve_symbol_spec` in the backtest runner uses) — note this
     explicitly as an approximation if you can't pin down the exact
     contract_size used at fill time.
   - Results bucketed by session hour (`open_time.hour`, UTC — convert to
     the project's configured `timezone` from `configs/app.yaml` if the user
     wants local-session buckets), by `spread_points_at_entry` (e.g. quartile
     or fixed bands), and by `skill` (normal vs a `news/*` skill window — see
     `.claude/skills/news-skill-gen` for what those look like).
3. Look for repeated failure patterns — losses clustering right after a
   particular `skill`, one `strategy_version` underperforming another,
   spread eating small TPs, a session-hour cluster. Cross-check anything
   news-shaped against `GET /news/upcoming` or `GET /news/active-windows`
   rather than assuming.
4. Write the review as markdown: findings first, evidence after (tables/
   numbers), and a short list of hypotheses worth testing — clearly labeled
   as hypotheses, not conclusions. If a hypothesis suggests a concrete code
   or param change, name it but don't act on it — that's `/refine-bot`'s job,
   and only via the automated report pipeline or a human decision, never
   this skill improvising a fix.

## Must never
- Change any code or config, or call any AI regeneration/refinement/activation
  endpoint. This skill is read-only analysis; refinements go through
  `/refine-bot` off the automated pipeline's own `AnalysisReport`s, never a
  change this skill proposes directly.
- Present an approximated R-multiple or bucket as if it were an exact,
  broker-verified number.
