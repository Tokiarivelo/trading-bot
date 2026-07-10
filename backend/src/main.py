"""FastAPI entrypoint.

Run with: uv run uvicorn src.main:app --reload --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.broker.api.routes import router as account_router
from src.container import build_container
from src.market_data.api.routes import router as market_data_router
from src.shared.config.settings import load_yaml_config
from src.shared.logging.setup import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    container = build_container()
    app.state.container = container
    # Reconnect with stored credentials if the gateway is already up, then
    # start the candle stream — it idles harmlessly until login succeeds.
    await container.account.reconnect_from_stored()
    container.candle_stream.start()
    yield
    await container.aclose()


app = FastAPI(title="AI Trading Bot", lifespan=lifespan)
app.include_router(account_router)
app.include_router(market_data_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/config/app")
async def app_config() -> dict:
    """Current runtime mode/symbols — the UI shows this prominently."""
    return load_yaml_config("app")
