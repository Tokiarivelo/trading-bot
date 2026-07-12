"""FastAPI entrypoint.

Run with: uv run uvicorn src.main:socket_app --reload --port 8000

`socket_app` wraps `app` with the Socket.IO ASGI layer (see
`src.market_data.api.ws`) — Socket.IO handles its own path prefix
(`/socket.io/`) and forwards everything else to the FastAPI app underneath.

Interactive API docs (generated from the `response_model`/`summary`/
`description` on every route — see each module's `api/routes.py` and
`api/schemas.py`):
  - Swagger UI: http://localhost:8000/docs
  - ReDoc:      http://localhost:8000/redoc
  - Raw schema: http://localhost:8000/openapi.json  (or `make openapi`)
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import socketio
from fastapi import Depends, FastAPI
from pydantic import BaseModel, Field

from src.ai.api.routes import router as ai_router
from src.ai.api.routes_refinement import router as ai_refinement_router
from src.ai.api.routes_settings import router as ai_settings_router
from src.backtest.api.routes import router as backtest_router
from src.broker.api.routes import router as account_router
from src.broker.api.trading_routes import router as trading_router
from src.container import build_container
from src.engine.api.routes import router as engine_router
from src.journal.api.routes import router as journal_router
from src.market_data.api.routes import router as market_data_router
from src.market_data.api.ws import bind_auth, bind_candle_stream, bind_live_candle, sio
from src.news.api.routes import router as news_router
from src.shared.auth.api.routes import router as auth_router
from src.shared.auth.dependencies import require_session
from src.shared.config.settings import load_yaml_config
from src.shared.logging.setup import configure_logging
from src.strategies.api.routes import router as strategies_router

API_DESCRIPTION = """
REST + WebSocket API for the AI trading bot backend.

The backend never talks to MetaTrader5 directly — every broker/market-data
call is proxied through the MT5 Gateway HTTP service (see
`gateway/src/gateway/main.py`). Money-touching endpoints (`/broker/orders`,
`/broker/positions/*`) go through the spread/RR gate in
`broker/application/spread_gate.py` before ever reaching the broker adapter.

