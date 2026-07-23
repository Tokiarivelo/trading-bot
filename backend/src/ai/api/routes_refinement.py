"""10-trade self-refinement loop endpoints (§8.2, F5).

Read-only except for `reject` — reviews and proposals are produced entirely
by `RefinementLoopService.on_ten_trades_completed` off the event bus, never
by a direct API call. Applying a proposal (or rolling back to any older
version) is the same `POST /strategies/versions/{id}/activate` a human uses
for manually-generated code — see the `strategies` tag.
"""

from __future__ import annotations

import difflib
import json

from fastapi import APIRouter, HTTPException, Path, Query

from src.ai.api.schemas import AnalysisReportOut, RefinementProposalDetailOut
from src.ai.application.refinement_loop import InvalidProposalStateError, RefinementLoopService
from src.ai.domain.models import RefinementProposal
from src.backtest.api.schemas import BacktestReportSummaryOut
from src.backtest.reports.writer import REPORTS_DIR
from src.shared.api.dependencies import AccountRuntimeDep
from src.strategies.application.versioning import StrategyVersionService

router = APIRouter(prefix="/accounts/{account_id}/ai/refinement", tags=["ai"])

_REPORT_NOT_FOUND = {404: {"description": "No analysis report with that id."}}
_PROPOSAL_NOT_FOUND = {404: {"description": "No refinement proposal with that id."}}
_PROPOSAL_STATE_CONFLICT = {
    409: {"description": "The proposal is already 'applied' or 'rejected'."}
}


def _service(account: AccountRuntimeDep) -> RefinementLoopService:
    return account.refinement_loop


def _strategy_versions(account: AccountRuntimeDep) -> StrategyVersionService:
    return account.strategy_versions


@router.get(
    "/reports",
    response_model=list[AnalysisReportOut],
    summary="List 10-trade analysis reports",
    description=(
        "Every AI review triggered by `TenTradesCompleted`, newest first — including reviews "
        "that found nothing worth changing (verdict 'no_action'), which are kept for audit."
    ),
)
async def list_reports(
    account: AccountRuntimeDep,
    symbol: str | None = Query(default=None, description="Filter to one symbol, e.g. XAUUSD."),
) -> list[AnalysisReportOut]:
    reports = await _service(account).list_reports(symbol)
    return [AnalysisReportOut.from_domain(r) for r in reports]


@router.get(
    "/reports/{report_id}",
    response_model=AnalysisReportOut,
    summary="Get a single analysis report",
    description="Full review detail — findings, verdict, and the raw LLM response for audit.",
    responses=_REPORT_NOT_FOUND,
)
async def get_report(
    account: AccountRuntimeDep,
    report_id: str = Path(description="Report id, as returned by GET .../reports."),
) -> AnalysisReportOut:
    report = await _service(account).get_report(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="report not found")
    return AnalysisReportOut.from_domain(report)


@router.get(
    "/proposals/{proposal_id}",
    response_model=RefinementProposalDetailOut,
    summary="Get a refinement proposal, with diff and before/after backtests",
    description=(
        "Full detail for a code refinement the AI proposed after a review: the rationale, the "
        "full proposed source, a unified diff against the base version's code (computed fresh "
        "on every read, never stored), and headline backtest stats for both the base version "
        "and the proposal over the same comparison period. To apply it (or roll back to any "
        "older version later), use `POST /strategies/versions/{new_version_id}/activate` — this "
        "endpoint never activates anything itself."
    ),
    responses=_PROPOSAL_NOT_FOUND,
)
async def get_proposal(
    account: AccountRuntimeDep,
    proposal_id: str = Path(description="Proposal id, from an AnalysisReport's proposal_id."),
) -> RefinementProposalDetailOut:
    proposal = await _service(account).get_proposal(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="proposal not found")
    return _detail(account, proposal)


@router.post(
    "/proposals/{proposal_id}/reject",
    response_model=RefinementProposalDetailOut,
    summary="Reject a pending refinement proposal",
    description=(
        "Marks a 'pending'/'backtested' proposal as rejected so it stops showing as awaiting a "
        "decision — the underlying StrategyVersion stays on disk as 'validated' but is never "
        "activated. Only allowed before the proposal is already 'applied' or 'rejected'."
    ),
    responses={**_PROPOSAL_NOT_FOUND, **_PROPOSAL_STATE_CONFLICT},
)
async def reject_proposal(
    account: AccountRuntimeDep,
    proposal_id: str = Path(description="Proposal id to reject."),
) -> RefinementProposalDetailOut:
    try:
        proposal = await _service(account).reject_proposal(proposal_id)
    except InvalidProposalStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _detail(account, proposal)


def _detail(
    account: AccountRuntimeDep, proposal: RefinementProposal
) -> RefinementProposalDetailOut:
    versions = _strategy_versions(account)
    base_version = versions.get_version(proposal.base_version_id)
    base_code = versions.get_code(base_version) if base_version is not None else ""
    diff = list(
        difflib.unified_diff(
            base_code.splitlines(),
            proposal.proposed_code.splitlines(),
            fromfile=f"{proposal.strategy_name} (base)",
            tofile=f"{proposal.strategy_name} (proposed)",
            lineterm="",
        )
    )
    return RefinementProposalDetailOut.from_domain(
        proposal,
        diff=diff,
        baseline_backtest=_load_backtest_summary(proposal.baseline_backtest_report_id),
        candidate_backtest=_load_backtest_summary(proposal.candidate_backtest_report_id),
    )


def _load_backtest_summary(report_id: str | None) -> BacktestReportSummaryOut | None:
    if report_id is None:
        return None
    path = REPORTS_DIR / f"{report_id}.json"
    if not path.is_file():
        return None
    with path.open() as f:
        data = json.load(f)
    return BacktestReportSummaryOut(
        id=report_id,
        strategy=data["strategy"],
        symbol=data["symbol"],
        period=data["period"],
        trade_count=len(data["trades"]),
        win_rate=data["win_rate"],
        profit_factor=data["profit_factor"],
        max_drawdown_pct=data["max_drawdown_pct"],
        avg_r=data["avg_r"],
        worst_losing_streak=data["worst_losing_streak"],
        starting_balance=data["starting_balance"],
        ending_balance=data["ending_balance"],
    )
