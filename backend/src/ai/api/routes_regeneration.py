"""User-triggered AI code regeneration endpoint (§6.5 code editor).

Distinct from `ai/api/routes.py` (PDF-derived first code) and
`ai/api/routes_refinement.py` (automated, trade-review-driven proposals):
this is a human typing free-form change instructions against a version
they're already looking at. Always produces a 'validated' strategy version,
never active — see the `strategies` tag for activation, and
`POST /strategies/versions/{id}/edit` for the manual-code-editor
counterpart.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Path, Request

from src.ai.api.schemas import RegenerateCodeIn, RegeneratedCodeOut
from src.ai.application.code_regeneration import CodeRegenerationService
from src.ai.application.llm_router import LLMProviderNotConfiguredError
from src.ai.ports.llm import LLMCallError
from src.strategies.application.versioning import StrategyNameConflictError

router = APIRouter(prefix="/ai/strategies", tags=["ai"])

_VERSION_NOT_FOUND = {404: {"description": "No strategy version with that id."}}
_NAME_CONFLICT = {409: {"description": "`new_name` is already in use by another strategy family."}}
_PROVIDER_NOT_CONFIGURED = {
    503: {
        "description": "The 'code_generation' task's configured LLM provider (shared with the "
        "PDF-to-code pipeline — see the `ai-settings` tag) is missing required setup (e.g. no "
        "TB_ANTHROPIC_API_KEY) — an operator needs to fix .env or configs/ai.yaml."
    }
}
_LLM_CALL_FAILED = {
    504: {
        "description": "The configured LLM provider was reachable but the call itself failed "
        "(timeout, non-zero exit, or an error result) — retry, or switch this task to a "
        "different provider on the Settings page."
    }
}


def _service(request: Request) -> CodeRegenerationService:
    return request.app.state.container.code_regeneration


@router.post(
    "/versions/{version_id}/regenerate",
    response_model=RegeneratedCodeOut,
    summary="Regenerate a strategy version's code with AI, from free-form instructions",
    description=(
        "Runs the `code_generation` task's configured LLM (`configs/ai.yaml` — the same "
        "provider setting the PDF-to-code pipeline uses, so there's one 'strategy code' "
        "provider to manage, not a second one to remember) against this version's code and "
        "spec snapshot — or, if `spec` is given, that edited spec instead, "
        "letting the trader tweak symbols/timeframes/entry-exit rules before regenerating — "
        "plus the trader's free-form instructions (e.g. 'only trade during the London "
        "session'), then validates the result in the strategy sandbox. If it passes, writes a "
        "new file under `strategies/generated/` and records a new `StrategyVersion` with "
        "status 'validated', never 'active'. By default the new version increments this "
        "version's own strategy family, parented on it explicitly; pass `new_name` to fork "
        "the result into a brand-new family at version 1 instead (the 'duplicate' save "
        "destination, for trying a change without touching the original). Activating the "
        "result (or rolling back) is a separate call, "
        "`POST /strategies/versions/{new_version_id}/activate`. For a direct hand-edit instead "
        "of an AI rewrite, use `POST /strategies/versions/{version_id}/edit`."
    ),
    responses={
        **_VERSION_NOT_FOUND,
        **_NAME_CONFLICT,
        **_PROVIDER_NOT_CONFIGURED,
        **_LLM_CALL_FAILED,
    },
)
async def regenerate_version_code(
    request: Request,
    body: RegenerateCodeIn,
    version_id: str = Path(description="Version id to regenerate from."),
) -> RegeneratedCodeOut:
    spec = body.spec.to_domain().to_dict() if body.spec is not None else None
    try:
        result = await _service(request).regenerate(
            version_id, body.instructions, spec=spec, new_name=body.new_name
        )
    except StrategyNameConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LLMProviderNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMCallError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RegeneratedCodeOut.from_domain(result)
