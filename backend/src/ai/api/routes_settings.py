"""Per-task AI provider selection endpoints (AI_PROVIDER_SETTINGS_PLAN.md §7,
Phase 10.3).

Read-mostly: the only writes are `PUT`/`DELETE` on a task's override, both of
which go through `ProviderSettingsService` so the DB write and the live
`LLMRouter` override happen together — the change is visible to the very
next `for_task(...)` call, no backend restart required (plan §10).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Path, Request

from src.ai.api.schemas import (
    ProviderInfoOut,
    ProviderKeyIn,
    ProviderPresetModelOut,
    ProviderTestIn,
    ProviderTestResultOut,
    SetTaskProviderIn,
    TaskProviderStatusOut,
)
from src.ai.application.provider_settings import (
    ProviderSettingsService,
    UnknownProviderError,
    UnknownTaskError,
)

router = APIRouter(prefix="/ai/settings", tags=["ai-settings"])

_TASK_NOT_FOUND = {404: {"description": "Not one of the 4 known AI tasks."}}
_PROVIDER_UNKNOWN = {422: {"description": "Not one of the 10 known providers."}}
_DEFAULT_TEST_BODY = ProviderTestIn()

#: Static display copy + curated model presets for `GET /ai/settings/providers`
#: — `configured` (live, per-request) is merged in at request time by
#: `_catalog_with_status`, never baked into this constant. Preset lists are a
#: maintained snapshot, not a live model-list call, so an operator can always
#: type a newer model id by hand instead of picking a preset.
_PROVIDER_CATALOG = [
    ProviderInfoOut(
        id="claude",
        label="Claude (API)",
        description="Direct Anthropic API. Cheapest/fastest option — the right default for "
        "high-frequency tasks like ten_trade_review.",
        needs_secret=True,
        configured=False,
        preset_models=[
            ProviderPresetModelOut(label="Claude Sonnet 5", model="claude-sonnet-5"),
            ProviderPresetModelOut(label="Claude Opus 4.8", model="claude-opus-4-8"),
            ProviderPresetModelOut(label="Claude Haiku 4.5", model="claude-haiku-4-5"),
            ProviderPresetModelOut(label="Claude Fable 5", model="claude-fable-5"),
        ],
    ),
    ProviderInfoOut(
        id="openai",
        label="OpenAI",
        description="Direct OpenAI API (GPT-5.6 generation) — needs an OpenAI platform API key.",
        needs_secret=True,
        configured=False,
        preset_models=[
            ProviderPresetModelOut(
                label="GPT-5.6 Sol (flagship reasoning/coding)", model="gpt-5.6-sol"
            ),
            ProviderPresetModelOut(label="GPT-5.6 Terra (balanced)", model="gpt-5.6-terra"),
            ProviderPresetModelOut(label="GPT-5.6 Luna (cost-sensitive)", model="gpt-5.6-luna"),
            ProviderPresetModelOut(label="GPT-4o mini (legacy, cheap)", model="gpt-4o-mini"),
        ],
    ),
    ProviderInfoOut(
        id="gemini",
        label="Google Gemini",
        description="Google's Generative Language API — needs a Gemini API key from AI Studio "
        "or a Google Cloud project.",
        needs_secret=True,
        configured=False,
        preset_models=[
            ProviderPresetModelOut(label="Gemini 3.5 Flash (GA)", model="gemini-3.5-flash"),
            ProviderPresetModelOut(
                label="Gemini 3.1 Pro (preview)", model="gemini-3.1-pro-preview"
            ),
            ProviderPresetModelOut(label="Gemini 3.1 Flash-Lite", model="gemini-3.1-flash-lite"),
        ],
    ),
    ProviderInfoOut(
        id="mistral",
        label="Mistral AI",
        description="Mistral's La Plateforme API — needs a Mistral API key.",
        needs_secret=True,
        configured=False,
        preset_models=[
            ProviderPresetModelOut(label="Mistral Large (latest)", model="mistral-large-latest"),
            ProviderPresetModelOut(label="Mistral Medium (latest)", model="mistral-medium-latest"),
            ProviderPresetModelOut(label="Mistral Small (latest)", model="mistral-small-latest"),
            ProviderPresetModelOut(
                label="Magistral Medium (reasoning)", model="magistral-medium-latest"
            ),
        ],
    ),
    ProviderInfoOut(
        id="groq",
        label="Groq",
        description="Groq's low-latency inference API for open-weight models — needs a Groq "
        "API key.",
        needs_secret=True,
        configured=False,
        preset_models=[
            ProviderPresetModelOut(label="GPT-OSS 120B", model="openai/gpt-oss-120b"),
            ProviderPresetModelOut(label="GPT-OSS 20B", model="openai/gpt-oss-20b"),
            ProviderPresetModelOut(label="Kimi K2", model="moonshotai/kimi-k2-instruct-0905"),
        ],
    ),
    ProviderInfoOut(
        id="deepseek",
        label="DeepSeek",
        description="Direct DeepSeek API — needs a DeepSeek platform API key.",
        needs_secret=True,
        configured=False,
        preset_models=[
            ProviderPresetModelOut(label="DeepSeek V4 Flash (chat)", model="deepseek-v4-flash"),
            ProviderPresetModelOut(label="DeepSeek V4 Pro (reasoning)", model="deepseek-v4-pro"),
        ],
    ),
    ProviderInfoOut(
        id="xai",
        label="xAI (Grok)",
        description="Direct xAI API — needs a Grok API key from the xAI console.",
        needs_secret=True,
        configured=False,
        preset_models=[
            ProviderPresetModelOut(label="Grok 4.5", model="grok-4.5"),
            ProviderPresetModelOut(label="Grok 4.3", model="grok-4.3"),
        ],
    ),
    ProviderInfoOut(
        id="claude_code",
        label="Claude Code",
        description="Headless Claude Code CLI, billed through your Claude Code subscription "
        "instead of metered API usage. Carries ~8.5k-11.8k tokens of fixed per-call overhead — "
        "best for occasional, high-context tasks, not frequent ones.",
        needs_secret=False,
        configured=False,
        preset_models=[
            ProviderPresetModelOut(label="Sonnet", model="sonnet"),
            ProviderPresetModelOut(label="Opus", model="opus"),
            ProviderPresetModelOut(label="Haiku", model="haiku"),
        ],
    ),
    ProviderInfoOut(
        id="ollama",
        label="Ollama",
        description="Any locally pulled Ollama model. 'Hermes Agent' below is a curated "
        "Nous-Hermes preset on this same provider, not a separate one.",
        needs_secret=False,
        configured=False,
        preset_models=[
            ProviderPresetModelOut(label="Hermes Agent (8b, default)", model="hermes3:8b"),
            ProviderPresetModelOut(label="Hermes Agent (70b)", model="hermes3:70b"),
        ],
    ),
    ProviderInfoOut(
        id="openclaw",
        label="OpenClaw",
        description="Beta / unverified — the wire contract is an assumed OpenAI-compatible "
        "chat-completions endpoint pending confirmation against a real OpenClaw instance.",
        needs_secret=True,
        configured=False,
    ),
]


def _catalog_with_status(service: ProviderSettingsService) -> list[ProviderInfoOut]:
    configured_map = service.provider_configured_map()
    return [
        entry.model_copy(update={"configured": configured_map.get(entry.id, False)})
        for entry in _PROVIDER_CATALOG
    ]


def _service(request: Request) -> ProviderSettingsService:
    return request.app.state.container.provider_settings


@router.get(
    "/tasks",
    response_model=list[TaskProviderStatusOut],
    summary="List effective AI provider per task",
    description=(
        "The 4 AI tasks (pdf_extraction, code_generation, ten_trade_review, code_refinement) "
        "with each one's current effective provider/model — a settings-page override if one is "
        "set, else the configs/ai.yaml default — plus whether that provider is usable right now "
        "without revealing any secret value."
    ),
)
async def list_tasks(request: Request) -> list[TaskProviderStatusOut]:
    statuses = _service(request).list_tasks()
    return [TaskProviderStatusOut.from_domain(s) for s in statuses]


@router.put(
    "/tasks/{task}",
    response_model=TaskProviderStatusOut,
    summary="Set a task's AI provider override",
    description=(
        "Pins `task` to `{provider, model}`, persisted so it survives a restart, and applied "
        "immediately — the very next call for this task builds a fresh adapter, no backend "
        "restart needed. Picking 'Hermes Agent' in the UI means sending "
        '`{provider: "ollama", model: "hermes3:8b"}` (or hermes3:70b); there is no separate '
        "hermes provider id."
    ),
    responses={**_TASK_NOT_FOUND, **_PROVIDER_UNKNOWN},
)
async def set_task_provider(
    request: Request,
    body: SetTaskProviderIn,
    task: str = Path(description="Task id, e.g. ten_trade_review."),
) -> TaskProviderStatusOut:
    try:
        status = _service(request).set_task_provider(task, body.provider, body.model)
    except UnknownTaskError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except UnknownProviderError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return TaskProviderStatusOut.from_domain(status)


@router.delete(
    "/tasks/{task}",
    response_model=TaskProviderStatusOut,
    summary="Clear a task's AI provider override",
    description="Removes the settings-page override, if any, so `task` reverts to its "
    "configs/ai.yaml default on the very next call.",
    responses=_TASK_NOT_FOUND,
)
async def clear_task_provider(
    request: Request, task: str = Path(description="Task id to revert to its YAML default.")
) -> TaskProviderStatusOut:
    try:
        status = _service(request).clear_task_provider(task)
    except (UnknownTaskError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return TaskProviderStatusOut.from_domain(status)


@router.post(
    "/providers/{provider}/test",
    response_model=ProviderTestResultOut,
    summary="Test connectivity for one provider",
    description=(
        "Runs a throwaway completion against `provider` using a fixed cheap model, independent "
        "of any task. With no body (or an empty/null `message`), sends a fixed one-token "
        "connectivity probe. With a `message` in the body (e.g. 'hello'), sends that instead and "
        "returns the provider's actual reply in `reply` — a real round-trip test, not just "
        "connectivity. Never raises for a failure — a missing secret, unreachable URL, or CLI "
        "error comes back as a normal 200 with `ok: false` and a `message`, so the settings page "
        "can render pass/fail inline."
    ),
    responses=_PROVIDER_UNKNOWN,
)
async def test_provider(
    request: Request,
    provider: str = Path(description="Provider id, one of KNOWN_PROVIDERS."),
    body: ProviderTestIn = _DEFAULT_TEST_BODY,
) -> ProviderTestResultOut:
    try:
        result = await _service(request).test_provider(provider, body.message)
    except UnknownProviderError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ProviderTestResultOut.from_domain(result)


@router.get(
    "/providers",
    response_model=list[ProviderInfoOut],
    summary="List the known AI providers",
    description="Catalog of the 10 providers the settings page offers — display name, "
    "explanation, whether it needs an API key, curated quick-pick model presets, and whether "
    "it's usable right now (checked live per request, never revealing the secret itself).",
)
async def list_providers(request: Request) -> list[ProviderInfoOut]:
    return _catalog_with_status(_service(request))


@router.put(
    "/providers/{provider}/key",
    response_model=ProviderInfoOut,
    summary="Set a provider's API key",
    description=(
        "Saves `provider`'s API key, Fernet-encrypted at rest with the encryption key held in "
        "the OS keyring — the key value is never returned by this or any other endpoint. Takes "
        "precedence over that provider's `.env` fallback immediately, no backend restart "
        "needed. Not valid for 'ollama' (local server URL only, set via TB_OLLAMA_URL) or "
        "'claude_code' (local CLI binary, no key)."
    ),
    responses=_PROVIDER_UNKNOWN,
)
async def set_provider_key(
    request: Request,
    body: ProviderKeyIn,
    provider: str = Path(description="Provider id, one of KNOWN_PROVIDERS."),
) -> ProviderInfoOut:
    try:
        _service(request).set_provider_key(provider, body.api_key)
    except UnknownProviderError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return next(p for p in _catalog_with_status(_service(request)) if p.id == provider)


@router.delete(
    "/providers/{provider}/key",
    response_model=ProviderInfoOut,
    summary="Clear a provider's saved API key",
    description="Removes the settings-page key for `provider`, if any, so it reverts to its "
    "`.env` fallback (or 'not configured' if that's empty too) on the very next call.",
    responses=_PROVIDER_UNKNOWN,
)
async def clear_provider_key(
    request: Request, provider: str = Path(description="Provider id, one of KNOWN_PROVIDERS.")
) -> ProviderInfoOut:
    try:
        _service(request).clear_provider_key(provider)
    except UnknownProviderError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return next(p for p in _catalog_with_status(_service(request)) if p.id == provider)
