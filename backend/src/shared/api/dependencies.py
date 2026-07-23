"""Shared FastAPI dependency for account-scoped routes.

MULTI_ACCOUNT_PLAN.md Phase 6: every account-scoped route lives under
`/accounts/{account_id}/...`. `get_account_runtime` resolves that path
segment to its `AccountRuntime` (Phase 5) — the one place a 404 is raised
for an `account_id` that isn't in `configs/accounts.yaml`, so every route
using it gets that behavior for free instead of re-deriving it per module.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Path, Request

from src.container import AccountRuntime

_ACCOUNT_ID_PATH = Path(
    description="Short slug identifying the account, e.g. 'ftmo-1' — see `GET /accounts` "
    "for valid values."
)


def get_account_runtime(
    account_id: Annotated[str, _ACCOUNT_ID_PATH], request: Request
) -> AccountRuntime:
    container = request.app.state.container
    try:
        return container.accounts[account_id]
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown account_id: {account_id!r}") from None


AccountRuntimeDep = Annotated[AccountRuntime, Depends(get_account_runtime)]
