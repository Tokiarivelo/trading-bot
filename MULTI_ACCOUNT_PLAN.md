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

## Phase 6 — API surface: `/accounts/{account_id}/...` — ✅ Done (2026-07-23)

Path-prefix over header or query param: it's self-documenting in OpenAPI
(shows as a required path parameter with its own `Field(description=...)`,
satisfying the CLAUDE.md docs requirement automatically), and it matches
REST convention. Added `get_account_runtime(account_id, request) ->
AccountRuntime` (`backend/src/shared/api/dependencies.py`, new package) —
looks up `request.app.state.container.accounts[account_id]`, 404s on an
unknown id, and gives `account_id` itself a `Path(description=...)` so the
one shared dependency documents every route's path param at once. This is
the first real `Depends()`-injected dependency in the codebase — every
existing route instead read `request.app.state.container.<field>` through a
private per-module `_service(request)` helper (confirmed via `grep -rn
"Depends(" backend/src/*/api/` returning only `main.py`'s router-level
`Depends(require_session)`); those helpers now take the injected
`AccountRuntimeDep` instead of `Request` and return `account.<field>`
directly, keeping every module's existing naming/shape.

**Which routes moved, which stayed global:** every route backed by an
`AccountRuntime` field (Phase 5) moved under `/accounts/{account_id}/...`:
`journal`, `activity`, `account` (MT5 connect/status), `engine`,
`market-data`, `strategies` (version CRUD/activate/pause/etc — not
`evaluate-custom`), and the three `ai` modules (`pdf-strategy`,
`refinement`, code `regeneration`). Two modules mixed account-scoped and
genuinely process-wide endpoints in one file and needed splitting into two
routers, mounted separately in `main.py`:
- `broker/api/trading_routes.py`: `router` (orders/positions — per account)
  vs. new `spread_router` (`/broker/symbols/{symbol}/spread-config`,
  `/broker/symbols/{symbol}/min-rr` — stays global, since `SpreadGate` is a
  genuine process-wide `Container` field per Phase 5, not per-account).
- `strategies/api/routes.py`: `router` (version endpoints — per account) vs.
  new `sandbox_router` (`/strategies/evaluate-custom` — stays global; this
  handler already built its own ad-hoc `CandleRepository`/`StrategyRegistry`
  from `container.settings.database_url` rather than any account's real
  registry, so per-account scoping would have been cosmetic at best).

Stayed unprefixed, per Phase 5's own global-vs-per-account boundaries
(unchanged by this phase): `auth`, `ai-settings` (`provider_settings` is
process-wide AI provider selection), `skills` (`skill_assignment` is
process-wide bot routing, primary-account-biased per Phase 5's confirmed
answer), `news` (`news_window_service` fans out to every account's bus via
`_FanOutEventBus`), `indicators` (`IndicatorService` isn't in `AccountRuntime`
at all — Phase 4 explicitly left indicator definitions out of the
`account_id` migration since they carry no such column; left untouched here
too rather than silently defaulting every compute/preview call to the
`"default"` account's candles), and `backtest` (candle history/backtesting
already thread an explicit `account_id` through `CandleRepository`
independent of any live account — only `POST /backtest/run`'s auto-backfill
path touches `container.candle_history` today, and that stays as-is).

New: `GET /accounts` (`backend/src/broker/api/accounts.py`, new
`AccountSummaryOut` schema in `broker/api/schemas.py`) — lists every
enabled account's `id`/`label`/`mode`/`enabled` from `configs/accounts.yaml`
for the frontend's future account switcher (Phase 8) and as the source of
truth for every other route's valid `{account_id}`. Global, unprefixed. New
`accounts` OpenAPI tag added alongside it; `account`/`broker`/`market-data`/
`journal`/`activity`/`engine`/`ai`/`strategies` tag descriptions updated to
note their new per-account scoping.