Live candle streaming is Socket.IO, not REST — see the `market-data` tag
description and `src/market_data/api/ws.py` for the `subscribe` /
`unsubscribe` / `candle_closed` / `candle_update` event contract.
"""

OPENAPI_TAGS = [
    {
        "name": "meta",
        "description": "Liveness check — no auth, no gateway dependency. Runtime configuration "
        "(`/config/app`) requires a session like every other route below.",
    },
    {
        "name": "auth",
        "description": "Login/logout for the shared app password (§11) — the bot can place "
        "live trades, so every route except this one and `/health` requires the session "
        "token `POST /auth/login` issues. When `TB_APP_PASSWORD` is unset, no session is "
        "required anywhere (bare local dev).",
    },
    {
        "name": "account",
        "description": "MT5 login/logout and connection status. Passwords transit request "
        "bodies only — never query strings, logs, or responses.",
    },
    {
        "name": "broker",
        "description": "Manual order placement and open-position management. Every order "
        "passes the per-symbol spread/RR gate before reaching the broker adapter "
        "(paper or live, per `configs/app.yaml: mode`).",
    },
    {
        "name": "market-data",
        "description": "Historical candles and live symbol specs over REST. Live candle "
        "streaming is Socket.IO (rooms per `symbol:timeframe`), documented in "
        "`src/market_data/api/ws.py` — Next.js rewrites don't proxy WS, so the "
        "frontend connects to this backend directly for it.",
    },
    {
        "name": "journal",
        "description": "Read-only trade history and chart markers, written automatically "
        "by the broker's `PositionOpened`/`PositionClosed` events.",
    },
    {
        "name": "engine",
        "description": "Automated trade-loop status and the manual kill switch. AI "
        "refinement logic and dev tooling must never call `/engine/kill` or "
        "`/engine/resume` — those are user-triggered controls only.",
    },
    {
        "name": "backtest",
        "description": "Read-only backtest reports written by `python -m src.backtest.cli` "
        "(or `make backtest`). There is no run-a-backtest endpoint — a backtest reads "
        "the same DB the live app does and can take a while, so it stays a CLI-only "
        "operation for now; this API only lists/reads the report files it produces.",
    },
    {
        "name": "ai",
        "description": "PDF -> StrategySpec -> code pipeline (F4), and the 10-trade "
        "self-refinement loop (F5). Every step is human-gated: upload/review only produces a "
        "draft or proposal, and code generation/refinement only ever produces a 'validated' "
        "strategy version — never an active, tradeable one, unless the refinement policy is "
        "'auto' and its backtest threshold is met. See the `strategies` tag for activation.",
    },
    {
        "name": "ai-settings",
        "description": "Per-task AI provider selection (Claude Code, Hermes Agent via Ollama, "
        "Ollama, OpenClaw) for document analysis, strategy generation, and trade-review/"
        "refinement. Changes apply without a backend restart — see the `ai` tag for the "
        "tasks themselves.",
    },
    {
        "name": "strategies",
        "description": "Strategy version history and activation. Activation registers a "
        "version live in the engine's `StrategyRegistry`; it never changes "
        "`configs/app.yaml`'s paper/live mode or any risk cap.",
    },
    {
        "name": "news",
        "description": "Economic calendar and active news-window status (F8) — read-only. "
        "The engine reacts to news windows internally: `NewsSkillSelector` blocks/overrides "
        "entries and the trade engine flattens positions on `NewsWindowEntered` when the "
        "matched news skill's `pre_event.close_all` requests it "
        "(`backend/src/skills/news/*.yaml`); this API only reports that state for the UI.",
    },
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    container = build_container()
    app.state.container = container
    bind_candle_stream(container.candle_stream)
    bind_live_candle(container.live_candle)
    bind_auth(container.session_issuer, lambda: container.settings.app_password)
    # Reconnect with stored credentials if the gateway is already up, then
    # start the candle streams — they idle harmlessly until login succeeds.
    await container.account.reconnect_from_stored()
    # Catch any broker-side close (SL/TP fill) that happened while the
    # backend was down — see broker/application/reconciliation.py.
    await container.reconciliation.reconcile_all()
    container.candle_stream.start()
    container.live_candle.start()
    container.news_window_service.start()
    container.health_monitor.start()
    yield
    await container.aclose()


app = FastAPI(
    title="AI Trading Bot",
    description=API_DESCRIPTION,
    version="0.1.0",
    openapi_tags=OPENAPI_TAGS,
    lifespan=lifespan,
)
_SESSION_REQUIRED = [Depends(require_session)]

app.include_router(auth_router)
app.include_router(account_router, dependencies=_SESSION_REQUIRED)
app.include_router(market_data_router, dependencies=_SESSION_REQUIRED)
app.include_router(trading_router, dependencies=_SESSION_REQUIRED)
app.include_router(journal_router, dependencies=_SESSION_REQUIRED)
app.include_router(engine_router, dependencies=_SESSION_REQUIRED)
app.include_router(backtest_router, dependencies=_SESSION_REQUIRED)
app.include_router(ai_router, dependencies=_SESSION_REQUIRED)
app.include_router(ai_refinement_router, dependencies=_SESSION_REQUIRED)
app.include_router(ai_settings_router, dependencies=_SESSION_REQUIRED)
app.include_router(strategies_router, dependencies=_SESSION_REQUIRED)
app.include_router(news_router, dependencies=_SESSION_REQUIRED)


class HealthOut(BaseModel):
    status: str = Field(description="Always 'ok' when the process is serving requests.")


class EngineConfigOut(BaseModel):
    enabled: bool = Field(description="Whether the automated trade loop runs at all.")
    entry_timeframe: str = Field(description="Timeframe the engine looks for entries on.")
    confirmation_timeframes: list[str] = Field(
        description="Higher timeframes used for multi-timeframe trend confirmation."
    )


class AppConfigOut(BaseModel):
    """Runtime mode/symbols from `configs/app.yaml` — the UI shows this
    prominently so it's always obvious whether the bot can place real trades."""

    mode: str = Field(description="'paper' (simulated fills) or 'live' (real broker orders).")
    timezone: str = Field(description="IANA timezone used for session windows and daily resets.")
    symbols: list[str] = Field(description="Symbols the engine and skills are configured for.")
    engine: EngineConfigOut


@app.get(
    "/health",
    response_model=HealthOut,
    tags=["meta"],
    summary="Liveness check",
    description="Unauthenticated liveness probe — returns 200 as soon as the ASGI app is serving, "
    "independent of gateway/DB connectivity. Use `/account/status` to check gateway health.",
)
async def health() -> HealthOut:
    return HealthOut(status="ok")


@app.get(
    "/config/app",
    response_model=AppConfigOut,
    tags=["meta"],
    summary="Get runtime app configuration",
    description="Current runtime mode/symbols/engine config from `configs/app.yaml` — the UI "
    "shows this prominently so paper vs. live mode is never ambiguous.",
    dependencies=_SESSION_REQUIRED,
    responses={401: {"description": "Missing or invalid session (see the `auth` tag)."}},
)
async def app_config() -> AppConfigOut:
    return AppConfigOut(**load_yaml_config("app"))


socket_app = socketio.ASGIApp(sio, other_asgi_app=app)
