"""Read-only backtest report endpoints.

These never run a backtest — they only list/read the JSON files
`python -m src.backtest.cli` (or `make backtest`) already wrote to
`backtest/reports/`. There is deliberately no "run a backtest" HTTP endpoint:
a backtest can take a while and touches the same DB the live app reads from,
so it's a CLI-only operation for now (see `.claude/skills/backtest/SKILL.md`).
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Path

from src.backtest.api.schemas import BacktestReportDetailOut, BacktestReportSummaryOut
from src.backtest.reports.writer import REPORTS_DIR

router = APIRouter(prefix="/backtest", tags=["backtest"])

_VALID_ID = re.compile(r"^[A-Za-z0-9_-]+$")


@router.get(
    "/reports",
    response_model=list[BacktestReportSummaryOut],
    summary="List saved backtest reports",
    description=(
        "Headline stats for every report file under `backend/src/backtest/reports/`, "
        "newest first. Reports are written by `python -m src.backtest.cli "
        "<strategy> <symbol> <period>` (or `make backtest`); this endpoint never "
        "triggers a run itself."
    ),
)
async def list_reports() -> list[BacktestReportSummaryOut]:
    if not REPORTS_DIR.exists():
        return []
    paths = sorted(REPORTS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [_summary(_load(p), p.stem) for p in paths]


@router.get(
    "/reports/{report_id}",
    response_model=BacktestReportDetailOut,
    summary="Get a single backtest report",
    description=(
        "Full report for `report_id` (the filename stem returned by "
        "`GET /backtest/reports`) — every trade and the equity curve, for the "
        "report detail page's trade table and equity chart."
    ),
    responses={404: {"description": "No report file with that id."}},
)
async def get_report(
    report_id: str = Path(description="Report id, as returned by GET /backtest/reports."),
) -> BacktestReportDetailOut:
    if not _VALID_ID.match(report_id):
        raise HTTPException(status_code=404, detail="report not found")
    path = REPORTS_DIR / f"{report_id}.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="report not found")
    data = _load(path)
    return BacktestReportDetailOut(
        **_summary(data, report_id).model_dump(),
        trades=[_trade_out(t) for t in data["trades"]],
        equity_curve=[
            {"time": _epoch(p["time"]), "balance": p["balance"]} for p in data["equity_curve"]
        ],
    )


def _load(path: Any) -> dict[str, Any]:
    with path.open() as f:
        return json.load(f)


def _summary(data: dict[str, Any], report_id: str) -> BacktestReportSummaryOut:
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


def _trade_out(trade: dict[str, Any]) -> dict[str, Any]:
    return {
        **trade,
        "open_time": _epoch(trade["open_time"]),
        "close_time": _epoch(trade["close_time"]),
    }


def _epoch(iso: str) -> int:
    return int(datetime.fromisoformat(iso).astimezone(UTC).timestamp())
