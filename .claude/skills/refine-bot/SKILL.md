---
name: refine-bot
description: Fetch an AI refinement proposal (from the automated 10-trade review loop), present its diff and before/after backtest comparison, and — only on explicit request — apply or reject it.
---

# Refine Bot

This is a read-mostly skill over a pipeline that has *already run*. By the
time an `AnalysisReport` has a `proposal_id`, the candidate code has already
been generated, sandbox-validated, saved as a new `StrategyVersion`, and
backtested against the current baseline — automatically. This skill's job is
to fetch that result, verify it's actually ready, present it clearly, and —
only if the user explicitly says so in this turn — apply or reject it. It
does not generate code, run a sandbox check, or run a backtest itself; those
already happened.

## How the pipeline actually works (context, not steps to run)
- Every `review_every_n_trades` closed trades per symbol
  (`configs/ai.yaml: review_every_n_trades`, default 10) fires
  `TenTradesCompleted` on the event bus.
- `RefinementLoopService.on_ten_trades_completed`
  (`backend/src/ai/application/refinement_loop.py`) handles it: pulls the
  closed trades (with M5/H1 candle snapshots) from the journal, prompts the
  `review_ten_trades` LLM task for win rate / avg R / failure pattern /
  session correlation / verdict, and saves an `AnalysisReport`.
- If the verdict is `refinement_proposed`, the same handler generates
  candidate code (`refine_strategy_code` prompt, retried against sandbox
  errors), saves it via `StrategyVersionService.save_generated_code(source=
  CodeSource.AI_REFINED)` — status `VALIDATED`, file
  `<name>_v{N+1}.py`, never edits the base version — then runs
  `run_backtest` twice (current active version, then the candidate) over the
  same default comparison period and records `improvement_pct`. All of this
  is done by the time the report shows up via the API.
- **`configs/ai.yaml: refinement.mode`** matters: in `suggest` mode (the
  default — "keep 'suggest' until you trust the loop") a proposal always
  waits for a human. In `auto` mode, the same handler can activate a
  `backtested` proposal itself — `status` becomes `applied`,
  `applied_mode: "auto"` — once per day
  (`max_auto_refinements_per_day`) and only if `improvement_pct >=
  auto_apply_min_improvement_pct` (default 10%). Check `mode` before
  assuming a proposal is waiting on you.
- There is no CLI and no endpoint to trigger a review/refinement pass on
  demand — this only fires off real trade closes. A different, unrelated
  feature, `POST /ai/strategies/versions/{id}/regenerate`, lets a human
  manually rewrite a version's code from free-form instructions; that's not
  this pipeline and not what this skill drives — point the user there
  explicitly if that's actually what they want instead.

## Steps
Given `$ARGUMENTS` (a report id, or a strategy/symbol name to find the latest
report for):

1. Fetch the report: `GET /ai/refinement/reports/{report_id}`, or
   `GET /ai/refinement/reports?symbol=<symbol>` (newest first) to find one.
   If `verdict` is `no_action`, stop and say so — there is nothing to apply.
2. Fetch the proposal via the report's `proposal_id`:
   `GET /ai/refinement/proposals/{proposal_id}` — returns `rationale`,
   `proposed_code`, a diff against the base version (computed fresh on every
   read, never stored), `new_version_id`, and `status`. Branch on `status`:
   - `pending` — the backtest comparison hasn't finished yet; nothing to
     present, say so and stop rather than fabricating numbers.
   - `rejected` — check `sandbox_errors`; the candidate never became a live
     option. Nothing to do.
   - `applied` — already resolved (check `applied_mode`: `"auto"` means the
     loop activated it itself under `configs/ai.yaml: refinement.mode: auto`).
     Report what happened; don't re-apply.
   - `backtested` — the normal case: proceed to step 3. Note this only
     reflects proposals applied *through this same auto path* — a human who
     activated `new_version_id` directly via
     `POST /strategies/versions/{id}/activate` does not flip this status (no
     event links the two), so if you suspect that already happened, check
     `GET /strategies/versions/{new_version_id}` directly rather than
     trusting `backtested` here at face value.
3. Present to the user: the rationale, the diff (not the full raw file unless
   asked), and the baseline-vs-candidate backtest comparison (win rate,
   profit factor, max drawdown, avg R) plus `improvement_pct`. Check trade
   counts on both sides — a positive `improvement_pct` over a handful of
   trades is weaker evidence than the headline number suggests. Read the
   risk-shaping lines in `proposed_code` yourself (SL/TP distance
   calculation, any lot-size logic) — there is no code-level guard against a
   widened stop or bigger size, only the prompt's instructions not to do
   that, so don't take "backtested, positive improvement" as proof it's safe.
4. Only on the user's explicit instruction in this turn:
   - Apply: `POST /strategies/versions/{new_version_id}/activate`.
   - Reject: `POST /ai/refinement/proposals/{proposal_id}/reject` (only
     valid while `status` is `pending`/`backtested`; the `StrategyVersion`
     stays on disk as `validated`, just never activated).

## Must never
- Call `POST /strategies/versions/{id}/activate` or
  `POST /ai/refinement/proposals/{id}/reject` without the user explicitly
  asking for that exact action in this turn.
- Edit `configs/risk.yaml`, `backend/src/engine/`, or circuit-breaker logic.
- Treat a positive `improvement_pct` as sufficient on its own — always
  surface the risk-parameter check from step 3.
- Try to manually trigger a review/refinement pass, or improvise one — if no
  report exists yet, say so.
- Touch `base_version_id`'s file, or any version other than the one this
  proposal already created — rollback and iteration both go through new
  versions, never edits in place.
