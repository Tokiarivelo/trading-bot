"""Phase 5 end-to-end: a synthetic M5 candle history containing two clean
breakout episodes (mirrors test_phase4_engine_flow.py's fixture style) is
seeded into a temp SQLite DB and replayed through `run_backtest`, driving the
exact same TradeEngine/RiskManager/PositionManager/OrderService pipeline live
trading uses. Confirms one trade closes via TP and the other via SL, and the
report's derived metrics match by direct calculation.

Uses the real `configs/` (risk.yaml, symbols/xauusd.yaml, app.yaml) since
those are the project's actual, checked-in trading config — no fixture
config needed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.backtest.application.run_backtest import NoSymbolSpecError, run_backtest
from src.market_data.adapters.candle_repository import CandleRepository
from src.market_data.adapters.replay import SymbolSpec
from src.market_data.adapters.symbol_spec_repository import SymbolSpecRepository
from src.market_data.domain.models import Candle, Timeframe
from src.shared.db.base import Base

M5_STEP = timedelta(minutes=5)
START = datetime(2025, 1, 1, tzinfo=UTC)


def m5(i: int, *, open: float, high: float, low: float, close: float, spread: int = 25) -> Candle:
    return Candle(
        symbol="XAUUSD",
        timeframe=Timeframe.M5,
        time=START + i * M5_STEP,
        open=open,
        high=high,
        low=low,
        close=close,
        tick_volume=1000,
        spread_points=spread,
    )


def build_m5_candles() -> list[Candle]:
    bars: list[Candle] = []
    # Episode 1: 20-bar flat range, a bullish breakout, then a bar whose high
    # clears the strategy's TP.
    bars += [m5(i, open=2400.0, high=2401.0, low=2399.0, close=2400.0) for i in range(20)]
    bars.append(m5(20, open=2401.0, high=2411.0, low=2400.5, close=2410.0))  # BUY breakout
    # Wick reaches the TP (2434.325) but the close stays below bar 20's high
    # (2411) so this bar doesn't *also* look like a fresh breakout signal.
    bars.append(m5(21, open=2410.0, high=2440.0, low=2405.0, close=2408.0))  # clears TP

    # Episode 2: a fresh 20-bar flat range, a bearish breakout, then a bar
    # whose high clears the strategy's SL (stopping the short out at a loss).
    bars += [m5(22 + i, open=2440.0, high=2441.0, low=2439.0, close=2440.0) for i in range(20)]
    bars.append(m5(42, open=2439.0, high=2439.5, low=2429.0, close=2430.0))  # SELL breakout
    bars.append(m5(43, open=2430.0, high=2445.0, low=2428.0, close=2432.0))  # clears SL
    return bars


def build_htf_candles(timeframe: Timeframe, step: timedelta, count: int = 5) -> list[Candle]:
    """Deliberately fewer bars than mtf_confirm's slow EMA period needs, so
    HTF confirmation is skipped (insufficient history) rather than vetoing —
    same trick test_phase4_engine_flow.py uses."""
    return [
        Candle(
            symbol="XAUUSD",
            timeframe=timeframe,
            time=START - (count - i) * step,
            open=2400.0,
            high=2401.0,
            low=2399.0,
            close=2400.5,
            tick_volume=1000,
            spread_points=25,
        )
        for i in range(count)
    ]


@pytest.fixture
def database_url(tmp_path) -> str:
    url = f"sqlite:///{tmp_path}/test.db"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    repository = CandleRepository(session_factory)
    repository.upsert_many(build_m5_candles())
    repository.upsert_many(build_htf_candles(Timeframe.H1, timedelta(hours=1)))
    repository.upsert_many(build_htf_candles(Timeframe.H4, timedelta(hours=4)))
    return url


async def test_backtest_closes_one_trade_via_tp_and_one_via_sl(database_url):
    report = await run_backtest(
        "breakout_v1", "XAUUSD", "2025-01:2025-01", database_url=database_url
    )

    assert len(report.trades) == 2
    tp_trade, sl_trade = report.trades

    assert tp_trade.side == "buy"
    assert tp_trade.profit > 0
    assert tp_trade.r_multiple == pytest.approx(2.2, rel=1e-3)  # breakout_v1's TP_RR

    assert sl_trade.side == "sell"
    assert sl_trade.profit < 0
    assert sl_trade.r_multiple == pytest.approx(-1.0, rel=1e-3)

    assert report.win_rate == pytest.approx(0.5)
    assert report.worst_losing_streak == 1
    assert report.ending_balance == pytest.approx(
        report.starting_balance + tp_trade.profit + sl_trade.profit
    )
    assert report.profit_factor == pytest.approx(tp_trade.profit / -sl_trade.profit)
    assert report.avg_r == pytest.approx((tp_trade.r_multiple + sl_trade.r_multiple) / 2)


async def test_backtest_raises_when_no_history(database_url):
    from src.backtest.application.run_backtest import NoHistoryError

    with pytest.raises(NoHistoryError):
        await run_backtest("breakout_v1", "XAUUSD", "2030-01:2030-01", database_url=database_url)


async def test_backtest_raises_when_history_only_partially_covers_the_period(database_url):
    """`build_m5_candles()` only seeds 2025-01-01 onward — requesting a period
    that starts well before that (e.g. 2024-06) must raise instead of
    silently replaying just the 2025-01 slice that happens to exist, which is
    what made a request for a year of history quietly turn into a report
    covering only a couple of days."""
    from src.backtest.application.run_backtest import NoHistoryError

    with pytest.raises(NoHistoryError, match="only goes back to"):
        await run_backtest("breakout_v1", "XAUUSD", "2024-06:2025-01", database_url=database_url)


async def test_backtest_rejects_unknown_strategy(database_url):
    with pytest.raises(ValueError, match="unknown strategy"):
        await run_backtest("not_a_strategy", "XAUUSD", "2025-01:2025-01", database_url=database_url)


async def test_backtest_rejects_symbol_the_strategy_does_not_trade(database_url):
    with pytest.raises(ValueError, match="does not trade"):
        await run_backtest("breakout_v1", "EURUSD", "2025-01:2025-01", database_url=database_url)


def _minimal_configs_dir(tmp_path: Path, *, xauusd_yaml: bool) -> Path:
    """A fixture configs/ containing only risk.yaml + app.yaml (both required
    unconditionally by run_backtest) and, optionally, a legacy
    symbols/xauusd.yaml — for exercising the DB-backed SymbolSpec sourcing
    without depending on the project's real checked-in config."""
    configs_dir = tmp_path / "configs"
    (configs_dir / "symbols").mkdir(parents=True)
    (configs_dir / "risk.yaml").write_text(
        "risk_per_trade_pct: 0.5\n"
        "daily_loss_limit_pct: 2.0\n"
        "max_open_positions: 100\n"
        "max_trades_per_day: 8\n"
        "consecutive_loss_pause: 10\n"
    )
    (configs_dir / "app.yaml").write_text('timezone: "UTC"\n')
    if xauusd_yaml:
        (configs_dir / "symbols" / "xauusd.yaml").write_text(
            "symbol: XAUUSD\n"
            "max_spread_points: 35\n"
            "min_rr: 1.5\n"
            "contract_size: 100.0\n"
            "point: 0.01\n"
            "digits: 2\n"
            "stops_level: 0\n"
            "volume_min: 0.01\n"
            "volume_max: 50\n"
            "volume_step: 0.01\n"
        )
    return configs_dir


