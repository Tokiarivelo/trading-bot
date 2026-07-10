"""Market data REST + WS endpoints (chart + tooling)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from src.market_data.application.candle_stream import candle_message
from src.market_data.domain.models import MarketDataUnavailable, Timeframe

router = APIRouter(prefix="/market-data", tags=["market-data"])

TimeframeParam = Annotated[Timeframe, Query()]


def _container(request: Request) -> Any:
    return request.app.state.container


@router.get("/candles")
async def get_candles(
    request: Request,
    symbol: str,
    timeframe: TimeframeParam = Timeframe.M5,
    count: Annotated[int, Query(ge=1, le=5000)] = 300,
) -> list[dict]:
    candles = await _container(request).candle_history.get_candles(symbol, timeframe, count)
    return [candle_message(c) for c in candles]


@router.get("/symbol-info")
async def get_symbol_info(request: Request, symbol: str) -> dict:
    try:
        info = await _container(request).market_data.get_symbol_info(symbol)
    except MarketDataUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return asdict(info)


class BackfillRequest(BaseModel):
    symbols: list[str] | None = None  # default: configured symbols
    timeframes: list[Timeframe] | None = None  # default: M5/H1/H4/D1
    count: int = Field(default=1000, ge=1, le=5000)


@router.post("/backfill")
async def backfill(request: Request, body: BackfillRequest) -> dict:
    container = _container(request)
    symbols = body.symbols or container.symbols
    timeframes = body.timeframes or list(Timeframe)
    stored: dict[str, int] = {}
    try:
        for symbol in symbols:
            for timeframe in timeframes:
                bars = await container.candle_history.backfill(symbol, timeframe, body.count)
                stored[f"{symbol}:{timeframe.value}"] = bars
    except MarketDataUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"stored": stored}


@router.websocket("/ws")
async def market_ws(websocket: WebSocket) -> None:
    broadcaster = websocket.app.state.container.ws_broadcaster
    await broadcaster.connect(websocket)
    try:
        while True:
            await websocket.receive_text()  # client messages ignored for now
    except WebSocketDisconnect:
        broadcaster.disconnect(websocket)
