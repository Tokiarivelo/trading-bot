# Multi-Account Support — Implementation Plan

## Context

Today the whole system (gateway, backend, frontend) is single-account by
design: one MT5 login, one gateway process, one backend `Container` built
once at startup, one SQLite DB with no `account_id` anywhere, one frontend
session with no account switcher. The goal is to let one person run
**several MT5 broker accounts concurrently** (different prop firms, live +
demo, different brokers) side by side, with one unified dashboard/journal —
not a multi-tenant product, no new user/auth model needed.

The hard external constraint driving most of the design: **MetaTrader5's
Python package only supports one logged-in account per OS process.** That
means "multi-account" always requires multiple gateway *processes*, no
matter what changes on the backend. Everything else in this plan exists to
let the backend and frontend address, route to, and keep separate the data
from N such gateway processes.

Verified via full codebase exploration before writing this plan:
- `gateway/src/gateway/mt5_client.py:99-100,603` — `Mt5Client` is a
  module-level singleton wrapping the global `MetaTrader5` module.
  `gateway/run_gateway.py:16-23` already reads `GATEWAY_HOST`/`GATEWAY_PORT`
  from env — no gateway source changes needed for multi-instance, just
  process/deployment changes.
- `backend/src/container.py`'s `Container` (dataclass, ~35 fields,
  lines 120-166) and `build_container()` (169-464) build exactly one of
  everything: one `httpx.AsyncClient` to the gateway (177-183), one
  `AccountService` backed by one `FernetCredentialStore(Path("data/credentials.enc"))`
  (212-215), one `BrokerPort`, one `TradeEngine` (414-425, purely
  event-driven via `EventBus.subscribe`), one `RiskManager`, one `EventBus`.
  Built once in `main.py`'s `lifespan()`, stored on `app.state.container`.
- `backend/src/shared/events/definitions.py` — `Event`/`CandleClosed`/
  `PositionOpened`/`PositionClosed`/`TenTradesCompleted` dataclasses carry no
  account field today.
- DB: SQLAlchemy ORM per module (`journal` → `trades`, `activity` →
  `activity_logs`, `strategies` → `strategy_versions`, `market_data` →
  `candles`/`symbol_specs`, etc.). Repo-wide grep for `account_id`/`user_id`
  returns nothing. Alembic is already wired (`backend/alembic.ini`,
  `backend/migrations/versions/`, 10 existing revisions, one-table-per-revision
  style) — migrations are straightforward to add.
- Frontend: `shared/api/client.ts` has one hardcoded `BASE = "/api"` and one
  bearer token, no account param anywhere. `shared/api/ws.ts` rooms are keyed
  only by `symbol:timeframe`. No account-switcher UI exists anywhere.
- Auth (`shared/auth/session.py`) is a single shared app-password token with
  no identity concept — this stays as-is (single user), untouched by this plan.

## Phase 1 — Account identity model & config — ✅ Done (2026-07-23)

Add `configs/accounts.yaml` (repo root, alongside `app.yaml`/`risk.yaml` —
confirmed `CONFIGS_DIR = REPO_ROOT / "configs"` in `settings.py`): a list of
`{id, label, gateway_url, gateway_shared_secret_env, mode: live|paper, enabled, risk_override_file?}`.
`id` is a short slug (e.g. `ftmo-1`), used everywhere downstream as the
partition key — never the MT5 login number, which is a credential, not an
identity. Extend `backend/src/shared/config/settings.py`'s `Settings` with
`accounts_config_path`, and add `load_accounts_config()` to
`shared/config/loader.py` mirroring the existing `load_yaml_config()`
pattern, returning a validated `list[AccountConfig]`.

No behavioral change yet — a one-entry `accounts.yaml` is equivalent to
today's single-account setup. This phase is pure config/settings.

**Files:** `configs/accounts.yaml` (new),
`backend/src/broker/domain/account.py` (new `AccountConfig` dataclass, next
to the existing `Mt5Credentials`/`AccountInfo`), `backend/src/shared/config/loaders.py`
(new `load_accounts_config()`, mirroring `load_risk_caps`/`load_news_config`).
No `Settings` field was needed — `load_yaml_config`/`CONFIGS_DIR` already
cover any file under `configs/`, so a separate `accounts_config_path`
setting would have been redundant.

