"""Custom indicator CRUD + on-demand computation endpoints.

Indicators are user/AI-written Python computed server-side in a sandbox
(`indicators/sandbox.py`) — independent of the chart's built-in, client-side
indicators (EMA/SMA/RSI/...). See `IndicatorService` for the no-versioning
edit-in-place rationale: indicators never trade, so there's no rollback
story to preserve.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Path, Request

from src.indicators.api.schemas import (
    ComputeIndicatorRequest,
    ComputeIndicatorResponseOut,
    CreateIndicatorRequest,
    DuplicateIndicatorRequest,
    EditIndicatorRequest,
    IndicatorDetailOut,
    IndicatorOut,
    PreviewIndicatorRequest,
)
from src.indicators.application.service import (
    IndicatorNameConflictError,
    IndicatorService,
    IndicatorValidationError,
)

router = APIRouter(prefix="/indicators", tags=["indicators"])

_INDICATOR_NOT_FOUND = {404: {"description": "No indicator with that id."}}


def _service(request: Request) -> IndicatorService:
    return request.app.state.container.indicators


@router.get(
    "",
    response_model=list[IndicatorOut],
    summary="List custom indicators",
    description="Every saved custom indicator, alphabetical by name. Does not include source "
    "code — fetch GET /indicators/{id} for that.",
)
async def list_indicators(request: Request) -> list[IndicatorOut]:
    return [IndicatorOut.from_domain(d) for d in _service(request).list_all()]


@router.get(
    "/{indicator_id}",
    response_model=IndicatorDetailOut,
    summary="Get a single indicator, including its source code",
    description="Full indicator detail for the chart's code-peek panel and the /indicators "
    "management page — same fields as GET /indicators plus the Python source.",
    responses=_INDICATOR_NOT_FOUND,
)
async def get_indicator(
    request: Request,
    indicator_id: str = Path(description="Indicator id, as returned by GET /indicators."),
) -> IndicatorDetailOut:
    definition = _service(request).get(indicator_id)
    if definition is None:
        raise HTTPException(status_code=404, detail="indicator not found")
    return IndicatorDetailOut.from_domain(definition)


@router.post(
    "",
    response_model=IndicatorDetailOut,
    summary="Create a custom indicator",
    description="Sandbox-validates `code` (imports limited to math/statistics/numpy/pandas; "
    "no I/O, no network) and, if it passes, saves a new indicator that immediately shows up "
    "in the chart's indicator picker.",
    responses={
        409: {"description": "`name` is already in use by another indicator."},
        422: {"description": "The code failed sandbox validation (import whitelist, AST "
              "scan, or the smoke-test compute() call)."},
    },
)
async def create_indicator(
    request: Request, body: CreateIndicatorRequest
) -> IndicatorDetailOut:
    service = _service(request)
    try:
        created = service.create(
            name=body.name, code=body.code, default_params=body.default_params
        )
    except IndicatorNameConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IndicatorValidationError as exc:
        raise HTTPException(status_code=422, detail="; ".join(exc.errors)) from exc
    return IndicatorDetailOut.from_domain(created)


@router.post(
    "/{indicator_id}/edit",
    response_model=IndicatorDetailOut,
    summary="Edit an indicator's code in place",
    description="Re-validates `code` in the sandbox and, if it passes, updates this "
    "indicator's row directly — unlike strategy versions there is no new-version/rollback "
    "step, since indicators never trade live. Every chart currently using this indicator "
    "picks up the new code on its next compute.",
    responses={
        **_INDICATOR_NOT_FOUND,
        422: {"description": "The edited code failed sandbox validation."},
    },
)
async def edit_indicator(
    request: Request,
    body: EditIndicatorRequest,
    indicator_id: str = Path(description="Indicator id whose code is being edited."),
) -> IndicatorDetailOut:
    service = _service(request)
    try:
        edited = service.edit(
            indicator_id, body.code, default_params=body.default_params
        )
    except IndicatorValidationError as exc:
        raise HTTPException(status_code=422, detail="; ".join(exc.errors)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return IndicatorDetailOut.from_domain(edited)


@router.post(
    "/{indicator_id}/duplicate",
    response_model=IndicatorDetailOut,
    summary="Duplicate an indicator under a new name",
    description="Clones this indicator's code and default params into a brand-new indicator "
    "row — a starting point for a variant, not a version of the original.",
    responses={
        **_INDICATOR_NOT_FOUND,
        409: {"description": "`name` is already in use by another indicator."},
    },
)
async def duplicate_indicator(
    request: Request,
    body: DuplicateIndicatorRequest,
    indicator_id: str = Path(description="Indicator id to duplicate."),
) -> IndicatorDetailOut:
    service = _service(request)
    try:
        duplicated = service.duplicate(indicator_id, new_name=body.name)
    except IndicatorNameConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return IndicatorDetailOut.from_domain(duplicated)


@router.delete(
    "/{indicator_id}",
    status_code=204,
    summary="Delete an indicator",
    description="Hard-deletes this indicator's row. Any chart with it currently added will "
    "simply stop getting new computed values for it — this cannot be undone.",
    responses=_INDICATOR_NOT_FOUND,
)
async def delete_indicator(
    request: Request,
    indicator_id: str = Path(description="Indicator id to delete."),
) -> None:
    service = _service(request)
    try:
        service.delete(indicator_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/{indicator_id}/compute",
    response_model=ComputeIndicatorResponseOut,
    summary="Compute a saved indicator against real candle history",
    description="Loads this indicator's code, re-validates it in the sandbox, runs compute() "
    "over the requested symbol/timeframe/period, and returns the resulting series for the "
    "chart to plot. Sandbox failures, missing candle history, or a runtime exception in "
    "compute() are reported in the response body's `error` field rather than an HTTP error, "
    "so the chart can show a clear message instead of losing the whole request.",
    responses=_INDICATOR_NOT_FOUND,
)
async def compute_indicator(
    request: Request,
    body: ComputeIndicatorRequest,
    indicator_id: str = Path(description="Indicator id to compute."),
) -> ComputeIndicatorResponseOut:
    service = _service(request)
    try:
        result = service.compute(
            indicator_id,
            symbol=body.symbol,
            timeframe=body.timeframe,
            period=body.period,
            params=body.params,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ComputeIndicatorResponseOut.from_result(result)


@router.post(
    "/preview",
    response_model=ComputeIndicatorResponseOut,
    summary="Preview ad-hoc indicator code against real candle history",
    description="Same as POST /indicators/{id}/compute, but for code that hasn't been saved "
    "yet — nothing is persisted. Used by the create/edit UI's Preview button so a trader can "
    "see an indicator's output before committing it.",
)
async def preview_indicator(
    request: Request, body: PreviewIndicatorRequest
) -> ComputeIndicatorResponseOut:
    service = _service(request)
    result = service.preview(
        body.code,
        symbol=body.symbol,
        timeframe=body.timeframe,
        period=body.period,
        params=body.params,
    )
    return ComputeIndicatorResponseOut.from_result(result)
