"""Engine control endpoints: status + the manual kill switch (§11)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Request

from src.engine.api.schemas import EngineStatusOut

router = APIRouter(prefix="/engine", tags=["engine"])


def _engine(request: Request) -> Any:
    return request.app.state.container.trade_engine


@router.get(
    "/status",
    response_model=EngineStatusOut,
    summary="Get automated trading engine status",
    description=(
        "Reports whether the engine is enabled/paused and its circuit-breaker "
        "counters (consecutive losses, trades and P/L for the current day). "
        "Polled by the UI's bot-control panel."
    ),
)
async def get_status(request: Request) -> EngineStatusOut:
    return EngineStatusOut(**asdict(_engine(request).status))


@router.post(
    "/kill",
    response_model=EngineStatusOut,
    summary="Kill switch: close all positions and pause the engine",
    description=(
        "Immediately closes every open position and pauses the engine so no new "
        "entries are taken. This is the manual emergency stop — call `/resume` to "
        "re-enable trading afterwards. Individual close failures are logged and "
        "skipped rather than aborting the sweep."
    ),
)
async def kill_switch(request: Request) -> EngineStatusOut:
    await _engine(request).kill_switch()
    return EngineStatusOut(**asdict(_engine(request).status))


@router.post(
    "/resume",
    response_model=EngineStatusOut,
    summary="Resume trading after a pause",
    description=(
        "Clears the paused state set by the kill switch or a circuit breaker. "
        "Does not reopen any positions — it only allows the engine to take new "
        "entries again on the next candle close."
    ),
)
async def resume(request: Request) -> EngineStatusOut:
    _engine(request).resume()
    return EngineStatusOut(**asdict(_engine(request).status))
