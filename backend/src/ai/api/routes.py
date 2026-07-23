"""PDF -> StrategySpec -> code endpoints (§8.1, F4).

Every step is human-gated: upload only produces a draft, editing/approving
never generates code, and code generation only ever produces a `validated`
`StrategyVersion` — activating it live is a separate call under the
`strategies` tag (`POST /strategies/versions/{id}/activate`).
"""

from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, Path, UploadFile

from src.ai.api.schemas import (
    CreateDraftFromPromptIn,
    CreateDraftFromSpecIn,
    GeneratedCodeOut,
    StrategyDraftOut,
    UpdateDraftSpecIn,
)
from src.ai.application.llm_router import LLMProviderNotConfiguredError
from src.ai.application.pdf_to_strategy import InvalidDraftStateError, PdfToStrategyService
from src.ai.ports.llm import LLMCallError
from src.shared.api.dependencies import AccountRuntimeDep

router = APIRouter(prefix="/accounts/{account_id}/ai/pdf-strategy", tags=["ai"])

_DRAFT_NOT_FOUND = {404: {"description": "No draft with that id."}}
_DRAFT_STATE_CONFLICT = {
    409: {"description": "The draft's current status doesn't allow this action."}
}
_PROVIDER_NOT_CONFIGURED = {
    503: {
        "description": "The task's configured LLM provider is missing required setup "
        "(e.g. no TB_ANTHROPIC_API_KEY) — an operator needs to fix .env or configs/ai.yaml."
    }
}
_LLM_CALL_FAILED = {
    504: {
        "description": "The configured LLM provider was reachable but the call itself failed "
        "(timeout, non-zero exit, or an error result) — retry, or switch this task to a "
        "different provider on the Settings page."
    }
}


def _service(account: AccountRuntimeDep) -> PdfToStrategyService:
    return account.pdf_to_strategy


@router.post(
    "/upload",
    response_model=StrategyDraftOut,
    summary="Upload a PDF and extract a StrategySpec draft",
    description=(
        "Extracts text from the PDF and runs it through the `pdf_extraction` task's "
        "configured LLM (`configs/ai.yaml`) to produce a `StrategyDraft` — a structured, "
        "human-reviewable spec (symbols, timeframes, indicators, entry/exit rules). This "
        "never generates code and never touches the strategy registry; the spec must be "
        "reviewed, optionally edited (`PATCH .../drafts/{id}`), and approved "
        "(`POST .../drafts/{id}/approve`) before `POST .../drafts/{id}/generate-code` can run. "
        "If `symbol` is given, it overrides the LLM's own symbol guess (which defaults to "
        "XAUUSD whenever the document doesn't name a broker instrument) in `edited_spec`, so "
        "the draft — and the auto-backtest that `generate-code` later runs — is scoped to "
        "whatever symbol was active on the chart when the upload was started."
    ),
    responses={
        400: {"description": "File is not a PDF."},
        **_PROVIDER_NOT_CONFIGURED,
        **_LLM_CALL_FAILED,
    },
)
async def upload_pdf(
    account: AccountRuntimeDep,
    file: UploadFile = File(  # noqa: B008 — FastAPI's documented param-default pattern
        description="A PDF describing a manual trading method."
    ),
    symbol: str | None = Form(  # noqa: B008 — FastAPI's documented param-default pattern
        default=None,
        description="Broker symbol to scope this draft to, e.g. the symbol currently on the "
        "chart. Overrides the LLM's extracted `symbols` guess in `edited_spec`.",
    ),
) -> StrategyDraftOut:
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="file must be a PDF")
    pdf_bytes = await file.read()
    try:
        draft = await _service(account).create_draft_from_pdf(
            file.filename or "upload.pdf", pdf_bytes, symbol=symbol or None
        )
    except LLMProviderNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMCallError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    return StrategyDraftOut.from_domain(draft)


@router.post(
    "/from-prompt",
    response_model=StrategyDraftOut,
    summary="Generate a StrategySpec draft from a typed description, no PDF",
    description=(
        "Runs the trader's own free-text description of a manual trading method through the "
        "same `pdf_extraction` task LLM as PDF upload, producing an identical human-reviewable "
        "`StrategyDraft`. Use this when there's no document to upload — just a description "
        "typed straight in. Never generates code and never touches the strategy registry; the "
        "spec must still be reviewed, optionally edited (`PATCH .../drafts/{id}`), and approved "
        "(`POST .../drafts/{id}/approve`) before `POST .../drafts/{id}/generate-code` can run. "
        "If `symbol` is given, it overrides the LLM's own symbol guess, same as PDF upload."
    ),
    responses={
        **_PROVIDER_NOT_CONFIGURED,
        **_LLM_CALL_FAILED,
    },
)
async def create_draft_from_prompt(
    account: AccountRuntimeDep, body: CreateDraftFromPromptIn
) -> StrategyDraftOut:
    try:
        draft = await _service(account).create_draft_from_text(
            body.description, symbol=body.symbol or None
        )
    except LLMProviderNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMCallError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    return StrategyDraftOut.from_domain(draft)


