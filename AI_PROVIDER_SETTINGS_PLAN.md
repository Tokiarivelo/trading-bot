# Multi-Provider AI Settings — Implementation Plan

Companion to `IMPLEMENTATION_PLAN.md` §6.7 and §8. This plan replaces the
current build-time, hardcoded `claude` / `ollama` choice in `configs/ai.yaml`
with a **Settings page** where an operator picks, per AI task, which provider
runs it — without a backend restart — from:

1. **Claude Code** — the Claude Code CLI/agent, run headless as a subprocess.
2. **Hermes Agent** — a curated Nous-Hermes model preset, run through the
   existing Ollama adapter (not a new backend provider — see §2).
3. **Ollama** — any locally pulled model (unchanged from today).
4. **OpenClaw** — a fourth provider whose API contract is **not yet known**
   (see §2.4). Its adapter is designed as a pluggable skeleton pending real
   docs from the user.

Read this alongside `backend/src/ai/` before touching code — nothing outside
`ai/adapters/` may import a provider SDK/CLI, per `CLAUDE.md`.

## Table of Contents
1. Goals & non-goals
2. Provider clarifications
3. Current state (as of this plan)
4. Target architecture
5. Config & secrets design
6. Backend changes, file by file
7. API surface
8. Frontend: Settings page
9. Provider adapter specs
10. Hot-reload semantics
11. Guardrails carried over unchanged
12. Testing plan
13. Rollout phases / checklist
14. Open questions for the user

---

## 1. Goals & non-goals

**Goals**
- One settings page lists the four AI tasks that exist today —
  `pdf_extraction` (document analysis), `code_generation` (bot/strategy
  generation), `ten_trade_review` and `code_refinement` (order/trade analysis
  for the self-refinement loop) — and lets the operator assign a
  provider + model to each, independently.
- Changing a task's provider takes effect without restarting the backend.
- Provider credentials/config stay out of git and out of logs, per
  `CLAUDE.md`'s "secrets only via `.env` / OS keyring" rule — the settings
  page edits *which provider + model* a task uses, never raw API keys.
- Adding a fifth provider later is a new adapter class + one registry entry,
  not a rewrite (`LLMRouter` already isolates this — see §4.1).

**Non-goals**
- Not replacing the sandbox validation, backtest-gated auto-refinement, or
  risk-cap guardrails in `refinement_loop.py` / `pdf_to_strategy.py` — those
  are provider-agnostic today and stay that way.
- Not building a generic "any OpenAI-compatible endpoint" BYO-provider UI.
  Four named providers, not an arbitrary list — that's a bigger feature the
  user hasn't asked for.
- Not deciding *for* the user whether raw Anthropic API access
  (`provider: claude`) is removed or kept as a fifth silent option — flagged
  as an open question in §14, defaulted to "kept" for now (least destructive).

---

## 2. Provider clarifications

Resolved with the user before writing this plan:

