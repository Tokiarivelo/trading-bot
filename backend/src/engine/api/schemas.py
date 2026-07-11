"""Wire schema for the `/engine` HTTP API. Mirrors `engine/domain/models.EngineStatus`."""

from __future__ import annotations

from pydantic import BaseModel, Field


class EngineStatusOut(BaseModel):
    """Current state of the automated trade loop and its circuit breakers."""

    enabled: bool = Field(description="Whether the engine is configured to trade at all.")
    paused: bool = Field(
        description="True after the kill switch or a circuit breaker has fired; no new entries "
        "are taken while paused."
    )
    pause_reason: str = Field(
        default="", description="Why `paused` is true; empty when not paused."
    )
    consecutive_losses: int = Field(
        default=0, description="Current consecutive-loss streak, reset on any win."
    )
    trades_today: int = Field(
        default=0, description="Trades opened since the start of the trading day."
    )
    daily_pnl: float = Field(default=0.0, description="Realized P/L for the current trading day.")