@router.post(
    "/from-spec",
    response_model=StrategyDraftOut,
    summary="Create a StrategySpec draft directly from structured JSON, no LLM call",
    description=(
        "Skips extraction entirely: `spec` becomes the draft's `extracted_spec` as-is — "
        "use this when the trading method is already available as JSON matching "
        "`ExtractedStrategySpecSchema` (e.g. downloaded from another draft or strategy "
        "version and re-worked). Same human-gated pipeline as PDF/prompt upload: never "
        "generates code and never touches the strategy registry; the draft must still be "
        "reviewed, optionally edited (`PATCH .../drafts/{id}`), and approved "
        "(`POST .../drafts/{id}/approve`) before `POST .../drafts/{id}/generate-code` can "
        "run. If `symbol` is given, it overrides `spec.symbols` in `edited_spec`, same as "
        "PDF upload's `symbol` field."
    ),
)
async def create_draft_from_spec_json(
    account: AccountRuntimeDep, body: CreateDraftFromSpecIn
) -> StrategyDraftOut:
    draft = await _service(account).create_draft_from_spec(
        body.spec.to_domain(), symbol=body.symbol or None
    )
    return StrategyDraftOut.from_domain(draft)


@router.get(
    "/drafts",
    response_model=list[StrategyDraftOut],
    summary="List strategy drafts",
    description="Every PDF-derived draft, newest first, regardless of review status.",
)
async def list_drafts(account: AccountRuntimeDep) -> list[StrategyDraftOut]:
    drafts = await _service(account).list_drafts()
    return [StrategyDraftOut.from_domain(d) for d in drafts]


@router.get(
    "/drafts/{draft_id}",
    response_model=StrategyDraftOut,
    summary="Get a single strategy draft",
    description="Full draft detail for the spec review/edit screen.",
    responses=_DRAFT_NOT_FOUND,
)
async def get_draft(
    account: AccountRuntimeDep,
    draft_id: str = Path(description="Draft id, as returned by POST .../upload."),
) -> StrategyDraftOut:
    draft = await _service(account).get_draft(draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="draft not found")
    return StrategyDraftOut.from_domain(draft)


@router.patch(
    "/drafts/{draft_id}",
    response_model=StrategyDraftOut,
    summary="Edit a draft's extracted spec",
    description=(
        "Replaces the reviewable spec with the user's edits (the original AI extraction is "
        "kept, untouched, for audit). Resets status to pending_review — a previously approved "
        "draft must be re-approved after an edit. Only allowed while pending_review or approved."
    ),
    responses={**_DRAFT_NOT_FOUND, **_DRAFT_STATE_CONFLICT},
)
async def update_draft_spec(
    account: AccountRuntimeDep,
    body: UpdateDraftSpecIn,
    draft_id: str = Path(description="Draft id to edit."),
) -> StrategyDraftOut:
    try:
        draft = await _service(account).update_draft_spec(draft_id, body.edited_spec.to_domain())
    except InvalidDraftStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return StrategyDraftOut.from_domain(draft)


@router.post(
    "/drafts/{draft_id}/approve",
    response_model=StrategyDraftOut,
    summary="Approve a draft's spec",
    description=(
        "Marks the spec as approved by the user — the required gate before "
        "POST .../generate-code will run. Only allowed while pending_review."
    ),
    responses={**_DRAFT_NOT_FOUND, **_DRAFT_STATE_CONFLICT},
)
async def approve_draft(
    account: AccountRuntimeDep, draft_id: str = Path(description="Draft id to approve.")
) -> StrategyDraftOut:
    try:
        draft = await _service(account).approve_draft(draft_id)
    except InvalidDraftStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return StrategyDraftOut.from_domain(draft)


@router.post(
    "/drafts/{draft_id}/reject",
    response_model=StrategyDraftOut,
    summary="Reject a draft",
    description="Marks the draft rejected — it is kept for the record but can no longer "
    "be approved or generate code.",
    responses=_DRAFT_NOT_FOUND,
)
async def reject_draft(
    account: AccountRuntimeDep, draft_id: str = Path(description="Draft id to reject.")
) -> StrategyDraftOut:
    try:
        draft = await _service(account).reject_draft(draft_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return StrategyDraftOut.from_domain(draft)


@router.post(
    "/drafts/{draft_id}/generate-code",
    response_model=GeneratedCodeOut,
    summary="Generate strategy code from an approved draft",
    description=(
        "Runs the `code_generation` task's configured LLM against the draft's approved spec, "
        "then validates the result in the strategy sandbox (import whitelist, AST scan, a "
        "smoke-test `evaluate()` call). If it passes, writes a new file under "
        "`strategies/generated/`, records a `StrategyVersion` with status 'validated' (never "
        "'active' — see the `strategies` tag), and attempts an automatic backtest. If the "
        "candle history needed for that backtest hasn't been downloaded yet, `backtest_report_id` "
        "comes back null rather than failing the whole request. Only allowed once the draft "
        "is approved."
    ),
    responses={
        **_DRAFT_NOT_FOUND,
        **_DRAFT_STATE_CONFLICT,
        **_PROVIDER_NOT_CONFIGURED,
        **_LLM_CALL_FAILED,
    },
)
async def generate_code(
    account: AccountRuntimeDep, draft_id: str = Path(description="Draft id, must be approved.")
) -> GeneratedCodeOut:
    try:
        result = await _service(account).generate_code(draft_id)
    except InvalidDraftStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LLMProviderNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMCallError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return GeneratedCodeOut.from_domain(result)