### 2.1 Claude Code
A genuinely new provider: instead of calling the Anthropic Messages API
directly (`ClaudeAdapter`, today's `provider: claude`), shell out to the
`claude` CLI in headless print mode. This uses the operator's local Claude
Code login/subscription rather than `TB_ANTHROPIC_API_KEY`, and is a
materially different adapter (subprocess, not HTTP client) — see §9.1.

**Decision: keep `claude` (direct Anthropic API) as a provider alongside
`claude_code`.** Confirmed with the user — least destructive, and justified
by a real cost/latency difference measured directly against the installed
CLI (§9.1): every headless `claude -p` call carries **~8,500–11,800 tokens
of fixed overhead** (environment/tool-schema blocks baked into the CLI's
system prompt) before the actual prompt, even with `--tools ""`. A trivial
2-token "reply with pong" call cost **$0.052–$0.071** and ~3s just in
overhead. For a task like `ten_trade_review` that may run automatically
every 10 trades, that overhead is not negligible — `claude` (raw API, no
CLI overhead) stays the right choice for high-frequency tasks, while
`claude_code` is better suited to occasional, high-context tasks (e.g.
`code_generation`, `code_refinement`) where the operator wants Claude Code's
subscription billing instead of metered API billing. Both remain in
`KNOWN_PROVIDERS`; the settings page shows them as two distinct options.

### 2.2 Hermes Agent
**Not a new backend provider.** Confirmed with the user: "Hermes Agent" means
a Nous-Hermes model (e.g. `hermes3:70b`, `hermes3:8b`) served through the
already-existing `OllamaAdapter`. It is surfaced in the settings UI as a
one-click **preset** — picking "Hermes Agent" for a task sets
`{ provider: ollama, model: "hermes3:8b" }` under the hood. No new adapter
class, no new `LLMRouter` branch. This keeps `ProviderSpec.provider` at
exactly the values the backend already understands plus the two genuinely
new ones (`claude_code`, `openclaw`).

**Decision: default preset is `hermes3:8b`.** Confirmed with the user —
lighter/faster, a reasonable default for frequent tasks (`ten_trade_review`)
on modest hardware. `hermes3:70b` is still offered as a second quick-pick
chip for operators who'd rather trade latency for quality; §8's
`ProviderTaskTable.tsx` shows both, with `hermes3:8b` preselected.

### 2.3 Ollama
Unchanged — any model already pulled locally, chosen by free-text/dropdown
in the settings UI (today this is only a YAML edit).

### 2.4 OpenClaw
**Contract unknown, and the user has confirmed proceeding on the guess
rather than supplying real docs.** §9.4 designs `OpenClawAdapter` against
the same `LLMPort.complete()` contract every other adapter implements, with
the wire format assumed to be an **OpenAI-compatible chat-completions HTTP
endpoint** (base URL + API key + model — the most common self-hosted-agent
contract, and a reasonable placeholder).

**Decision: ship it as an unverified stub, registered but clearly marked.**
Because the contract is a guess, not a confirmation, `OpenClawAdapter` is
still gated behind Phase 10.1's "hold until confirmed" note in §13 — it gets
written and unit-tested against its own assumed contract (so the rest of the
system — registry, settings API, frontend — is exercised end-to-end), but
the settings page should label it clearly (e.g. a "beta / unverified"
badge) until someone confirms it against a real OpenClaw instance. Nothing
else in the plan changes if the contract turns out different, because
everything upstream of the adapter only ever sees `LLMPort`.

---

## 3. Current state (as of this plan)

All AI integration lives in the hexagonal `backend/src/ai/` module; nothing
else imports a provider SDK. Confirmed by reading the code directly:

| File | Role |
|---|---|
| `backend/src/ai/ports/llm.py` | `LLMMessage`, `ProviderSpec(provider: str, model: str)`, `LLMPort` protocol (`async complete(message, *, max_tokens=4096) -> str`) |
| `backend/src/ai/adapters/claude.py` | `ClaudeAdapter` — wraps `anthropic.AsyncAnthropic` |
| `backend/src/ai/adapters/ollama.py` | `OllamaAdapter` — `httpx` POST to `/api/chat` |
| `backend/src/ai/application/llm_router.py` | `LLMRouter.for_task(task)` → builds/caches an adapter from `configs/ai.yaml: provider_per_task[task]`; `_build()` is an `if/elif` on `spec.provider` (`"claude"` / `"ollama"`, else `ValueError`) |
| `configs/ai.yaml` | `provider_per_task` map (4 tasks today, all `provider: claude`), `refinement` policy block |
| `backend/src/shared/config/settings.py:27-28` | `anthropic_api_key`, `ollama_url` — the only provider secrets today |
| `backend/src/container.py:268-272` | Builds **one shared `LLMRouter`** at startup: `LLMRouter(load_llm_provider_config(...), anthropic_api_key=settings.anthropic_api_key, ollama_url=settings.ollama_url)` |
| `backend/src/ai/application/pdf_to_strategy.py` | Document analysis → `StrategySpec` (task `pdf_extraction`) and code generation (task `code_generation`) |
| `backend/src/ai/application/refinement_loop.py` | 10-trade review (task `ten_trade_review`) and code refinement (task `code_refinement`) |

Two gaps this plan must close:
- `LLMRouter._build()` hardcodes exactly two providers by string comparison
  — a third/fourth provider needs new branches, and its constructor only
  accepts `anthropic_api_key` / `ollama_url`, not a general credential set.
- `LLMRouter` **caches an adapter instance per task the first time it's
  used** (`llm_router.py:38-41`) and is built once at container startup.
  `IMPLEMENTATION_PLAN.md` §10.1 already documents `configs/ai.yaml` as
  "hot-reload: yes," but nothing currently invalidates that cache — editing
  the YAML today has no effect until restart. A real settings page makes
  this gap visible, so §10 fixes it.

---

## 4. Target architecture

### 4.1 Provider registry instead of `if/elif`

Replace `LLMRouter._build()`'s string comparison with a small provider
registry so adding provider #5 later never touches `LLMRouter` again:

```python
# backend/src/ai/application/llm_router.py
ProviderFactory = Callable[[ProviderSpec], LLMPort]

class LLMRouter:
    def __init__(self, provider_per_task: dict[str, ProviderSpec], factories: dict[str, ProviderFactory]) -> None:
        self._provider_per_task = provider_per_task
        self._factories = factories          # {"claude": ..., "ollama": ..., "claude_code": ..., "openclaw": ...}
        self._cache: dict[str, LLMPort] = {}

    def _build(self, spec: ProviderSpec) -> LLMPort:
        factory = self._factories.get(spec.provider)
        if factory is None:
            raise ValueError(f"unknown LLM provider: {spec.provider!r}")
        return factory(spec)
```

`container.py` assembles the `factories` dict from `Settings` (credentials
live there, per `CLAUDE.md`) — each factory is a closure over the one secret
it needs, so `LLMRouter` itself never sees a raw API key:

```python
# backend/src/container.py
factories: dict[str, ProviderFactory] = {
    "claude": lambda spec: _require_claude(settings.anthropic_api_key, spec),
    "ollama": lambda spec: OllamaAdapter(settings.ollama_url, spec.model),
    "claude_code": lambda spec: ClaudeCodeAdapter(settings.claude_code_binary, spec.model),
    "openclaw": lambda spec: _require_openclaw(settings.openclaw_url, settings.openclaw_api_key, spec),
}
llm_router = LLMRouter(load_llm_provider_config(settings.configs_dir), factories)
```

This is the only structural change needed to support N providers — §9 gives
each new adapter's internals.

### 4.2 Two-layer config: YAML defaults + DB overrides

`configs/ai.yaml` stays the versioned, reviewed **default** `provider_per_task`
map (what ships in a fresh checkout / what CI uses). The Settings page writes
**overrides** to a new DB table, not to the YAML file — this matches how
`configs/risk.yaml` is treated as user-owned-but-not-app-writable, and avoids
an app process rewriting a git-tracked file on disk (which would fight the
developer's own edits and show up as unexplained working-tree diffs).

`LLMRouter.provider_per_task` is resolved at call time as
`db_overrides.get(task) or yaml_defaults[task]`, described fully in §6.3.

### 4.3 Module placement

New code lives inside the existing `backend/src/ai/` module (it's this
module's own configuration, not a new bounded context):

```
backend/src/ai/
  domain/
    provider_config.py       # NEW — TaskProviderOverride dataclass, PROVIDERS enum/registry metadata
  adapters/
    claude_code.py            # NEW
    openclaw.py                # NEW
    provider_config_repository.py  # NEW — DB-backed override store
    orm.py                     # extend with ai_task_provider_override table
  application/
    llm_router.py              # MODIFIED — registry-based, see §4.1
    provider_settings.py        # NEW — application service: list/get/set task overrides, test-connection
  api/
    routes_settings.py          # NEW — GET/PUT task overrides, POST test-connection
    schemas.py                   # extend with settings request/response models
```

---

## 5. Config & secrets design

Per `CLAUDE.md`: *"Config is YAML in `configs/`, loaded through
`shared/config`; secrets only via `.env` / OS keyring — never hardcoded,
never logged."* This constrains the settings page tightly: it may change
**which provider/model a task uses**, never accept or persist a raw API key
from the browser.

| What | Where it lives | Who writes it |
|---|---|---|
| Default `provider_per_task` (shipped, reviewed) | `configs/ai.yaml` | developer, git-tracked |
| Per-task override (operator's live choice) | new DB table `ai_task_provider_override` | Settings page, via API |
| Anthropic API key (`claude`) | `.env` → `Settings.anthropic_api_key` | operator, file/OS env only |
| Ollama base URL | `.env` → `Settings.ollama_url` | operator |
| Claude Code CLI path/extra args | `.env` → `Settings.claude_code_binary`, `Settings.claude_code_extra_args` (defaults: `"claude"`, `""`) | operator, optional (has default) |
| OpenClaw base URL + API key | `.env` → `Settings.openclaw_url`, `Settings.openclaw_api_key` | operator |

New `Settings` fields (`backend/src/shared/config/settings.py`), all with
the existing `TB_` prefix convention:

```python
claude_code_binary: str = "claude"
claude_code_extra_args: str = ""
openclaw_url: str = ""
openclaw_api_key: str = ""
```

And `.env.example` additions alongside the existing AI-provider block:

```
# AI providers (leave empty to disable a provider)
TB_ANTHROPIC_API_KEY=
TB_OLLAMA_URL=http://127.0.0.1:11434
TB_CLAUDE_CODE_BINARY=claude
TB_OPENCLAW_URL=
TB_OPENCLAW_API_KEY=
```

The settings page's "test connection" action (§7) reports *whether* a
provider is configured (its factory raises `LLMProviderNotConfiguredError`)
without ever displaying or accepting the secret value itself — consistent
with how the existing `pdf_extraction`/etc. routes already turn that
exception into a 503 rather than leaking config state.

---

## 6. Backend changes, file by file

### 6.1 `backend/src/ai/ports/llm.py`
No change to `LLMPort`/`LLMMessage`. `ProviderSpec.provider` stays a plain
`str` (not an enum) so new provider names are a data change, not a code
change — but add a module-level constant used by validation and the
settings API:

```python
KNOWN_PROVIDERS = ("claude", "ollama", "claude_code", "openclaw")
```

### 6.2 `backend/src/ai/domain/provider_config.py` (new)

```python
@dataclass(frozen=True)
class TaskProviderOverride:
    task: str
    provider: str
    model: str
    updated_at: datetime
```

Pure domain data — no pydantic, no SQLAlchemy (per `CLAUDE.md` hexagonal
rule: domain stays framework-free).

### 6.3 `backend/src/ai/adapters/provider_config_repository.py` (new)
SQLAlchemy-backed, mirrors the existing `DraftRepository` /
`AnalysisReportRepository` pattern (session-factory constructor injection,
async methods). New table via `orm.py`:

```python
class TaskProviderOverrideRow(Base):
    __tablename__ = "ai_task_provider_override"
    task: Mapped[str] = mapped_column(primary_key=True)
    provider: Mapped[str]
    model: Mapped[str]
    updated_at: Mapped[datetime]
```

`ProviderConfigRepository.get_all() -> dict[str, TaskProviderOverride]`,
`.set(task, provider, model) -> None`, `.clear(task) -> None` (revert to
YAML default). New Alembic migration (see `make migrate` target in the root
Makefile) adding this one table.

### 6.4 `backend/src/ai/application/llm_router.py` (modified)
As in §4.1, plus resolution order and cache invalidation:

```python
def for_task(self, task: str) -> LLMPort:
    spec = self._overrides.get(task) or self._provider_per_task.get(task)
    if spec is None:
        raise ValueError(f"no LLM provider configured for task {task!r}")
    cache_key = (task, spec.provider, spec.model)
    if cache_key not in self._cache:
        self._cache[cache_key] = self._build(spec)
    return self._cache[cache_key]

def set_override(self, task: str, spec: ProviderSpec) -> None:
    self._overrides[task] = spec   # next for_task() call rebuilds under a new cache key
```

Keying the cache by `(task, provider, model)` instead of just `task` means an
override takes effect on the very next call with **no explicit invalidation
needed** — stale entries simply stop being requested. This is simpler and
safer than a cache-bust method (§10 covers this in detail).

### 6.5 `backend/src/ai/application/provider_settings.py` (new)
Thin application service the API layer calls:
- `list_tasks() -> list[TaskProviderStatus]` — for each of the 4 known
  tasks: current effective `provider`/`model` (override or YAML default),
  `source: "override" | "default"`, and `configured: bool` (does the
  resolved provider have its required secret/URL set in `Settings`, without
  revealing the secret).
- `set_task_provider(task, provider, model) -> None` — validates `provider in
  KNOWN_PROVIDERS` and `task` is one of the 4 real task names, persists via
  `ProviderConfigRepository.set`, then calls `llm_router.set_override(...)`.
- `clear_task_provider(task) -> None` — same, via `.clear` / removing the
  override so `for_task` falls back to the YAML default.
- `test_provider(provider) -> bool` — attempts a 1-token `complete()` call
  against a throwaway `ProviderSpec` for that provider using a fixed cheap
  model, catching `LLMProviderNotConfiguredError` and provider SDK/HTTP
  errors, returning a simple boolean (+ error message) rather than raising —
  this is the backing call for the settings page's "Test" button.

### 6.6 `backend/src/container.py` (modified)
Lines 268-272 become the registry-factory construction from §4.1, plus
wiring the new repository and application service:

```python
provider_config_repository = ProviderConfigRepository(session_factory)
llm_router = LLMRouter(
    load_llm_provider_config(settings.configs_dir),
    factories=_build_provider_factories(settings),
    overrides=await provider_config_repository.get_all(),
)
provider_settings = ProviderSettingsService(
    repository=provider_config_repository,
    llm_router=llm_router,
    settings=settings,
)
```

`_build_provider_factories(settings)` is a small module-level function (not
inline lambdas as shown in §4.1 — that was illustrative) so it's unit
testable in isolation. Add `provider_settings: ProviderSettingsService` to
the `Container` dataclass alongside `pdf_to_strategy` / `refinement_loop`.

---

## 7. API surface

New router `backend/src/ai/api/routes_settings.py`, mounted alongside
`ai_router` in `main.py` with a new OpenAPI tag entry in `OPENAPI_TAGS`
(`backend/src/main.py:56`):

```python
{
    "name": "ai-settings",
    "description": "Per-task AI provider selection (Claude Code, Hermes Agent "
    "via Ollama, Ollama, OpenClaw) for document analysis, strategy generation, "
    "and trade-review/refinement. Changes apply without a backend restart.",
},
```

| Method & path | `response_model` | Purpose |
|---|---|---|
| `GET /ai/settings/tasks` | `list[TaskProviderStatusOut]` | Current provider/model per task (`pdf_extraction`, `code_generation`, `ten_trade_review`, `code_refinement`), override vs. default, configured flag |
| `PUT /ai/settings/tasks/{task}` | `TaskProviderStatusOut` | Body `{ provider, model }`; validates against `KNOWN_PROVIDERS`; `404` if `task` unknown, `422` if provider unknown |
| `DELETE /ai/settings/tasks/{task}` | `TaskProviderStatusOut` | Clears the override, reverts to the YAML default |
| `POST /ai/settings/providers/{provider}/test` | `ProviderTestResultOut` | Body-less; runs `test_provider()`; `503` mapped from `LLMProviderNotConfiguredError` same as existing AI routes |
| `GET /ai/settings/providers` | `list[ProviderInfoOut]` | Static catalog: id, display name, description, whether it needs a secret, and (for `ollama`) the Hermes preset models to show as quick picks |

Every route needs `summary`, `description`, and `responses=` entries per
`CLAUDE.md`'s binding OpenAPI-documentation rule — follow the existing style
in `backend/src/ai/api/routes_refinement.py` as the closest precedent.

`TaskProviderStatusOut` / `ProviderInfoOut` / `ProviderTestResultOut` are new
Pydantic models in `backend/src/ai/api/schemas.py`, each `Field` carrying a
`description`, mirroring `domain/provider_config.py`'s dataclasses (never
importing pydantic into `domain/`).

---

## 8. Frontend: Settings page

Mirrors the newest precedent, `frontend/src/features/ai-reports/` +
`frontend/src/app/ai-reports/`, file-for-file:

```
frontend/src/features/settings/
  ProviderTaskTable.tsx     # 4 rows (one per task), provider dropdown + model input/presets, Save
  ProviderStatusBadge.tsx   # green/red dot + label from `configured`
  ProviderTestButton.tsx    # calls test endpoint, shows pass/fail inline

frontend/src/app/settings/
  page.tsx                  # thin shell: <header>+<main>, renders ProviderTaskTable
```

`frontend/src/shared/api/client.ts` — new section following the existing
comment-banner convention (`// ── AI: PDF -> StrategySpec pipeline ...`):

```ts
// ── AI: provider settings (per-task LLM selection) ──────────────────────────
export interface TaskProviderStatus { task: string; provider: string; model: string; source: "override" | "default"; configured: boolean }
export interface ProviderInfo { id: string; label: string; needsSecret: boolean; presetModels?: { label: string; model: string }[] }
export async function listTaskProviders(): Promise<TaskProviderStatus[]> { ... }
export async function setTaskProvider(task: string, provider: string, model: string): Promise<TaskProviderStatus> { ... }
export async function clearTaskProvider(task: string): Promise<TaskProviderStatus> { ... }
export async function testProvider(provider: string): Promise<{ ok: boolean; message?: string }> { ... }
export async function listProviders(): Promise<ProviderInfo[]> { ... }
```

Types are hand-written here only because this plan predates codegen for this
route; once `/ai/settings/*` routes exist and `make openapi` is run, prefer
generating these from the OpenAPI schema per the project's stated convention
("API types come from the backend OpenAPI schema — don't hand-write
duplicates").

Nav link in `frontend/src/app/page.tsx` (next to the existing links around
line 259):

```tsx
<Link href="/settings" className="text-sm text-ink-muted hover:text-accent">
  Settings
</Link>
```

**UI content per task row**: task label in plain language ("Document
analysis (PDF → strategy)", "Strategy code generation", "10-trade review",
"Code refinement"), provider dropdown with exactly the 4 options (Claude
Code / Hermes Agent / Ollama / OpenClaw), a model field that becomes a preset
picker when Hermes Agent is selected (per §2.2, this just sets
`provider=ollama` + a curated model string under the hood — the row still
displays "Hermes Agent" via the `source`/label mapping, not "Ollama", so the
UI must track "which preset produced this override," e.g. by matching the
resolved model string against the Hermes preset list client-side), a status
badge from `configured`, and a Test button.

Before declaring this task done: `make lint-frontend` and
`make build-frontend`, and manually exercise the page against a running
backend (`make dev-backend` + `make dev-frontend`) — set each task to each
provider, confirm the badge/test button reflect real `.env` state, confirm a
refinement-loop run picks up a changed `ten_trade_review` provider without a
restart.

---

## 9. Provider adapter specs

All four implement the exact same `LLMPort.complete(message, *,
max_tokens=4096) -> str` — callers in `pdf_to_strategy.py` /
`refinement_loop.py` need zero changes regardless of which providers exist.

### 9.1 `ClaudeCodeAdapter` (new) — `backend/src/ai/adapters/claude_code.py`

**Flags verified directly against the installed Claude Code CLI** (`claude
--help`, plus two live `claude -p ... --output-format json` calls) — this is
no longer a guess:

- `-p "<prompt>"` — headless print mode, exits after one response.
- `--output-format json` — single JSON object on stdout; the completion text
  is in the **`result`** field (confirmed by an actual call — full shape
  includes `type`, `subtype`, `is_error`, `result`, `total_cost_usd`,
  `usage`, `session_id`, `stop_reason`).
- `--tools ""` (not `--allowed-tools ""`) is the correct flag to fully
  disable the built-in tool set — `--allowedTools` is an allow-list *within*
  the default tools, `--tools ""` removes them entirely. Confirmed: a call
  with `--tools ""` returned `"permission_denials":[]` and no permission
  prompts, i.e. it never even offered a tool to use.
- `--no-session-persistence` — don't leave a resumable session on disk for
  every one-off completion call.
- `--model <alias-or-full-name>` — accepts `sonnet`/`opus`/`fable` aliases or
  a full model name.
- No `--mcp-config` passed, plus `--strict-mcp-config` — guarantees zero MCP
  tools load from project/user config, keeping this a pure text boundary.

**Cost/latency finding (measured, not estimated):** even with `--tools ""`,
each call pays **8,500–11,800 tokens of fixed overhead** (environment info,
tool schemas baked into the CLI's system prompt) before the real prompt is
counted. Two live test calls: a trivial "reply with pong" cost **$0.052**
(8,523 cache-creation tokens, warm cache-read path) and **$0.071** when a
custom `--system-prompt` was supplied (11,830 cache-creation tokens — a
custom system prompt invalidates the CLI's default prompt cache rather than
reducing overhead). **Conclusion: do not pass `--system-prompt`** — instead
fold `message.system` into the prompt text as originally planned, so repeat
calls with the same effective prompt can hit the CLI's own prompt cache.
This overhead is also *why* §2.1 keeps raw `claude` alongside `claude_code`
— high-frequency tasks should default to the cheaper raw-API path.

```python
class ClaudeCodeAdapter:
    def __init__(self, binary: str, model: str, extra_args: str = "") -> None:
        self._binary = binary
        self._model = model
        self._extra_args = shlex.split(extra_args) if extra_args else []

    async def complete(self, message: LLMMessage, *, max_tokens: int = 4096) -> str:
        prompt = f"{message.system}\n\n{message.user}"
        proc = await asyncio.create_subprocess_exec(
            self._binary, "-p", prompt,
            "--model", self._model,
            "--output-format", "json",
            "--tools", "",                  # disable built-in tools entirely — text in, text out
            "--strict-mcp-config",           # + no --mcp-config passed => zero MCP tools
            "--no-session-persistence",
            *self._extra_args,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180.0)
        if proc.returncode != 0:
            raise RuntimeError(f"claude code exited {proc.returncode}: {stderr.decode()[:500]}")
        payload = json.loads(stdout)
        if payload.get("is_error"):
            raise RuntimeError(f"claude code returned an error result: {payload!r}")
        return payload["result"]
```

Notes:
- `max_tokens` isn't a CLI flag the way it is for `AsyncAnthropic.messages.create`
  — Claude Code manages output length itself (`modelUsage.maxOutputTokens`
  in the test response was 64000). The `max_tokens` parameter on `LLMPort`
  is accepted for interface compatibility but not forwarded; callers that
  truly need a hard cap should keep prompting for concise output, same as
  they already do.
- `LLMProviderNotConfiguredError` for this provider means "binary not found
  on `PATH`" — check via `shutil.which(binary)` at factory-build time,
  mapped the same way missing `TB_ANTHROPIC_API_KEY` is today. (Auth itself
  isn't independently probed — an unauthenticated CLI will surface as a
  non-zero exit / `is_error: true` on first real use, which the `RuntimeError`
  paths above already handle.)
- Concurrency: each call spawns a process; the trading engine must never
  block on this — `ten_trade_review`/`code_refinement` already run off the
  event bus asynchronously (§ "Guardrails," `refinement_loop.py`'s
  catch-all wrapper), so a slow/hung CLI call degrades to "no report this
  cycle," not an engine stall. Keep the `asyncio.wait_for` timeout.

### 9.2 Hermes Agent
No new adapter — see §2.2. Settings-page "Hermes Agent" preset resolves to
`ProviderSpec(provider="ollama", model=<preset>)`, built by the existing
`OllamaAdapter`.

### 9.3 Ollama
Unchanged (`backend/src/ai/adapters/ollama.py`), reused for both the
"Ollama" and "Hermes Agent" UI options.

### 9.4 `OpenClawAdapter` (new, stubbed) — `backend/src/ai/adapters/openclaw.py`

```python
class OpenClawAdapter:
    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self._model = model

    async def complete(self, message: LLMMessage, *, max_tokens: int = 4096) -> str:
        # ASSUMPTION (unverified): OpenAI-compatible /v1/chat/completions contract.
        # Confirm against real OpenClaw docs before this ships; only this method's
        # body should need to change if the real contract differs.
        async with httpx.AsyncClient(base_url=self._base_url, timeout=120.0) as client:
            response = await client.post(
                "/v1/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self._model,
                    "max_tokens": max_tokens,
                    "messages": [
                        {"role": "system", "content": message.system},
                        {"role": "user", "content": message.user},
                    ],
                },
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
```

`LLMProviderNotConfiguredError` when `openclaw_url` or `openclaw_api_key` is
empty, same pattern as `claude`. **Do not merge Phase 10.1's OpenClaw branch
until the real API contract is confirmed** — ship the other three providers
first if OpenClaw's docs aren't available yet (see §14).

---

## 10. Hot-reload semantics

Today `configs/ai.yaml` is documented as hot-reloadable but isn't, in
practice, because `LLMRouter` caches one adapter per task for the process
lifetime with no invalidation path. This plan fixes it two ways at once:

1. **Settings-page overrides** (the main path operators will use) go through
   `LLMRouter.set_override()` (§6.4), which changes the cache key
   immediately — the very next `for_task(...)` call in `pdf_to_strategy.py`
   or `refinement_loop.py` builds a fresh adapter. No polling, no file
   watcher needed, because the write and the read both go through the same
   in-process object.
2. **Direct `configs/ai.yaml` edits** (developer workflow, no restart) are
   out of scope for this plan — keep documenting that path as "restart
   required" in `IMPLEMENTATION_PLAN.md` §10.1 unless the user separately
   asks for a file-watcher. The settings page is the hot-reloadable path;
   the YAML file is the versioned-defaults path, and those are allowed to
   have different reload semantics.

---

## 11. Guardrails carried over unchanged

None of this plan touches the safety-critical parts of the AI layer — it
only changes *which adapter* `LLMRouter.for_task()` returns:

- Generated/refined strategy code still always passes through
  `backend/src/strategies/sandbox.py` via
  `strategy_versions.save_generated_code(...)` regardless of which of the 4
  providers produced it.
- `configs/risk.yaml` remains user-owned; no code in this plan reads or
  writes it.
- `backend/src/engine/` circuit breakers are untouched.
- `refinement.mode` (`suggest`/`auto`), `auto_apply_min_improvement_pct`, and
  `max_auto_refinements_per_day` in `configs/ai.yaml` keep gating
  auto-application exactly as today — provider choice and refinement policy
  are orthogonal.
- `LLMProviderNotConfiguredError` → HTTP 503 mapping is preserved and
  extended to the two new providers, so a misconfigured Claude Code/OpenClaw
  task fails the same legible way `claude`/`ollama` do today.

---

## 12. Testing plan

Per `CLAUDE.md`: every broker-affecting change needs unit tests; this isn't
broker-affecting, but the existing `backend/tests/unit/ai/` suite (mirrors
Phase 6/7 tests) is the pattern to extend:

- `test_llm_router.py`: registry-based `_build()` resolves all 4 providers
  correctly; unknown provider raises `ValueError`; override takes effect on
  next `for_task()` call without cache staleness; missing secret raises
  `LLMProviderNotConfiguredError` for `claude`, `claude_code`, `openclaw`.
- `test_claude_code_adapter.py`: mock `asyncio.create_subprocess_exec`
  (patch it, don't shell out in CI); assert prompt/flags construction, JSON
  parse of `stdout`, non-zero-exit → `RuntimeError`, timeout → raised.
- `test_openclaw_adapter.py`: `httpx` mock/respx; asserts request shape
  (until real contract confirmed, tests encode the *assumed* contract and
  must be revisited alongside the adapter body per §9.4/§14).
- `test_provider_settings.py`: `list_tasks`/`set_task_provider`/
  `clear_task_provider`/`test_provider` service methods against a fake
  repository + fake `LLMRouter`.
- `test_routes_settings.py`: FastAPI `TestClient` — 200/404/422/503 paths for
  each route, response bodies match `response_model` (OpenAPI-doc rule).
- Frontend: no existing test runner beyond lint/build per `CLAUDE.md`
  ("Before declaring any frontend task done, run `make lint-frontend` and
  `make build-frontend`") — manually exercise the page per §8's last
  paragraph.

Gate before declaring done, from `backend/`: `uv run ruff check src tests`
and `uv run pytest`, plus `uv run alembic upgrade head` (or equivalent
project migration command) for the new table.

---

## 13. Rollout phases / checklist

Follows `IMPLEMENTATION_PLAN.md` §12's phase format — this is "Phase 10."

### Phase 10.1 — Backend provider registry refactor — DONE (2026-07-12)
- [x] `LLMRouter` → registry/factory-based (`llm_router.py`), cache keyed by `(task, provider, model)`, plus `set_override`/`clear_override` for the future settings-page write path (Phase 10.2)
- [x] `ClaudeCodeAdapter` (subprocess, headless, tool-use disabled, flags verified per §9.1)
- [x] `OpenClawAdapter` (assumed OpenAI-compatible contract per §2.4/§9.4) — registered, marked unverified/beta in factory error text and adapter docstring; settings-UI badge itself lands in Phase 10.4
- [x] New `Settings` fields (`claude_code_binary`, `claude_code_extra_args`, `openclaw_url`, `openclaw_api_key`) + `.env.example` entries
- [x] `container.py` wiring updated — `_build_provider_factories(settings)` builds one closure per provider (`backend/src/container.py:387-424`), composition root now imports all four adapters directly per its own "only place concrete adapters are chosen" rule
- [x] Unit tests: `test_llm_router.py` (override/cache-key semantics), `test_claude_code_adapter.py` (subprocess flags + JSON parsing), `test_openclaw_adapter.py` (assumed HTTP contract) — 401 passed, `ruff check src tests` clean
- [x] `configs/ai.yaml` comments updated to document all 4 provider values and the Hermes Agent preset mapping

Note: `ProviderConfigRepository`/DB-backed overrides and the settings API
(§6.3-§6.5, §7) are Phase 10.2 — `LLMRouter.set_override`/`clear_override`
exist now but nothing calls them yet outside tests; `container.py` still
only threads YAML defaults through.

### Phase 10.2 — Persistence + settings service — DONE (2026-07-12)
- [x] `TaskProviderOverride`/`TaskProviderStatus`/`ProviderTestResult` domain models + `KNOWN_TASKS` (`ai/domain/provider_config.py`), `ProviderConfigRepository` (`ai/adapters/provider_config_repository.py`), migration `369b56f79a5d_ai_task_provider_override_table` for `ai_task_provider_override` (verified upgrade/downgrade/upgrade against a scratch DB, applied to the dev DB)
- [x] `LLMRouter` extended (not rewritten) with `resolve()` (spec + "override"/"default" source), `check_configured()` (build-only, no network, no secret exposure), and `build_adapter()` (uncached, for one-off probes) — `for_task()` now delegates to `resolve()` internally, existing cache/override/clear semantics from Phase 10.1 untouched
- [x] `ProviderSettingsService` (`ai/application/provider_settings.py`): `list_tasks`/`set_task_provider`/`clear_task_provider`/`test_provider`, validates against `KNOWN_TASKS`/`KNOWN_PROVIDERS` (`UnknownTaskError`/`UnknownProviderError`), `test_provider` is a live throwaway `complete()` call per provider (fixed cheap model per provider) that never raises — always returns a `ProviderTestResult`
- [x] `container.py` wired: `ProviderConfigRepository` seeds `LLMRouter`'s `overrides=` at startup from the DB, `provider_settings` added to `Container`
- [x] Unit tests: `test_provider_config_repository.py` (real-sqlite roundtrip, mirrors `test_repository.py`), `test_llm_router.py` additions (`resolve`/`check_configured`/`build_adapter`), `test_provider_settings.py` (validation + persistence + router wiring, fake repository + real in-memory `LLMRouter`) — 70/70 in `tests/unit/ai/`, full suite 496 passed / 2 pre-existing environment failures (`test_health.py` needs a live gateway process, unrelated to this phase), `ruff check src tests` clean

### Phase 10.3 — API — DONE (2026-07-12)
- [x] `routes_settings.py` (5 routes from §7: `GET/PUT/DELETE /ai/settings/tasks[/{task}]`, `POST /ai/settings/providers/{provider}/test`, `GET /ai/settings/providers`), `ai-settings` OpenAPI tag added to `OPENAPI_TAGS` and mounted in `main.py` alongside `ai_router`/`ai_refinement_router`
- [x] Schemas in `ai/api/schemas.py` (`TaskProviderStatusOut`, `SetTaskProviderIn`, `ProviderTestResultOut`, `ProviderInfoOut`, `ProviderPresetModelOut`), every `Field` documented; `GET /providers` serves a static in-file catalog (display copy only, no live/secret state) with the two Hermes Agent presets on the `ollama` entry
- [x] Error mapping: `UnknownTaskError` -> 404, `UnknownProviderError` -> 422; `test_provider` never raises (Phase 10.2's service already traps `LLMProviderNotConfiguredError`/provider errors into `ProviderTestResult(ok=False)`), so the test endpoint always returns 200 — the plan's original "503 mapped from LLMProviderNotConfiguredError" note for that route was superseded by how Phase 10.2 actually implemented `test_provider()`
- [x] `test_routes_settings.py` (14 tests: list/set/clear/test/catalog, 404/422 paths) — 80/80 in `tests/unit/ai/`, full suite 435 passed, `ruff check src tests` clean; verified via `app.openapi()` directly that all 5 routes carry `summary`/`description`/`responses` and every new schema field has a `description`, no untyped `dict`/`object` responses

### Phase 10.4 — Frontend — DONE (2026-07-12)
- [x] `frontend/src/features/settings/` (`ProviderTaskTable.tsx`, `ProviderStatusBadge.tsx`, `ProviderTestButton.tsx`) — one row per task, provider dropdown (4 catalog providers + a client-side-only "Hermes Agent" pseudo-option that maps to `provider=ollama` + a preset model, matched back against the resolved model string per §8), model field that swaps to preset chips for Hermes Agent, status dot, Save/Reset-to-default/Test actions
- [x] `frontend/src/app/settings/page.tsx` — thin shell rendering `ProviderTaskTable`
- [x] Nav link added in `frontend/src/app/page.tsx` next to News
- [x] `client.ts` additions: `api.put` (new, no route had needed PUT before this), `TaskProviderStatus`/`ProviderInfo`/`ProviderTestResult` types, `listTaskProviders`/`setTaskProvider`/`clearTaskProvider`/`testProvider`/`listProviders` — hand-written per plan's note (predates `/ai/settings/*` in codegen), snake_case→camelCase mapped client-side for `ProviderInfo` only (the other 3 response shapes are already flat)
- [x] `pnpm lint` and `pnpm build` clean (pre-existing unrelated warning in `DrawingsList.tsx` untouched by this change); manually verified against the running dev backend/frontend: `/ai/settings/tasks` and `/ai/settings/providers` render correctly (screenshot), a live `PUT`/`GET`/`POST .../test`/`DELETE` round trip against `ten_trade_review` confirmed the override applies and reverts with no backend restart, Save/Reset buttons correctly disabled until a row is actually dirty (verified via DOM dump), no console errors on load

### Phase 10.5 — Docs & cleanup — DONE (2026-07-12)
- [x] `IMPLEMENTATION_PLAN.md` §6.7 rewritten to describe the two-layer (YAML default / DB override) provider selection and the live Settings page; §10.1's file map corrected — `configs/ai.yaml` is restart-only, the DB override is the actual hot-reload path; §12 Phase 10 checklist marked 10.1-10.5 done
- [x] This file's §14 open questions — all four already resolved in prose (see below); no outstanding questions remain
- [x] `configs/ai.yaml` header comment rewritten: describes itself as the git-tracked default layer (restart to change) and explicitly points at the `ai_task_provider_override` DB table as the live override path

---

## 14. Open questions — resolved

All four questions from the original draft are settled:

1. **OpenClaw's real API contract** — proceeding on the OpenAI-compatible
   chat-completions guess (§2.4, §9.4). `OpenClawAdapter` ships in Phase 10.1
   as an explicitly unverified stub, labeled "beta/unverified" in the
   settings UI until confirmed against a real instance.
2. **Default Hermes Agent model** — `hermes3:8b` (§2.2), with `hermes3:70b`
   offered as a secondary quick-pick chip.
3. **Keep raw `claude` alongside `claude_code`?** — yes, keep both (§2.1).
   Justified further by the measured Claude Code CLI overhead (§9.1):
   8,500–11,800 fixed tokens per call make the raw API meaningfully cheaper
   for high-frequency tasks.
4. **Claude Code CLI flags** — verified directly against the installed CLI
   (§9.1): `-p`, `--output-format json` (text in `result`), `--tools ""`
   (not `--allowed-tools`) to fully disable tools, `--strict-mcp-config` +
   no `--mcp-config` for zero MCP tools, `--no-session-persistence`. Do
   **not** use `--system-prompt` — it invalidates the CLI's prompt cache
   rather than reducing overhead (measured: $0.071 vs $0.052 for the same
   trivial call).

No open questions remain. All phases (10.1-10.5) are implemented and shipped
(§13) — this plan is complete. `IMPLEMENTATION_PLAN.md` §6.7/§10.1/§12 and
`configs/ai.yaml`'s header comment now describe the shipped two-layer
(YAML default / DB override) design as current behavior, not a future plan.
