"""Shared-secret auth: the backend must send X-Gateway-Secret on every call.

The secret comes from the GATEWAY_SHARED_SECRET env var. If it is unset the
check is skipped (bare local dev) — always set it when the gateway is
reachable from anywhere but localhost.
"""

from __future__ import annotations

import hmac
import os

from fastapi import Header, HTTPException


def verify_secret(x_gateway_secret: str = Header(default="")) -> None:
    secret = os.environ.get("GATEWAY_SHARED_SECRET", "")
    if secret and not hmac.compare_digest(x_gateway_secret, secret):
        raise HTTPException(status_code=401, detail="bad or missing X-Gateway-Secret")
