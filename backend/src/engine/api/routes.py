"""Engine control endpoints: status + the manual kill switch (§11)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Request

from src.engine.api.schemas import EngineStatusOut, RiskCapsOut, UpdateMinLotFallbackIn

router = APIRouter(prefix="/engine", tags=["engine"])


def _engine(request: Request) -> Any:
    return request.app.state.container.trade_engine


def _risk_manager(request: Request) -> Any:
    return request.app.state.container.risk_manager


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


@router.get(
    "/risk-caps",
    response_model=RiskCapsOut,
    summary="Get the live engine's current risk caps",
    description=(
        "Returns every risk cap the running `RiskManager` is enforcing right now. "
        "Matches `configs/risk.yaml` on disk unless `PUT /engine/risk-caps/min-lot-fallback` "
        "has been called since the last backend restart, in which case those two fields "
        "reflect the live override instead."
    ),
)
async def get_risk_caps(request: Request) -> RiskCapsOut:
    return RiskCapsOut(**asdict(_risk_manager(request).caps))


@router.put(
    "/risk-caps/min-lot-fallback",
    response_model=RiskCapsOut,
    summary="Enable/configure the broker-minimum-lot sizing fallback, live",
    description=(
        "Updates, on the running engine, whether a balance too small for "
        "risk_per_trade_pct to reach the broker's minimum lot trades that minimum lot "
        "anyway (and the risk ceiling that gates it) — see `RiskManager.size_position`. "
        "Takes effect on the very next sizing decision for live/paper trading. Only these "
        "two fields change; every other risk cap is untouched. **Not persisted** — a "
        "backend restart reverts to `configs/risk.yaml`, which the human edits directly "
        "to change the default (see CLAUDE.md: risk caps are user-owned)."
    ),
)
async def update_min_lot_fallback(body: UpdateMinLotFallbackIn, request: Request) -> RiskCapsOut:
    _risk_manager(request).set_min_lot_fallback(
        enabled=body.enabled, max_risk_per_trade_pct=body.max_risk_per_trade_pct
    )
    return RiskCapsOut(**asdict(_risk_manager(request).caps))
