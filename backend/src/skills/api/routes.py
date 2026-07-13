"""Symbol -> strategy routing endpoints (§6.6) — the real "apply a bot to a
symbol" action, distinct from the `strategies` tag's per-family version
activation. See `SkillAssignmentService` for what changes on disk and live.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Path, Request

from src.skills.api.schemas import AssignStrategyIn, NormalSkillOut
from src.skills.application.skill_assignment import (
    SkillAssignmentService,
    UnknownStrategyError,
    UnknownSymbolError,
)

router = APIRouter(prefix="/skills", tags=["skills"])


def _service(request: Request) -> SkillAssignmentService:
    return request.app.state.container.skill_assignment


@router.get(
    "/normal",
    response_model=list[NormalSkillOut],
    summary="List every symbol's current strategy assignment",
    description="One entry per symbol in configs/app.yaml, showing which strategy family is "
    "currently routed to trade it live (§6.6) — the source TradeEngine._try_enter reads to "
    "resolve which strategy to evaluate for a symbol.",
)
async def list_normal_skills(request: Request) -> list[NormalSkillOut]:
    skills = _service(request).list_assignments()
    return [NormalSkillOut.from_domain(s) for s in skills]


@router.put(
    "/normal/{symbol}",
    response_model=NormalSkillOut,
    summary="Apply a strategy to a symbol",
    description=(
        "Reroutes which strategy family trades `symbol` live: writes "
        "skills/normal/<symbol>.yaml with the new `strategy` (keeping the symbol's existing "
        "sessions/risk_multiplier), and hot-swaps the running SkillSelector so the change takes "
        "effect immediately, no restart needed. This is purely the routing decision — it does "
        "not activate or change any StrategyVersion; the target family must already have an "
        "active, non-paused version or the engine will simply find nothing to evaluate."
    ),
    responses={
        404: {"description": "No configs/symbols/<symbol>.yaml for this symbol."},
        422: {
            "description": "strategy_name has no currently active, non-paused StrategyVersion."
        },
    },
)
async def assign_strategy(
    request: Request,
    body: AssignStrategyIn,
    symbol: str = Path(description="Broker symbol, e.g. XAUUSD."),
) -> NormalSkillOut:
    try:
        skill = _service(request).assign(symbol, body.strategy_name)
    except UnknownSymbolError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except UnknownStrategyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return NormalSkillOut.from_domain(skill)
