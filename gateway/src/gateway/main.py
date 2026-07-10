"""MT5 Gateway — FastAPI app skeleton (endpoints land in Phase 1).

Runs on Windows or under Wine next to a running MT5 terminal:
    wine python -m uvicorn src.gateway.main:app --port 8787
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="MT5 Gateway")


@app.get("/health")
def health() -> dict[str, str | bool]:
    # Phase 1: also report mt5.terminal_info() connection state.
    return {"status": "ok", "terminal_connected": False}