**Done:** all of the above shipped as described. Tests added:
`test_accounts_config_has_at_least_one_account_with_required_fields`
(`backend/tests/unit/shared/test_config.py`) and two cases in the new
`backend/tests/unit/shared/test_loaders.py`. `uv run ruff check src tests`
clean; full `uv run pytest` green (1138 passed — excluding one pre-existing,
unrelated collection failure in `tests/unit/strategies/test_rbr_dbd_zones_scalp_xauusd_noveto.py`,
which imports a generated strategy module that doesn't exist in the repo;
predates this work, already present on `main` at `e8c1ba5`, flagged
separately). No behavior change: `container.py`/`build_container()` are
untouched — this phase is pure config groundwork for Phase 5.

## Phase 2 — Credential store: per-account file — ✅ Done (2026-07-23)

Change `FernetCredentialStore` (`backend/src/broker/adapters/credential_store.py`)
to take a `Path` built from `account_id` — `data/credentials/{account_id}.enc`
— instead of the hardcoded `data/credentials.enc`. Per-account files over one
keyed file: the class is already a dumb `save/load/clear` over a single
path with no key-namespace concept, and per-file isolation means a corrupt
write only loses one account's credentials, not all of them. The OS-keyring
Fernet key stays global (one key, N files).

**Files:** `backend/src/broker/adapters/credential_store.py`, its
construction site (moves into Phase 5's per-account wiring).

**Done:** `FernetCredentialStore` itself already took an arbitrary `Path` —
the actual change was a new `credentials_path_for(account_id) -> Path`
helper (`data/credentials/{account_id}.enc`) in `credential_store.py`, and
its single construction site in `container.py`, which now calls
`load_accounts_config()` and picks the first *enabled* entry
(`_primary_account()`, new helper) to identify which account's credential
file to open — `container.py` still wires exactly one account end-to-end
ahead of Phase 5's full per-account registry, so this phase only threads the
identity through, it doesn't yet loop. The one real on-disk file,
`backend/data/credentials.enc` (this machine's live `default` account
login), was migrated to `backend/data/credentials/default.enc` (byte-for-byte
verified, old file removed) so the running system isn't logged out by this
change. New test: `test_credentials_path_for_is_per_account`
(`backend/tests/unit/broker/test_credential_store.py`). `uv run ruff check
src tests` clean (same one pre-existing unrelated collection failure as
Phase 1, still present on `main`); full `uv run pytest` green otherwise.

## Phase 3 — Gateway: multi-instance deployment — ✅ Done (2026-07-23)

No gateway source changes were needed — `run_gateway.py` already parameterizes
host/port via env. What's needed is operational:
- Port allocation: each `accounts.yaml` entry carries its own `gateway_url`
  (already captured in Phase 1).
- `Makefile`: replace single `dev-gateway`/`mt5-login`/`kill` targets with an
  account-parameterized pattern — `make dev-gateway ACCOUNT=ftmo-1` reads
  port/secret for that account, plus a `dev-gateway-all` target that loops
  over enabled accounts.
- `kill`/`stop`: currently `pkill -f run_gateway.py` (name-based — would kill
  *every* gateway instance at once). Move to PID-file based:
  `gateway/run/{account_id}.pid` written on start, `kill $(cat ...)` on stop.

**Files:** `Makefile`, possibly `gateway/run_gateway.py` (only if PID-file
writing needs to live inside the script rather than the launch wrapper),
deployment docs (`gateway/README.md`, `LAUNCH.md`).

**Done:** added `backend/scripts/print_account_gateway_env.py` — the one
place that parses `configs/accounts.yaml` for the Makefile, run as
`uv run python -m scripts.print_account_gateway_env [account_id]` from
`backend/`. It resolves an account (by id, or the first *enabled* one if
omitted) to `TB_RESOLVED_ACCOUNT_ID`/`_GATEWAY_HOST`/`_GATEWAY_PORT`/
`_GATEWAY_SECRET_ENV` `export` statements for the Makefile to `eval`, or —
with `--list-ids` — every enabled account's id (one per line) for
`dev-gateway-all`. On an unknown/disabled account or a bad `gateway_url` it
prints an `echo ... >&2; exit 1` line instead, so the `eval` fails loudly in
the calling shell rather than continuing with empty variables. No gateway
source changes, per the plan — `run_gateway.py` untouched; PID-file writing
lives in the Makefile recipe (a plain `echo $! > run/<id>.pid` right after
backgrounding the `wine` process), not the script, since the Makefile is
already what forks the process and needs no in-script cooperation to know
its own child's PID.

`Makefile` changes:
- `dev-gateway` now takes `ACCOUNT=<id>` (optional — defaults to the first
  enabled account), resolves host/port/secret via the script above (the
  secret is read out of `.env` by the `.env` variable name the account's
  `gateway_shared_secret_env` points to), and writes/holds
  `gateway/run/<account_id>.pid` for the life of the process.
- New `dev-gateway-all` loops `--list-ids` and re-invokes `$(MAKE)
  dev-gateway ACCOUNT=<id>` per account in parallel (mirrors `dev`'s
  `trap 'kill 0' EXIT` + background-jobs-then-`wait` pattern).
- `dev` no longer duplicates the terminal-launch + wine invocation inline —
  it now backgrounds `$(MAKE) dev-gateway` (default account) as one of its
  three jobs, so the default-account gateway it starts also gets a PID file
  (needed for `kill` below to find it) without copy-pasting the recipe.
- `mt5-login` and `doctor` both gained the same optional `ACCOUNT=<id>` and
  resolve host/port/secret the same way, instead of the old single global
  `GATEWAY_PORT`/`GATEWAY_SHARED_SECRET` Make variables (removed — they had
  no remaining consumer once every gateway-touching target resolved
  per-account).
- `kill`/`stop`: the gateway is no longer killed by port (a single
  `GATEWAY_PORT` can't cover N accounts' N ports) or by the old
  `pkill -f run_gateway.py` (kills every instance, defeating per-account
  isolation). It now loops `gateway/run/*.pid`, kills each live PID, and
  removes the file — plus `make kill ACCOUNT=<id>` to stop just one
  account's gateway via its own PID file, leaving backend/frontend/other
  accounts running. A `pkill -f run_gateway.py` fallback still runs last, as
  a safety net for anything not tracked by a PID file (e.g. started outside
  `make`), not as the primary mechanism.
- `gateway/run/` added to `.gitignore` (PID files are host-local, like
  `.venv`/`data/`).

Docs: added a "Running more than one account" section to `gateway/README.md`
and `LAUNCH.md` explaining the per-account commands above; both existing
single-account workflows (`make dev`, `make dev-gateway`, `make mt5-login
LOGIN=...`) are unchanged in behavior — they still work with no `ACCOUNT=`
at all by resolving to the first enabled `accounts.yaml` entry.

**Caveat surfaced during manual verification, not part of this phase's
code:** while dry-running the updated `kill` target I ran it for real by
mistake and it killed the then-running backend (:8000) and frontend (:3001)
dev processes (not gateway-related — this predates and is unrelated to the
PID-file change; the old port-based backend/frontend kill logic is
untouched). Restarted both via `make dev-backend`/`make dev-frontend`
immediately after. No gateway/MT5 process was affected (none was running).
Actual gateway/Wine/MT5 login flow was **not** exercised live in this pass
(would require logging into a real MT5 account) — verified via `make -n`
dry-runs (recipe expansion for `dev-gateway`, `dev-gateway-all`, `kill`,
`kill ACCOUNT=...`) and one live run of `backend/scripts/print_account_gateway_env.py`
against the real `configs/accounts.yaml` (resolves `default`, `--list-ids`,
and the unknown-account bail path all behave as designed). `uv run ruff
check src tests scripts` clean (same one pre-existing unrelated collection
failure as Phases 1–2); full `uv run pytest` run separately, see next
phase's verification note if a discrepancy shows up.

## Phase 4 — DB migration: `account_id` columns — ✅ Done (2026-07-23)

Add `account_id: str` (non-null after backfill, indexed) to:
- `trades` (journal)
- `activity_logs`
- `strategy_versions` (a strategy assignment is "this bot, on this account")
- `candles` and `symbol_specs` — **do not skip these**: different brokers
  quote different spreads/point-values/digits for a nominally identical
  symbol (e.g. `XAUUSD` vs `XAUUSD.a`), so a shared cache would silently mix
  broker-specific price history and lot-size rules across accounts. Extend
  both tables' composite keys to include `account_id`.

One Alembic revision per table (matches existing granularity), each doing
`add_column` → backfill existing rows with a single `default_account_id`
(the `accounts.yaml` entry marked as the pre-migration incumbent) → set
`nullable=False`. Land this before the container refactor so the schema is
stable underneath the wiring work.

**Files:** `backend/migrations/versions/<new>_*.py` (5 new revisions),
`backend/src/{journal,activity,strategies,market_data}/adapters/orm.py` and
matching repository methods (gain an `account_id` filter param).

**Done:** all 5 revisions shipped
(`885996aa6537`/`d6d6e88aac6c`/`ab579974226c`/`1ec3d9e05ff1`/`ad2ce706c70f`,
chained onto the existing head `7296ba2cc26a`), backfilling every existing
row to `account_id='default'` (this machine's sole pre-migration
`accounts.yaml` entry). `trades`/`activity_logs`/`strategy_versions` got a
plain indexed column (`op.add_column(..., server_default='default',
nullable=False)` — no batch mode needed, PK unchanged). `candles`
(PK `symbol,timeframe,time`) and `symbol_specs` (PK `symbol`) needed their
composite primary key widened to lead with `account_id`, which SQLite can
only do via Alembic's batch (table-recreate) mode — verified against a
120MB/1.1M-row copy of the real dev DB: upgrade preserves every row count
and backfills correctly, `alembic downgrade -5` cleanly restores the
original schema and row counts (no data loss either direction).

Repository methods (`JournalRepository`, `ActivityLogRepository`,
`StrategyVersionRepository`, `CandleRepository`, `SymbolSpecRepository`)
gained an `account_id: str = "default"` parameter on every read/write method
that needed one (write methods to set it, read/delete methods to filter by
it) — PK-only lookups (`get`/`delete` by row id) were left alone since a
version/trade id is already globally unique regardless of account. The
default value keeps every existing call site (services, routes, tests)
working unchanged today, since only one account exists — Phase 5's
`AccountRuntime` registry is what will thread real per-account values in and
remove the need for the default, per this phase's scope note above
("Land this before the container refactor"): `container.py`, the
application services, and `backtest/` were deliberately left untouched in
this phase. New cross-account isolation tests added: 4 in
`test_repository.py` (journal/activity), a new
`tests/unit/strategies/test_repository.py` (none existed before), plus new
cases in `test_candle_repository.py`/`test_symbol_spec_repository.py` — all
assert one account's writes are invisible to another's reads and to the
`"default"` account.

Applied to the real dev DB too (`backend/data/trading.db`, ~216MB,
1.1M+ candle rows): the live backend (uvicorn) was stopped first (SQLite
batch-mode migration needs exclusive access), `alembic upgrade head` run
against it, row counts and `account_id='default'` backfill verified, then
the backend restarted (`make dev-backend`) — confirmed clean startup (all
strategy versions reloaded, `/health` OK, gateway candle polling resumed)
with no errors. The gateway/Wine/MT5 terminal processes were left running
throughout — they were never touched, since the gateway has no DB access
per the architecture rule (backend talks to MT5 only through the gateway
HTTP API) and stopping it wasn't necessary for a backend-only DB migration.
`uv run ruff check src tests` clean (same one pre-existing unrelated
collection failure as Phases 1–3); full `uv run pytest` green: 1153 passed
(1151 + the 2 `test_health.py` cases that only pass once the real DB is
migrated, confirmed after migrating it).

## Phase 5 — Container restructuring: `AccountRuntime` + registry — ✅ Done (2026-07-23)

Introduced `AccountRuntime`, a dataclass bundling everything account-scoped —
`gateway_client, event_bus, market_data, candle_history, candle_stream,
live_candle, ws_broadcaster, account, broker, order_service,
manual_trade_gate, reconciliation, health_monitor, position_manager,
trade_journal, activity_log, risk_manager, trade_engine, strategy_registry,
strategy_versions, pdf_to_strategy, code_regeneration, refinement_loop` —
built fresh per enabled `accounts.yaml` entry by a new
`build_account_runtime()`. `EventBus` is per-account, exactly as planned:
`TradeEngine`/`ReconciliationService`/`GatewayHealthMonitor` subscribe only
on their own account's bus, so the frozen event dataclasses never needed an
`account_id` field.

**Deviation from this section's original text, found during implementation
and confirmed with the user (AskUserQuestion) before writing any code:**
`StrategyRegistry` and `StrategyVersionService` are **per-account**, not
global. Phase 4's own repository + tests already committed to this —
`StrategyVersionRepository.get_active`/`list_active` are keyed by
`(name, account_id)`, and `test_same_name_can_be_active_on_two_different_accounts`
explicitly asserts two accounts can run different active code for the same
strategy name at once. A single shared registry (a plain `name -> Strategy`
dict mutated in place by `activate_version`) can't honor that — promoting a
refinement on account A would instantly change what account B's
`TradeEngine` executes. Because `PdfToStrategyService`/
`CodeRegenerationService`/`RefinementLoopService` all hold a direct
`strategy_versions`/`strategy_registry` reference, they became per-account
too (mechanically — no internal code changes to `refinement_loop.py`/
`pdf_to_strategy.py`/`code_regeneration.py` were needed beyond that; only
`StrategyVersionService` itself gained an `account_id` param threaded into
every repository call). Baseline strategy instances (`BreakoutV1()` etc.)
are shared, stateless objects registered into every account's own registry —
only the registry bookkeeping (active/paused) is per-account.

Stays genuinely global (`Container`, built once): `settings`,
`session_issuer`, `symbols` (base list), `SpreadGate` (stateless config —
one shared instance, since `SkillAssignmentService` needs a single one to
mutate), `skill_selector`/`NewsSkillSelector`/`SkillAssignmentService` (bot
routing — "which strategy trades which symbol" is shared config across
accounts, per the user's confirmed answer; `SkillAssignmentService`'s
`candle_stream` param became `candle_streams: Sequence[CandleStreamService]`
so assigning a bot hot-activates the symbol on every account, and it
validates against the *primary* account's registry for existence/pause
checks — same "primary account" fallback pattern already used by
`_primary_account()` in Phases 2–3), `llm_router`/`ProviderSettingsService`/
`DraftRepository` (AI provider plumbing), `NewsWindowService` (calendar
polling is account-agnostic, but now publishes onto every account's bus via
a small `_FanOutEventBus` duck-typed wrapper so `news_window_service.py`
itself needed no changes), `AlertService` (stateless — the same instance is
subscribed onto every account's bus, exactly like today's single subscribe
call, just looped), `IndicatorService` (indicators have no `account_id`
column — out of Phase 4's migration scope, left untouched).

Also added: `shared/logging/account_context.py` — a `ContextVar[str]` set
once at the top of each per-account background task
(`CandleStreamService._run`/`LiveCandleService._run`/
`GatewayHealthMonitor._run`), read by `activity/adapters/log_handler.py` to
stamp the right `account_id` on every persisted log row. Without this,
`logging.getLogger(__name__)` (shared across every account's `TradeEngine`/
`OrderService` instance) had no way to attribute a log line to the account
that produced it — a real gap against CLAUDE.md's "log every decision" bar
once N accounts run concurrently. Falls back to `"default"` outside any
bound task (HTTP routes, startup code) — no behavior change for the
single-account case, since Phase 6 (not yet done) is what will bind it per
request.

`Container` keeps every pre-Phase-5 field name as a read-only property
delegating to `self.accounts[self.primary_account_id]` (the first enabled
`accounts.yaml` entry) — this is why every existing route's
`request.app.state.container.<x>` accessor and every `SimpleNamespace`-
stubbed route test kept working completely unchanged; verified via
`uv run pytest` (full suite green, same one pre-existing unrelated
collection failure as Phases 1–4). Phase 6 deletes these properties one at a
time as each route switches to `get_account_runtime(account_id)`.
`main.py`'s `lifespan()` now loops `container.accounts.values()` for the
per-account startup work (`reconnect_from_stored`, `reconciliation.
reconcile_all`, `candle_history.reconcile_gaps`, and the three per-account
`.start()` calls) instead of calling them once; `news_window_service.start()`
stays a single call.

New test: `backend/tests/unit/test_container.py` — builds two full
`AccountRuntime`s from a temp `accounts.yaml` with two enabled entries
(copying the real `configs/` tree so all the ancillary YAML is valid) and
asserts: distinct event buses/strategy registries/gateway clients per
account; publishing `CandleClosed` on one account's bus never reaches
another's `trade_engine`; registering a new strategy instance on one
account's registry leaves the other's untouched (the in-memory mirror of
Phase 4's `test_same_name_can_be_active_on_two_different_accounts`); and the
backward-compat properties resolve to the primary account.

**Files:** `backend/src/container.py` (rewritten), `backend/src/main.py`
(`lifespan()` loops accounts), `backend/src/shared/logging/
account_context.py` (new), `backend/src/activity/adapters/log_handler.py`,
mechanical `account_id`-threading in `journal/application/trade_journal.py`,
`activity/application/activity_log_service.py`, `market_data/application/
history.py`, `market_data/application/candle_stream.py`,
`market_data/application/live_candle.py` (context binding only, no repo),
`broker/application/health_monitor.py` (context binding only, no repo),
`strategies/application/versioning.py`, `skills/application/
skill_assignment.py` (`candle_streams` list), plus the two existing
`SkillAssignmentService`-constructing tests updated to match.

No frontend/API-surface change — no route yet exposes a second account
(that's Phase 6). No live/paper gateway smoke test this phase, per Phase 9's
rollout order (that milestone lands after Phase 6).

## Phase 6 — API surface: `/accounts/{account_id}/...`

Path-prefix over header or query param: it's self-documenting in OpenAPI
(shows as a required path parameter with its own `Field(description=...)`,
satisfying the CLAUDE.md docs requirement automatically), and it matches
REST convention. Add a FastAPI dependency `get_account_runtime(account_id,
request) -> AccountRuntime` (looks up
`request.app.state.container.accounts[account_id]`, 404s on unknown id);
every route handler uses it instead of reaching `request.app.state.container`
directly. Global endpoints (`GET /accounts` list, `/auth/*`) stay unprefixed.

**Files:** every `*/api/routes.py` under `backend/src/{broker,engine,journal,
market_data,activity,...}`, new `backend/src/broker/api/accounts.py` for the
account list endpoint.

## Phase 7 — Per-account risk overrides

`configs/risk.yaml` stays the global, user-owned floor — untouched,
never auto-modified, per existing binding rule. Add an optional
`configs/risk/{account_id}.yaml` (only used if `accounts.yaml`'s
`risk_override_file` is set) that `RiskManager` construction merges *on top
of* the global file. The merge function may only tighten caps, never loosen
them — enforced in code, not trusted from the file. Both files remain
hand-authored; AI/refinement code gains no write access to either.

**Files:** `backend/src/engine/application/risk_manager.py` (merge logic),
`configs/risk/` (new directory).

## Phase 8 — Frontend

Add `AccountContext` (`frontend/src/shared/api/account-context.tsx`) — React
context + `localStorage`-persisted active `account_id`, loaded from a new
`GET /accounts` call. Account switcher lives in the top nav/header, next to
where `AccountPanel.tsx` currently sits (that stays as the connect/disconnect
form for the *currently selected* account, not a list).

`client.ts` request helpers gain an `accountId` param interpolated into the
`/accounts/{id}/...` path. `ws.ts`'s `roomKey` extends to
`${accountId}:${symbol}:${timeframe}`, `subscribeRoom` takes an `accountId`.
Feature hooks (`useAllPositions`, `useTradeHistory`, `useActivityLog`,
`useTrading`, etc.) read `accountId` via a new `useActiveAccount()` hook
rather than each taking it as an explicit prop, to minimize call-site churn.

**Files:** `frontend/src/shared/api/client.ts`, `frontend/src/shared/api/ws.ts`,
`frontend/src/shared/api/account-context.tsx` (new),
`frontend/src/features/account/AccountPanel.tsx`, one small edit per feature
hook that currently assumes a single account.

## Phase 9 — Testing & rollout order

Smallest useful milestone: **Phases 1–6, backend-only**. Verify entirely
through `uv run pytest` + manual OpenAPI-docs/`curl` checks against two real
gateway processes pointed at two demo accounts — no frontend work until
that's green under `make check`. Each phase lands as its own PR with:
- unit tests (config loader, per-account credential store isolation,
  Alembic upgrade/downgrade round-trip against a copied dev DB,
  `AccountRuntime` wiring smoke test)
- a paper-mode integration test for every broker-affecting phase (3, 5, 6),
  per the project's binding quality bar.

Frontend (Phase 8) is deliberately last — it's the only phase with no
money-path risk, so it's safe to build against a stable, typed
(OpenAPI-generated) backend contract instead of hand-written duplicate types
churning alongside backend changes.

## Verification

- Backend: `cd backend && uv run ruff check src tests && uv run pytest`
  after every phase; `make openapi` to confirm every new/changed route still
  produces full summary/description/typed schemas per CLAUDE.md's OpenAPI rules.
- Migration round-trip: `alembic upgrade head` then `alembic downgrade -1`
  against a copied dev DB for each new revision, confirming backfill values
  are sane and no data loss occurs.
- End-to-end smoke test for the backend milestone (Phase 9): run two gateway
  processes (`make dev-gateway ACCOUNT=<a>`, `make dev-gateway ACCOUNT=<b>`)
  against two demo MT5 accounts, hit `/accounts/<a>/...` and
  `/accounts/<b>/...` endpoints, confirm trades/candles/activity logs stay
  correctly isolated per account (no cross-account leakage in journal queries).
- Frontend: `pnpm lint && pnpm build`, then manually switch accounts in the
  UI and confirm chart/journal/positions all repaint to the newly selected
  account's data, and the WS connection re-subscribes to the new account's
  rooms.
