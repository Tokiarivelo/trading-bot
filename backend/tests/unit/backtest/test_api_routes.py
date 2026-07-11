from datetime import UTC, datetime

import httpx
import pytest
from fastapi import FastAPI

from src.backtest.api import routes as routes_module
from src.backtest.api.routes import router
from src.backtest.domain.models import BacktestReport, BacktestTrade, EquityPoint
from src.backtest.reports.writer import write_report

T0 = datetime(2025, 1, 1, tzinfo=UTC)
T1 = datetime(2025, 1, 1, 0, 5, tzinfo=UTC)


def make_report(profit: float = 96.8) -> BacktestReport:
    trade = BacktestTrade(
        side="buy",
        volume=0.04,
        open_time=T0,
        open_price=2410.125,
        sl=2399.125,
        tp=2434.325,
        close_time=T1,
        close_price=2434.325,
        profit=profit,
        r_multiple=2.2,
    )
    return BacktestReport(
        strategy="breakout_v1",
        symbol="XAUUSD",
        period="2025-01:2025-01",
        starting_balance=10_000.0,
        ending_balance=10_000.0 + profit,
        trades=(trade,),
        equity_curve=(
            EquityPoint(time=T0, balance=10_000.0),
            EquityPoint(time=T1, balance=10_000.0 + profit),
        ),
        win_rate=1.0,
        profit_factor=float("inf"),
        max_drawdown_pct=0.0,
        avg_r=2.2,
        worst_losing_streak=0,
    )


@pytest.fixture
async def api(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_module, "REPORTS_DIR", tmp_path)
    app = FastAPI()
    app.include_router(router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://backend") as client:
        yield client, tmp_path


async def test_list_reports_empty_dir(api):
    client, _ = api
    response = await client.get("/backtest/reports")
    assert response.status_code == 200
    assert response.json() == []


async def test_list_reports_returns_summary(api):
    client, reports_dir = api
    write_report(make_report(), reports_dir)

    response = await client.get("/backtest/reports")
    assert response.status_code == 200
    (summary,) = response.json()
    assert summary["strategy"] == "breakout_v1"
    assert summary["symbol"] == "XAUUSD"
    assert summary["trade_count"] == 1
    assert summary["profit_factor"] is None  # inf serialized as null


async def test_get_report_returns_full_detail(api):
    client, reports_dir = api
    path = write_report(make_report(), reports_dir)

    response = await client.get(f"/backtest/reports/{path.stem}")
    assert response.status_code == 200
    detail = response.json()
    assert len(detail["trades"]) == 1
    assert detail["trades"][0]["r_multiple"] == pytest.approx(2.2)
    assert detail["trades"][0]["open_time"] == int(T0.timestamp())
    assert len(detail["equity_curve"]) == 2


async def test_get_report_unknown_id_404s(api):
    client, _ = api
    response = await client.get("/backtest/reports/does_not_exist")
    assert response.status_code == 404


async def test_get_report_rejects_path_traversal(api):
    client, _ = api
    response = await client.get("/backtest/reports/..%2F..%2F..%2Fetc%2Fpasswd")
    assert response.status_code == 404