**Done:** all of the above shipped as described. Every affected route test
updated to the new paths — the existing `SimpleNamespace`-stubbed pattern
extends unchanged, just one level deeper (`SimpleNamespace(accounts={"default":
SimpleNamespace(trade_journal=service)})` instead of
`SimpleNamespace(trade_journal=service)`), and the three hand-wired
integration `ContainerForTest` classes (`test_phase1_flow.py`,
`test_phase3_broker_flow.py`, `test_phase4_engine_flow.py`) each gained one
line, `self.accounts = {"default": self}`, since they already carry every
`AccountRuntime`-scoped field a flat object needs. `uv run ruff check src
tests` clean (same one pre-existing unrelated collection failure as
Phases 1–5); full `uv run pytest` green: 1156 passed. Verified the full
`/openapi.json` schema directly (no running server needed — the FastAPI
`app` object builds identically either way): every new/changed path shows
up under `/accounts/{account_id}/...` as expected, `GET /accounts` has a
summary+description, and the shared `account_id` path parameter carries a
description on every single route that uses it (confirmed via a raw schema
dump — this was the one gap the first pass missed, since
`get_account_runtime`'s original `account_id: str` signature had no
`Path(description=...)` and FastAPI doesn't synthesize one).

**Caveat from this pass:** an errant `uv run ruff format src tests` (meant
to reflow a handful of newly-too-long lines from added `/accounts/{account_id}`
prefixes) reformatted the entire tree — around 65 files outside this
phase's scope, including every file under `strategies/generated/` (AI/
manually-authored strategy code CLAUDE.md says dev tooling must never
modify without a clear reason). Caught before committing anything; every
such file was restored via `git checkout --` and formatting was re-run
scoped to just the files this phase actually touched. Worth remembering for
future phases: never run repo-wide `ruff format`, always pass explicit file
paths.

**Files:** `backend/src/shared/api/dependencies.py` (new),
`backend/src/broker/api/accounts.py` (new), `backend/src/broker/api/schemas.py`
(new `AccountSummaryOut`), every `*/api/routes.py` under `backend/src/{broker,
engine,journal,market_data,activity,strategies,ai}`, `backend/src/main.py`
(router registration + `OPENAPI_TAGS`), plus the route/integration tests
listed above.

No frontend change (Phase 8's turn, per the plan's rollout order) — every
`frontend/src/shared/api/client.ts` path is now stale (still hardcodes the
pre-Phase-6 unprefixed routes), a known, deliberate gap until Phase 8.

## Phase 7 — Per-account risk overrides — ✅ Done (2026-07-23)

`configs/risk.yaml` stays the global, user-owned floor — untouched, never
auto-modified, per existing binding rule. Added `apply_risk_override(base:
RiskCaps, override: dict) -> RiskCaps` (`backend/src/engine/application/
risk_manager.py`): merges only the keys present in a per-account override
dict on top of the global `RiskCaps`, field by field — every field not
present in the override keeps the global value. Enforced entirely in code,
never trusted from the file: each of the five plain numeric caps
(`risk_per_trade_pct`, `daily_loss_limit_pct`, `max_open_positions`,
`max_trades_per_day`, `consecutive_loss_pause`) must be `<=` the global
value or the merge raises `ValueError` naming the offending field;
`min_lot_fallback_enabled` may only flip `True -> False`, never the reverse;
`max_risk_per_trade_pct` must be `<=` the global ceiling (`global
max_risk_per_trade_pct` if set, else `global risk_per_trade_pct`) and an
explicit `null` override is rejected outright (there is no way to write a
`null` that "tightens" a ceiling).

