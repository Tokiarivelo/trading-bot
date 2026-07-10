"""FastAPI entrypoint.

Run with: uv run uvicorn src.main:app --reload --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.container import build_container
from src.shared.config.settings import load_yaml_config
from src.shared.logging.setup import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    app.state.container = build_container()
    yield


app = FastAPI(title="AI Trading Bot", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/config/app")
async def app_config() -> dict:
    """Current runtime mode/symbols — the UI shows this prominently."""
    return load_yaml_config("app")
