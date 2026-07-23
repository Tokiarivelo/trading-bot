"""`GET /accounts` — list every configured account (MULTI_ACCOUNT_PLAN.md
Phase 6). Global, unprefixed: a client calls this *before* it knows any
`account_id`, to discover which accounts exist (for an account switcher) and
which ids are valid on every other `/accounts/{account_id}/...` route.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from src.broker.api.schemas import AccountSummaryOut

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.get(
    "",
    response_model=list[AccountSummaryOut],
    summary="List configured accounts",
    description=(
        "Every enabled account wired up from `configs/accounts.yaml` at startup — the "
        "frontend's account switcher and every other route's valid `{account_id}` path "
        "segment both come from here. Does not include credentials, the gateway URL, or "
        "the gateway shared-secret env var name."
    ),
)
async def list_accounts(request: Request) -> list[AccountSummaryOut]:
    container = request.app.state.container
    return [
        AccountSummaryOut(
            id=runtime.config.id,
            label=runtime.config.label,
            mode=runtime.config.mode,
            enabled=runtime.config.enabled,
        )
        for runtime in container.accounts.values()
    ]