`configs/risk/{risk_override_file}.yaml` is optional per account — no such
directory or file exists in this repo today since the only real account
(`default`) has `risk_override_file: null` in `configs/accounts.yaml`; the
directory is created by a human the first time they actually need a
stricter account (e.g. a prop-firm account with a tighter daily-loss rule
than the operator's own global floor), read via the existing
`load_yaml_config(f"risk/{file}", configs_dir)` (subdirectory paths already
supported — same mechanism as `configs/symbols/{symbol}.yaml`), so no new
loader function was needed.

Wired into `container.py`'s `build_container()`: a new
`_resolve_account_risk_caps(global_caps, account_cfg, configs_dir)` helper
returns `global_caps` unchanged when `risk_override_file` is unset, else the
merged result; computed once per account into an `account_risk_caps` dict
*before* the per-account `build_account_runtime()` loop (previously every
account received the same single `risk_caps` value), and each account's
`RiskManager` (`AccountRuntime.risk_manager`) now gets its own resolved
`RiskCaps`. Because `GET /accounts/{account_id}/engine/risk-caps`
(Phase 6) already reads `_risk_manager(account).caps` — a per-account
`RiskManager` instance already existed since Phase 5 — no route or schema
change was needed for the override to become visible over the API.
Backtesting (`backtest/application/run_backtest.py`) is intentionally
untouched: it calls `load_risk_caps()` directly against the global file, per
this phase's original scope note — no account-scoped override concept
applies to a standalone backtest run.

**Done:** new tests — 9 cases in
`backend/tests/unit/engine/test_risk_manager.py` covering
`apply_risk_override` (tightening each field, rejecting a loosened value for
each of the 5 plain caps via `pytest.mark.parametrize`, the
`min_lot_fallback_enabled` one-way-flip rule, the `max_risk_per_trade_pct`
ceiling including the explicit-`null`-is-rejected case, and an empty-dict
override producing equivalent caps), plus 2 new `build_container()`-level
tests in `backend/tests/unit/test_container.py`
(`test_account_risk_override_tightens_caps_for_one_account_only`,
`test_account_risk_override_rejects_loosening_at_startup`) proving the
override only affects the one account that sets `risk_override_file` and
that a loosening override fails loudly at container-build time rather than
silently trading under a looser cap. `uv run ruff check src tests` clean
(same one pre-existing unrelated collection failure as Phases 1–6); full
`uv run pytest` green.

**Files:** `backend/src/engine/application/risk_manager.py`
(`apply_risk_override`), `backend/src/container.py`
(`_resolve_account_risk_caps`, per-account `account_risk_caps` dict wired
into `build_account_runtime()`'s `risk_caps` param), test files listed
above. `configs/risk/` directory itself was **not** created — no real
override exists yet in this repo, and an empty speculative directory with a
placeholder file would just be dead weight; a human creates it the first
time an account actually needs a tighter cap.

## Phase 8 — Frontend — ✅ Done (2026-07-23)

Added `AccountContext` (`frontend/src/shared/api/account-context.tsx`) — React
context + `localStorage`-persisted active `account_id`, loaded from a new
`GET /accounts` call, `AccountProvider` mounted in `app/layout.tsx` inside
`LoginGate` (so it only fetches post-auth) and outside `NavigationProvider`.
Exposes `useAccounts()` (full switcher state) and `useActiveAccount()`
(`accountId: string | null` — null until `GET /accounts` first resolves;
every hook/component gates on it exactly like existing code already gates on
an empty `symbol`, so there's no new fallback-to-a-guessed-id failure mode).

**Deviation from this section's original text:** the switcher itself isn't
in a single shared header — every page hand-rolls its own `<header>` with
`<MenuButton />` as the one common element (confirmed via `grep -rl
"MenuButton" src/app`, 15 call sites, no shared header component exists).
Rather than touch all 15 page headers, `MenuButton` itself
(`shared/ui/NavigationDrawer.tsx`) now renders the hamburger icon plus a new
`AccountSwitcher` (a `<select>`, or a static label when only one account is
configured, or nothing while the list is still loading) — one file change
puts the switcher in every page's top nav instead of 15. `AccountPanel.tsx`
(the connect/disconnect form) now reads `useActiveAccount()` and operates on
whichever account is selected, unchanged otherwise.

`client.ts`'s ~35 per-account request helpers each gained an `accountId:
string` first parameter, building `/accounts/{id}/...` paths via a new
`acctPath()` helper — mechanical, matched 1:1 against Phase 6's router
prefixes (`grep -rn "APIRouter(" src/*/api/*.py`) to get the global/
per-account split exactly right: `auth`, `ai-settings`, `skills`, `news`,
`indicators`, `backtest`, the broker `spread_router`, and the strategies
`sandbox_router` stayed unprefixed/global, matching Phase 6/7's own
boundaries; everything else gained the param. New `getAccounts()` (`GET
/accounts`, global, unprefixed — called before any `account_id` is known).
`ws.ts`'s `roomKey`/`subscribeRoom` extended to `{accountId, symbol,
timeframe}`, emitting `account_id` in the `subscribe`/`unsubscribe` payload.

**Deviation found during implementation, not in this section's original
text:** the backend's WS layer (`market_data/api/ws.py`) had no account
concept at all — one global `sio` server, rooms keyed only by
`symbol:timeframe`, bound once at startup to only the *primary* account's
`CandleStreamService`/`LiveCandleService` (a comment in `main.py` said as
much: "Phase 6/8 of MULTI_ACCOUNT_PLAN.md own real multi-account WS room
routing"). Left as-is, the frontend's new `accountId` in `ws.ts` would have
been cosmetic — worse, two accounts holding the same symbol (e.g. `XAUUSD`
on two different brokers) would broadcast into the *same* room and a chart
would silently receive candles from the wrong account. Fixed as part of this
phase, since the frontend change is meaningless without it: rooms are now
`account_id:symbol:timeframe`; `bind_candle_stream`/`bind_live_candle`
became `dict[str, ...]` maps keyed by account, populated by looping
`container.accounts.items()` in `main.py`'s `lifespan()` instead of a single
`container.candle_stream`/`container.live_candle` call; `WsBroadcaster`
(`container.py`, already constructed once per account per Phase 5) now takes
`account_id` in its constructor and scopes every `emit` to that account's
room. An unknown/disabled `account_id` in a `subscribe` payload joins the
room harmlessly but never receives events, since no broadcaster ever emits
into it — no new 404/error path needed on the WS side.

Every hook that already existed (`useTrading`, `useAllPositions`,
`useTradeHistory`, `useActivityLog`, `useActiveStrategyForSymbol`) now calls
`useActiveAccount()` internally and gates its fetch/mutate on a non-null id,
per the plan's "minimize call-site churn" goal — `page.tsx` and every other
caller of these hooks needed zero changes. Components that call `client.ts`
directly (not through a hook) — roughly 30 files across
`features/{strategies,chart,trading,engine,settings,ai-reports,backtest,
bot-control,logs,account}/` plus `app/bots/page.tsx` — each gained one
`useActiveAccount()` call and an `if (!accountId) return;`/early-null guard
at their call sites; found exhaustively via `grep` for every per-account
function name against the codebase, not by eyeballing individual features.

**Files:** `frontend/src/shared/api/client.ts`, `frontend/src/shared/api/ws.ts`,
`frontend/src/shared/api/account-context.tsx` (new), `frontend/src/app/layout.tsx`,
`frontend/src/shared/ui/NavigationDrawer.tsx`,
`frontend/src/features/account/AccountPanel.tsx`, the 5 hooks listed above,
~30 feature components/pages (one `useActiveAccount()` call + guard each) —
`backend/src/market_data/api/ws.py`, `backend/src/main.py`,
`backend/src/container.py` (WS multi-account fix), plus the 3 hand-wired
`ContainerForTest` integration test classes (`WsBroadcaster("default")`).

**Done:** `pnpm exec tsc --noEmit`, `pnpm lint` (oxlint), and `pnpm build`
all clean. Backend: `uv run ruff check src tests` clean (same one
pre-existing unrelated collection failure as Phases 1–7); full `uv run
pytest` green — 1190 passed (up from 1153 at Phase 4/7's last count; the
gap is other work landed on `main` since, not this phase — this phase added
no new backend tests of its own beyond the 3 updated `WsBroadcaster(...)`
call sites, since Phase 8's own scope is frontend-plus-the-WS-fix and the
existing per-account isolation tests from Phases 4/5/7 already cover the
underlying `AccountRuntime`/repository behavior this phase's UI reads).

**Not done this phase, per Phase 9's rollout order:** no live/paper gateway
smoke test with two real MT5 accounts — that's explicitly Phase 9's
end-to-end milestone, run manually against `configs/accounts.yaml` once a
second real account exists. The account switcher itself was exercised only
against the one real `default` account in this repo (renders as the static
single-account label, per `AccountSwitcher`'s `accounts.length === 1`
branch) — its multi-account `<select>` branch and the WS per-account
isolation fix are logic-verified (types, build, existing test suite) but not
visually verified against two live accounts side by side, since no second
account is configured on this machine.

## Phase 9 — Testing & rollout order

**Gap found and fixed while bringing up a second real account (2026-07-24):**
`gateway/src/gateway/mt5_client.py`'s `login()` called `mt5.initialize()` with
no `path` argument, and the Makefile's terminal-launch check was a single
flat `pgrep -x terminal64` shared across every account. MetaTrader5 only
supports one logged-in account per terminal instance — with no `path`,
`initialize()` attaches to *whatever* terminal is already running, so a
second account's gateway would silently log the first account's terminal
into itself instead of getting its own session. Phase 3's "no gateway
source changes needed" conclusion only verified host/port env
parameterization; it never exercised two concurrent terminal sessions
(Phase 8 explicitly flagged this as untested, deferred here).

Fix: `configs/accounts.yaml` gained an optional `mt5_terminal_subpath` field
(path to that account's own `terminal64.exe`, relative to the Wine prefix's
`drive_c/`) — unset for `default`, preserving its exact pre-fix behavior.
`AccountConfig` (`backend/src/broker/domain/account.py`) and
`load_accounts_config` (`backend/src/shared/config/loaders.py`) carry it
through; `print_account_gateway_env.py` exports it as
`TB_RESOLVED_TERMINAL_SUBPATH`. The Makefile's `dev-gateway`/`mt5-terminal`
recipes resolve the right terminal path per account and switch their
running-check from `pgrep -x terminal64` (name-only — wrong once 2+
instances share that binary name) to `pgrep -f <path>` whenever a subpath is
set, and pass `MT5_TERMINAL_SUBPATH` as an env var into the Wine Python
gateway process. `mt5_client.py` reads that env var once at import time,
builds the Windows-style path (`C:\` + subpath with `/` → `\`), and passes
it to `mt5.initialize(path=...)` only when set — `default`'s gateway calls
`mt5.initialize()` exactly as before. `configs/accounts.yaml` now has a
`demo-1` entry (`mt5_terminal_subpath: "MT5-demo-1/terminal64.exe"`,
`gateway_url: http://127.0.0.1:8788`, mode `paper`) for this rollout.

**Still required, operator-side, before running `demo-1`'s gateway for
real:** a second, separate portable MT5 terminal install at
`$(WINEPREFIX)/drive_c/MT5-demo-1/terminal64.exe` (copy the existing
install directory, or reinstall with `/PORTABLE` and a different target
dir under the same Wine prefix) — two `terminal64.exe` processes launched
from the *same* install directory would still contend over that
directory's shared config/session state. Also add
`TB_GATEWAY_SHARED_SECRET_DEMO_1` to `.env` (see `.env.example`) and,
once the terminal exists, log in via the UI's AccountPanel (credentials
are never stored in `.env` — encrypted via the existing per-account
`FernetCredentialStore`, per Phase 2) or `make mt5-login ACCOUNT=demo-1
LOGIN=... PASSWORD=... SERVER=...`.

Verified this pass (no live MT5 involved): `uv run ruff check src tests
scripts` clean in both `backend/` and `gateway/` (same one pre-existing
unrelated collection failure as every prior phase); `uv run pytest` green
in both (backend 1190, gateway 43); `load_accounts_config` resolves both
`default` (subpath `None`, unchanged) and `demo-1` (subpath resolved,
correct port 8788) from the real `configs/accounts.yaml`;
`print_account_gateway_env.py demo-1` and its bare (default) form both
export the right values; `make -n dev-gateway`/`dev-gateway
ACCOUNT=demo-1`/`mt5-terminal ACCOUNT=demo-1` all resolve their recipes
correctly.

**Files:** `gateway/src/gateway/mt5_client.py`,
`backend/src/broker/domain/account.py`,
`backend/src/shared/config/loaders.py`,
`backend/scripts/print_account_gateway_env.py`, `Makefile`
(`dev-gateway`, `dev-gateway-all`, `mt5-terminal`), `configs/accounts.yaml`
(new `demo-1` entry), `.env.example` (new
`TB_GATEWAY_SHARED_SECRET_DEMO_1` placeholder).


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
