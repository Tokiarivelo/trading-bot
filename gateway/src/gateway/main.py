"""MT5 Gateway — FastAPI app.

Runs on Windows or under Wine next to a running MT5 terminal:
    cd gateway
    wine python run_gateway.py          # see run_gateway.py for sys.path setup

Thin and dumb by design: raw broker facts + explicit commands, no business
logic. Everything except /health requires the X-Gateway-Secret header
(GATEWAY_SHARED_SECRET env var).
"""

from __future__ import annotations

from fastapi import Depends, FastAPI

from .mt5_client import client
from .routes import auth, market_data
from .schemas import HealthOut
from .security import verify_secret

app = FastAPI(title="MT5 Gateway")

app.include_router(auth.router, dependencies=[Depends(verify_secret)])
app.include_router(market_data.router, dependencies=[Depends(verify_secret)])


@app.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    return HealthOut(**client.health())