def _spec(contract_size: float = 100.0) -> SymbolSpec:
    return SymbolSpec(
        point=0.01,
        digits=2,
        stops_level=0,
        contract_size=contract_size,
        volume_min=0.01,
        volume_max=50.0,
        volume_step=0.01,
    )


async def test_backtest_uses_db_backed_symbol_spec_without_any_yaml(tmp_path, database_url):
    """No configs/symbols/xauusd.yaml at all — the symbol_specs DB row
    (as populated by POST /market-data/backfill in production) is enough on
    its own to run a backtest."""
    configs_dir = _minimal_configs_dir(tmp_path, xauusd_yaml=False)
    engine = create_engine(database_url)
    SymbolSpecRepository(sessionmaker(bind=engine, expire_on_commit=False)).upsert(
        "XAUUSD", _spec()
    )

    report = await run_backtest(
        "breakout_v1", "XAUUSD", "2025-01:2025-01", database_url=database_url,
        configs_dir=configs_dir,
    )

    assert len(report.trades) == 2


async def test_backtest_raises_no_symbol_spec_without_db_row_or_yaml(tmp_path, database_url):
    configs_dir = _minimal_configs_dir(tmp_path, xauusd_yaml=False)

    with pytest.raises(NoSymbolSpecError, match="XAUUSD"):
        await run_backtest(
            "breakout_v1", "XAUUSD", "2025-01:2025-01", database_url=database_url,
            configs_dir=configs_dir,
        )


async def test_db_symbol_spec_takes_precedence_over_legacy_yaml(tmp_path, database_url):
    """The legacy YAML has a normal volume_min (0.01, same as the main
    fixture test above, which trades fine). The DB row's volume_min is set
    absurdly high (1000) — risk-based position sizing can never produce a
    viable lot size that large, so no trade opens. If the YAML were still
    winning over the DB row, trades would go through exactly like the main
    test; zero trades here proves the DB row is the one actually used."""
    configs_dir = _minimal_configs_dir(tmp_path, xauusd_yaml=True)
    engine = create_engine(database_url)
    repository = SymbolSpecRepository(sessionmaker(bind=engine, expire_on_commit=False))
    repository.upsert(
        "XAUUSD",
        SymbolSpec(
            point=0.01,
            digits=2,
            stops_level=0,
            contract_size=100.0,
            volume_min=1000.0,
            volume_max=2000.0,
            volume_step=0.01,
        ),
    )

    report = await run_backtest(
        "breakout_v1", "XAUUSD", "2025-01:2025-01", database_url=database_url,
        configs_dir=configs_dir,
    )

    assert report.trades == ()
