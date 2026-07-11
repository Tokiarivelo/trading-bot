"""Strategy version listing and activation endpoints (§6.5, §8.1).

Activation is the only user-triggered action here, and it doubles as
rollback: activating an older version id reactivates that exact file and
archives whatever was active — nothing is ever edited in place.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Path, Query, Request

from src.strategies.api.schemas import StrategyVersionDetailOut, StrategyVersionOut
from src.strategies.application.versioning import StrategyValidationError, StrategyVersionService

router = APIRouter(prefix="/strategies", tags=["strategies"])

_VERSION_NOT_FOUND = {404: {"description": "No strategy version with that id."}}


def _service(request: Request) -> StrategyVersionService:
    return request.app.state.container.strategy_versions


@router.get(
    "/versions",
    response_model=list[StrategyVersionOut],
    summary="List strategy versions",
    description="Every recorded strategy version, newest first per name. Filter to one "
    "strategy family with `name`.",
)
async def list_versions(
    request: Request,
    name: str | None = Query(default=None, description="Restrict to this strategy family name."),
) -> list[StrategyVersionOut]:
    versions = _service(request).list_versions(name)
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
