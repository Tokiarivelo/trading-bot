"""Deterministic backtest runner (Phase 5).

Replays historical candles through the exact same `TradeEngine` /
`RiskManager` / `PositionManager` / `OrderService` pipeline the live engine
uses — only the market-data, account, and skill-selection adapters are
backtest-specific (replay instead of the gateway, a simulated balance
instead of a real MT5 account, a fixed strategy instead of skill selection).
This guarantees "what you backtest is what runs live."

Composition root for backtests — mirrors `container.py`'s wiring style but
self-contained: a fresh `EventBus`, no gateway HTTP client, no writes to the
live journal DB.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from src.backtest.adapters.bookkeeper import BacktestBookkeeper
from src.backtest.adapters.fixed_skill_selector import FixedSkillSelector
from src.backtest.application import metrics
from src.backtest.application.period import parse_period
from src.backtest.domain.models import BacktestReport
from src.broker.adapters.paper import PaperBroker
from src.broker.application.order_service import OrderService
from src.broker.application.spread_gate import SpreadGate
from src.broker.domain.trading import Position, Side
from src.engine.application.position_manager import PositionManager
from src.engine.application.risk_manager import RiskManager
from src.engine.application.trade_loop import TradeEngine
from src.engine.ports.strategy_source import StrategySourcePort
from src.market_data.adapters.candle_repository import CandleRepository
from src.market_data.adapters.replay import ReplayMarketDataPort, SymbolSpec
from src.market_data.domain.models import Candle, Timeframe
from src.shared.config.loaders import load_risk_caps, load_symbol_trading_config
from src.shared.config.settings import CONFIGS_DIR, load_yaml_config
from src.shared.db.base import make_session_factory
from src.shared.events.bus import EventBus
from src.shared.events.definitions import CandleClosed, PositionClosed, PositionOpened
from src.strategies.adapters.repository import StrategyVersionRepository
from src.strategies.application.versioning import StrategyVersionService
from src.strategies.generated.breakout_v1 import BreakoutV1
from src.strategies.registry import StrategyRegistry

logger = logging.getLogger(__name__)

# Warmup window loaded before the requested start so indicators (mtf_confirm's
# EMA(50), a strategy's own lookback) have real history on the first bar
# traded, not an artificially short warm-up.
HISTORY_BUFFER = timedelta(days=60)
DEFAULT_STARTING_BALANCE = 10_000.0
DEFAULT_DATABASE_URL = "sqlite:///./data/trading.db"
# backend/src/backtest/application/run_backtest.py -> backend/src
_BACKEND_SRC_DIR = Path(__file__).resolve().parent.parent.parent
_STRATEGIES_GENERATED_DIR = _BACKEND_SRC_DIR / "strategies" / "generated"


class NoHistoryError(Exception):
    """No candle history in the requested range — run the backfill job first."""


async def run_backtest(
    strategy_name: str,
    symbol: str,
    period: str,
    *,
    strategy_source: StrategySourcePort | None = None,
    starting_balance: float = DEFAULT_STARTING_BALANCE,
    database_url: str = DEFAULT_DATABASE_URL,
    configs_dir: Path = CONFIGS_DIR,
) -> BacktestReport:
    start, end = parse_period(period)

    registry = strategy_source or _default_registry(database_url)
    strategy = registry.get(strategy_name)
    if strategy is None:
        raise ValueError(f"unknown strategy: {strategy_name!r}")
    if symbol not in strategy.spec.symbols:
        raise ValueError(f"strategy {strategy_name!r} does not trade {symbol}")

    symbol_config = load_symbol_trading_config(symbol, configs_dir)
    risk_caps = load_risk_caps(configs_dir)
    timezone = load_yaml_config("app", configs_dir).get("timezone", "UTC")

    session_factory = make_session_factory(database_url)
    repository = CandleRepository(session_factory)
    history_start = start - HISTORY_BUFFER
    candles: dict[Timeframe, list[Candle]] = {
        tf: repository.get_range(symbol, tf, history_start, end) for tf in Timeframe
    }
    m5_bars = [c for c in candles[Timeframe.M5] if c.time >= start]
    if not m5_bars:
        raise NoHistoryError(
            f"no M5 candle history for {symbol} in {start.date()}..{end.date()} — "
            "run the historical backfill job first (POST /market-data/backfill)"
        )

    spec = SymbolSpec(
        point=symbol_config.point,
        digits=symbol_config.digits,
        stops_level=symbol_config.stops_level,
        contract_size=symbol_config.contract_size,
        volume_min=symbol_config.volume_min,
        volume_max=symbol_config.volume_max,
        volume_step=symbol_config.volume_step,
    )
    replay = ReplayMarketDataPort(symbol, candles, spec)

    event_bus = EventBus()
    spread_gate = SpreadGate({symbol: symbol_config})
    broker = PaperBroker(replay)
    order_service = OrderService(
        broker=broker, market_data=replay, spread_gate=spread_gate, event_bus=event_bus
    )
    risk_manager = RiskManager(caps=risk_caps, timezone=timezone)
    position_manager = PositionManager(order_service=order_service, market_data=replay)

    clock_box = {"now": history_start}
    clock: Callable[[], datetime] = lambda: clock_box["now"]  # noqa: E731

    bookkeeper = BacktestBookkeeper(
        starting_balance=starting_balance,
        risk_manager=risk_manager,
        contract_size=symbol_config.contract_size,
        clock=clock,
    )
    # The bookkeeper is the sole PositionClosed handler: it owns balance and
    # feeds the risk manager's circuit breakers explicitly. TradeEngine's own
    # on_position_closed is intentionally NOT subscribed here, so there is
    # exactly one writer of trade-close state (see backtest/adapters/bookkeeper.py).
    event_bus.subscribe(PositionOpened, bookkeeper.on_position_opened)
    event_bus.subscribe(PositionClosed, bookkeeper.on_position_closed)

    trade_engine = TradeEngine(
        market_data=replay,
        order_service=order_service,
        account=bookkeeper,
        risk_manager=risk_manager,
        position_manager=position_manager,
        skill_selector=FixedSkillSelector(strategy_name),
        strategy_source=registry,
        entry_timeframe=strategy.spec.entry_timeframe,
        confirmation_timeframes=strategy.spec.confirmation_timeframes,
        clock=clock,
    )

    logger.info(
        "backtest starting: strategy=%s symbol=%s period=%s bars=%d starting_balance=%.2f",
        strategy_name,
        symbol,
        period,
        len(m5_bars),
        starting_balance,
    )
    for candle in m5_bars:
        replay.advance_to(candle.close_time)
        clock_box["now"] = candle.close_time
        await _check_stops(order_service, symbol, candle)
        await trade_engine.on_candle_closed(
            CandleClosed(symbol=symbol, timeframe="M5", occurred_at=candle.close_time)
        )

    await _force_close_open_positions(order_service, symbol, m5_bars[-1])

    trades = tuple(bookkeeper.trades)
    equity_curve = tuple(bookkeeper.equity_curve)
    return BacktestReport(
        strategy=strategy_name,
        symbol=symbol,
        period=period,
        starting_balance=starting_balance,
        ending_balance=bookkeeper.balance,
        trades=trades,
        equity_curve=equity_curve,
        win_rate=metrics.win_rate(trades),
        profit_factor=metrics.profit_factor(trades),
        max_drawdown_pct=metrics.max_drawdown_pct(equity_curve),
        avg_r=metrics.avg_r(trades),
        worst_losing_streak=metrics.worst_losing_streak(trades),
    )


async def _check_stops(order_service: OrderService, symbol: str, candle: Candle) -> None:
    for position in await order_service.get_positions(symbol):
        stop_price = _stop_hit(position, candle)
        if stop_price is not None:
            await order_service.close_at_price(position.ticket, stop_price, candle.close_time)


async def _force_close_open_positions(
    order_service: OrderService, symbol: str, last_candle: Candle
) -> None:
    for position in await order_service.get_positions(symbol):
        await order_service.close_at_price(
            position.ticket, last_candle.close, last_candle.close_time
        )


def _stop_hit(position: Position, candle: Candle) -> float | None:
    """SL checked before TP if a bar's range spans both — the standard
    conservative backtesting convention (assume the worse outcome)."""
    if position.side is Side.BUY:
        if position.sl is not None and candle.low <= position.sl:
            return position.sl
        if position.tp is not None and candle.high >= position.tp:
            return position.tp
    else:
        if position.sl is not None and candle.high >= position.sl:
            return position.sl
        if position.tp is not None and candle.low <= position.tp:
            return position.tp
    return None


def _default_registry(database_url: str) -> StrategyRegistry:
    """`breakout_v1` plus every strategy the trader has actually built and
    activated — mirrors `container.py`'s startup wiring so `make backtest`/
    the CLI can run a backtest against any AI-generated or hand-edited
    strategy, not just the hardcoded demo one."""
    registry = StrategyRegistry()
    registry.register(BreakoutV1())
    session_factory = make_session_factory(database_url)
    strategy_versions = StrategyVersionService(
        repository=StrategyVersionRepository(session_factory),
        registry=registry,
        generated_dir=_STRATEGIES_GENERATED_DIR,
    )
    strategy_versions.load_active_into_registry()
    return registry
