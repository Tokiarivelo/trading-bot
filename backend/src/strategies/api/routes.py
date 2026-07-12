"""Strategy version listing and activation endpoints (§6.5, §8.1).

Activation is the only user-triggered action here, and it doubles as
rollback: activating an older version id reactivates that exact file and
archives whatever was active — nothing is ever edited in place.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Path, Query, Request

from src.strategies.api.schemas import (
    DuplicateVersionRequest,
    RenameVersionRequest,
    StrategyVersionDetailOut,
    StrategyVersionOut,
)
from src.strategies.application.versioning import (
    StrategyNameConflictError,
    StrategyValidationError,
    StrategyVersionService,
)
from src.strategies.domain.versioning import VersionStatus

router = APIRouter(prefix="/strategies", tags=["strategies"])

_VERSION_NOT_FOUND = {404: {"description": "No strategy version with that id."}}

# Module-level singleton, not a call in the argument default — ruff's B008
# check doesn't special-case `Query()` for non-primitive annotations
# (VersionStatus is a StrEnum) the way it does for str/int/Literal.
_STATUS_QUERY = Query(
    default=None, description="Restrict to this lifecycle stage: validated, active, archived."
)


def _service(request: Request) -> StrategyVersionService:
    return request.app.state.container.strategy_versions


@router.get(
    "/versions",
    response_model=list[StrategyVersionOut],
    summary="List strategy versions",
    description="Every recorded strategy version, newest first per name. Filter to one "
    "strategy family with `name`, or to one lifecycle stage with `status` (e.g. `status=active` "
    "to fetch only what's currently live, without pulling every historical version).",
)
async def list_versions(
    request: Request,
    name: str | None = Query(default=None, description="Restrict to this strategy family name."),
    status: VersionStatus | None = _STATUS_QUERY,
) -> list[StrategyVersionOut]:
    versions = _service(request).list_versions(name, status)
    return [StrategyVersionOut.from_domain(v) for v in versions]


@router.get(
    "/versions/{version_id}",
    response_model=StrategyVersionDetailOut,
    summary="Get a single strategy version, including its source code",
    description="Full version detail for the version diff/detail screen — same fields as "
    "GET /strategies/versions plus the generated Python source.",
    responses=_VERSION_NOT_FOUND,
)
async def get_version(
    request: Request,
    version_id: str = Path(description="Version id, as returned by GET /strategies/versions."),
) -> StrategyVersionDetailOut:
    service = _service(request)
    version = service.get_version(version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="strategy version not found")
    code = service.get_code(version)
    return StrategyVersionDetailOut.from_domain_with_code(version, code)


@router.post(
    "/versions/{version_id}/activate",
    response_model=StrategyVersionOut,
    summary="Activate a strategy version",
    description=(
        "Re-validates the file on disk in the sandbox, registers it live in the "
        "StrategyRegistry, and archives whichever version of the same strategy name was "
        "previously active. This is also how rollback works: activate an older version id "
        "to bring it back. Does not change configs/app.yaml's paper/live mode — this only "
        "selects which strategy code the engine runs, never real-money risk settings."
    ),
    responses={
        **_VERSION_NOT_FOUND,
        422: {"description": "The version's file no longer passes sandbox validation."},
    },
)
async def activate_version(
    request: Request,
    version_id: str = Path(description="Version id to activate (or reactivate, for rollback)."),
) -> StrategyVersionOut:
    service = _service(request)
    try:
        version = service.activate_version(version_id)
    except StrategyValidationError as exc:
        raise HTTPException(status_code=422, detail="; ".join(exc.errors)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return StrategyVersionOut.from_domain(version)


@router.post(
    "/versions/{version_id}/duplicate",
    response_model=StrategyVersionOut,
    summary="Duplicate a strategy version into a new strategy family",
    description=(
        "Clones this version's generated code and spec snapshot into a brand-new "
        "strategy family — new name, version 1, no parent — a fork for retargeting "
        "(e.g. same logic, different symbol), not a supersession of the original. "
        "Optionally pass `symbols` to also retarget the clone to different symbols; "
        "this rewrites the `StrategySpec(symbols=...)` literal in the generated source "
        "and re-validates it in the sandbox before saving. Never edits configs/app.yaml — "
        "the engine won't trade the new symbol live until a human adds it there."
    ),
    responses={
        **_VERSION_NOT_FOUND,
        409: {
            "description": "The requested new name is already in use by another strategy family."
        },
        422: {
            "description": "The clone (with the symbols override applied, if any) failed "
            "sandbox validation, or no `symbols=(...)` literal could be found to rewrite."
        },
    },
)
async def duplicate_version(
    request: Request,
    body: DuplicateVersionRequest,
    version_id: str = Path(description="Version id to duplicate."),
) -> StrategyVersionOut:
    service = _service(request)
    try:
        duplicated = service.duplicate_version(
            version_id,
            new_name=body.name,
            symbols=tuple(body.symbols) if body.symbols else None,
        )
    except StrategyNameConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except StrategyValidationError as exc:
        raise HTTPException(status_code=422, detail="; ".join(exc.errors)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return StrategyVersionOut.from_domain(duplicated)


@router.patch(
    "/versions/{version_id}/rename",
    response_model=StrategyVersionOut,
    summary="Rename a strategy family",
    description=(
        "Renames the display name shared by every version of this strategy family "
        "(not just this one) — updates the stored records only, never the generated "
        "file's on-disk name or contents."
    ),
    responses={
        **_VERSION_NOT_FOUND,
        409: {
            "description": "The requested new name is already in use by another strategy family."
        },
    },
)
async def rename_version(
    request: Request,
    body: RenameVersionRequest,
    version_id: str = Path(description="Any version id belonging to the family to rename."),
) -> StrategyVersionOut:
    service = _service(request)
    try:
        renamed = service.rename_family(version_id, body.name)
    except StrategyNameConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return StrategyVersionOut.from_domain(renamed)
