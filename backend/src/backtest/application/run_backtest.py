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

import dataclasses
import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session, sessionmaker

from src.backtest.adapters.bookkeeper import BacktestBookkeeper
from src.backtest.adapters.context_builder import CachedContextBuilder
from src.backtest.adapters.fixed_skill_selector import FixedSkillSelector
from src.backtest.application import metrics
from src.backtest.application.period import parse_period
from src.backtest.application.signals import extract_signals
from src.backtest.domain.models import ActivityLogEntry, BacktestReport
from src.broker.adapters.paper import PaperBroker
from src.broker.application.order_service import OrderService
from src.broker.application.spread_gate import DEFAULT_MIN_RR, SpreadGate
from src.broker.domain.symbol_config import SymbolTradingConfig
from src.broker.domain.trading import Position, Side
from src.engine.application.position_manager import PositionManager
from src.engine.application.risk_manager import RiskManager
from src.engine.application.trade_loop import TradeEngine
from src.engine.ports.strategy_source import StrategySourcePort
from src.market_data.adapters.candle_repository import CandleRepository
from src.market_data.adapters.replay import ReplayMarketDataPort, SymbolSpec
from src.market_data.adapters.symbol_spec_repository import SymbolSpecRepository
from src.market_data.domain.models import Candle, Timeframe
from src.shared.config.loaders import load_risk_caps, load_symbol_trading_config_if_exists
from src.shared.config.settings import CONFIGS_DIR, load_yaml_config
from src.shared.db.base import make_session_factory
from src.shared.events.bus import EventBus
from src.shared.events.definitions import CandleClosed, PositionClosed, PositionOpened
from src.strategies.adapters.repository import StrategyVersionRepository
from src.strategies.application.versioning import StrategyVersionService
from src.strategies.generated.breakout_v1 import BreakoutV1
from src.strategies.generated.breakout_v2 import BreakoutV2
from src.strategies.generated.mean_reversion_v1 import MeanReversionV1
from src.strategies.generated.trend_structure_v1 import TrendStructureV1
from src.strategies.generated.trend_structure_v2 import TrendStructureV2
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


class _ActivityCapture(logging.Handler):
    """Mirrors every `src.*` INFO+ log line emitted during the replay loop
    into an in-memory list, stamped with the *simulated* clock rather than
    wall-clock time — this is what lets a zero-trade report still show why
    (signals, HTF vetoes, sizing rejections) without the server's stdout.

    Deliberately separate from `src.activity`'s DB-backed handler (see
    `shared/logging/setup.py`): a backtest replays weeks of history in
    seconds and must not flood the live "what is the bot doing right now"
    activity log with replay noise."""

    def __init__(self, clock: Callable[[], datetime]) -> None:
        super().__init__(level=logging.INFO)
        self._clock = clock
        self.entries: list[ActivityLogEntry] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.entries.append(
            ActivityLogEntry(
                time=self._clock(),
                level=record.levelname,
                logger=record.name,
                message=record.getMessage(),
            )
        )


class NoHistoryError(Exception):
    """No candle history in the requested range — run the backfill job first."""


class NoSymbolSpecError(Exception):
    """No broker facts (point/digits/stops_level/contract_size/volume_*) known
    for this symbol — neither a `symbol_specs` DB row (populated by
    `POST /market-data/backfill`) nor a legacy `configs/symbols/<symbol>.yaml`
    exist."""


async def run_backtest(
    strategy_name: str,
    symbol: str,
    period: str,
    *,
    strategy_source: StrategySourcePort | None = None,
    starting_balance: float = DEFAULT_STARTING_BALANCE,
    database_url: str = DEFAULT_DATABASE_URL,
    configs_dir: Path = CONFIGS_DIR,
    min_lot_fallback_enabled: bool | None = None,
    max_risk_per_trade_pct: float | None = None,
    min_rr: float | None = None,
) -> BacktestReport:
    """`min_lot_fallback_enabled`/`max_risk_per_trade_pct`, when given, override
    `configs/risk.yaml`'s values for this run only — lets you try a different
    min-lot fallback setting on a small-balance backtest before flipping it
    on for the live bot via `PUT /engine/risk-caps/min-lot-fallback`. `None`
    (the default for each) means "use what's configured in the file".

    `min_rr` similarly overrides `configs/symbols/<symbol>.yaml`'s min_rr for
    this run only — a tighter-stop strategy (e.g. a scalping variant) can
    fail the spread-adjusted RR floor a swing-trading min_rr was tuned for,
    since a fixed-points spread eats a bigger share of a smaller take-profit;
    this lets you find a working value before flipping it on for the live
    bot via `PUT /broker/symbols/{symbol}/min-rr`. Has no effect if `symbol`
    has no `configs/symbols/<symbol>.yaml` at all (there's no config to
    override — SpreadGate would already be using its own no-cap fallback)."""
    start, end = parse_period(period)

    registry = strategy_source or _default_registry(database_url)
    strategy = registry.get(strategy_name)
    if strategy is None:
        raise ValueError(f"unknown strategy: {strategy_name!r}")
    if symbol not in strategy.spec.symbols:
        raise ValueError(f"strategy {strategy_name!r} does not trade {symbol}")

    # Policy fields (max_spread_points/min_rr) are optional — a symbol with no
    # legacy configs/symbols/<symbol>.yaml just runs with SpreadGate's own
    # no-config fallback (no spread cap, DEFAULT_MIN_RR), same as manual
    # trading on an unconfigured symbol already does live.
    symbol_config = load_symbol_trading_config_if_exists(symbol, configs_dir)
    if min_rr is not None:
        if symbol_config is not None:
            symbol_config = dataclasses.replace(symbol_config, min_rr=min_rr)
        else:
            logger.warning(
                "min_rr override=%.2f requested but %s has no configs/symbols/ file — "
                "nothing to override, SpreadGate's no-cap fallback still applies",
                min_rr,
                symbol,
            )
    resolved_min_rr = symbol_config.min_rr if symbol_config is not None else DEFAULT_MIN_RR
    risk_caps = load_risk_caps(configs_dir)
    if min_lot_fallback_enabled is not None or max_risk_per_trade_pct is not None:
        risk_caps = dataclasses.replace(
            risk_caps,
            min_lot_fallback_enabled=(
                risk_caps.min_lot_fallback_enabled
                if min_lot_fallback_enabled is None
                else min_lot_fallback_enabled
            ),
            max_risk_per_trade_pct=(
                risk_caps.max_risk_per_trade_pct
                if max_risk_per_trade_pct is None
                else max_risk_per_trade_pct
            ),
        )
    timezone = load_yaml_config("app", configs_dir).get("timezone", "UTC")

    entry_tf = Timeframe(strategy.spec.entry_timeframe)

    session_factory = make_session_factory(database_url)
    repository = CandleRepository(session_factory)
    history_start = start - HISTORY_BUFFER
    # Only the timeframes this run can ever read: the strategy's entry and
    # confirmation frames plus its engine HTF-veto frame (the timeframe
    # immediately above entry_tf — see trade_loop._veto_timeframe), plus M5,
    # which `ReplayMarketDataPort` always needs to derive bid/ask from the
    # current bar. Loading all nine timeframes made DB reads the single
    # biggest fixed cost of a run (e.g. ~100k M1 rows for an M5 strategy that
    # never looks at them).
    veto_tf = entry_tf.next_up() if strategy.spec.htf_veto else None
    needed_timeframes = (
        {entry_tf, Timeframe.M5}
        | {Timeframe(tf) for tf in strategy.spec.confirmation_timeframes}
        | ({veto_tf} if veto_tf is not None else set())
    )
    candles: dict[Timeframe, list[Candle]] = {
        tf: repository.get_range(symbol, tf, history_start, end) for tf in needed_timeframes
    }
    entry_bars = [c for c in candles[entry_tf] if c.time >= start]
    if not entry_bars:
        raise NoHistoryError(
            f"no {entry_tf.value} candle history for {symbol} in {start.date()}..{end.date()} — "
            "run the historical backfill job first (POST /market-data/backfill, "
            f"with start={start.date()} to pull the full range)"
        )
    # A backtest replaying less history than requested produces a misleadingly
    # short report instead of an error (this is exactly what silently turned a
    # 2025-07..2026-07 request into a 2-day replay before this check existed) —
    # `POST /market-data/backfill` only pulls the most recent `count` bars
    # unless `start` is passed, so a stale/partial DB is easy to end up with.
    # 4 days tolerates weekend/holiday gaps without a per-symbol trading
    # calendar.
    earliest = entry_bars[0].time
    if earliest - start > timedelta(days=4):
        raise NoHistoryError(
            f"{symbol} {entry_tf.value} history only goes back to {earliest.date()}, but the "
            f"requested period starts {start.date()} — call "
            f"POST /market-data/backfill with start={start.date()} to pull the "
            "missing range before backtesting"
        )

    spec = _resolve_symbol_spec(symbol, session_factory, symbol_config)
    replay = ReplayMarketDataPort(symbol, candles, spec)

    event_bus = EventBus()
    spread_gate = SpreadGate({symbol: symbol_config} if symbol_config is not None else {})
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
        contract_size=spec.contract_size,
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
        clock=clock,
        context_builder=CachedContextBuilder(candles),
    )

    activity_capture = _ActivityCapture(clock)
    activity_logger = logging.getLogger("src")
    activity_logger.addHandler(activity_capture)
    # A caller that never ran `configure_logging`/`logging.basicConfig` (e.g.
    # a test, or run_backtest() invoked directly) leaves the root logger at
    # its default WARNING level, which silently drops every INFO decision
    # log before it reaches this handler — force INFO here so activity_log
    # is populated regardless of whether the process configured logging.
    original_level = activity_logger.level
    if original_level == logging.NOTSET or original_level > logging.INFO:
        activity_logger.setLevel(logging.INFO)
    try:
        logger.info(
            "backtest starting: strategy=%s symbol=%s period=%s entry_tf=%s bars=%d "
            "starting_balance=%.2f",
            strategy_name,
            symbol,
            period,
            entry_tf.value,
            len(entry_bars),
            starting_balance,
        )
        tz = ZoneInfo(timezone)
        current_day = entry_bars[0].close_time.astimezone(tz).date()
        for candle in entry_bars:
            replay.advance_to(candle.close_time)
            clock_box["now"] = candle.close_time
            bar_day = candle.close_time.astimezone(tz).date()
            if bar_day != current_day:
                current_day = bar_day
                _auto_resume_daily_breaker(risk_manager)
            await _check_stops(order_service, symbol, candle)
            await trade_engine.on_candle_closed(
                CandleClosed(symbol=symbol, timeframe=entry_tf.value, occurred_at=candle.close_time)
            )

        await _force_close_open_positions(order_service, symbol, entry_bars[-1])
    finally:
        activity_logger.removeHandler(activity_capture)
        activity_logger.setLevel(original_level)

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
        activity_log=tuple(activity_capture.entries),
        signals=extract_signals(activity_capture.entries),
        min_rr=resolved_min_rr,
        risk_per_trade_pct=risk_caps.risk_per_trade_pct,
        daily_loss_limit_pct=risk_caps.daily_loss_limit_pct,
        max_open_positions=risk_caps.max_open_positions,
        max_trades_per_day=risk_caps.max_trades_per_day,
        consecutive_loss_pause=risk_caps.consecutive_loss_pause,
        min_lot_fallback_enabled=risk_caps.min_lot_fallback_enabled,
        max_risk_per_trade_pct=risk_caps.max_risk_per_trade_pct,
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


def _resolve_symbol_spec(
    symbol: str,
    session_factory: sessionmaker[Session],
    symbol_config: SymbolTradingConfig | None,
) -> SymbolSpec:
    """Physical broker facts, required (there's no sane default for lot
    sizing). Prefers the `symbol_specs` DB row backfill snapshots from the
    gateway's live symbol_info; falls back to the legacy YAML's physical
    fields for symbols backfilled before that table existed. Raises
    `NoSymbolSpecError` if neither source has this symbol."""
    spec = SymbolSpecRepository(session_factory).get(symbol)
    if spec is not None:
        return spec
    if symbol_config is not None:
        return SymbolSpec(
            point=symbol_config.point,
            digits=symbol_config.digits,
            stops_level=symbol_config.stops_level,
            contract_size=symbol_config.contract_size,
            volume_min=symbol_config.volume_min,
            volume_max=symbol_config.volume_max,
            volume_step=symbol_config.volume_step,
        )
    raise NoSymbolSpecError(
        f"no broker facts known for {symbol!r} — run "
        "POST /market-data/backfill for this symbol first (it snapshots "
        "them from the gateway), or add a legacy configs/symbols/"
        f"{symbol.lower()}.yaml"
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


def _auto_resume_daily_breaker(risk_manager: RiskManager) -> None:
    """Resume a daily-loss circuit-breaker pause at the trading-day boundary.

    Live, the daily-loss breaker stays tripped until the operator resumes via
    the UI/notification. A backtest has no operator, so before this hook a
    single >=limit losing day silently ended the run — a "4-month" report
    could contain one week of trades and months of forced idleness (that is
    exactly how this was found). Resuming at the next day's first bar
    simulates the operator's next-morning resume, which is what the cap's
    "daily" semantics mean.

    Only the daily-loss trip is auto-resumed. The consecutive-loss breaker
    and the kill switch are anomaly/manual stops, not day-scoped — a backtest
    that trips those SHOULD stay halted, and their trip line in the activity
    log is the honest result. The reason-prefix match is the risk manager's
    only public signal for which breaker fired (see `RiskManager.
    record_trade_closed`'s "daily loss ..." wording — engine code is
    read-only to backtest changes per project rules)."""
    status = risk_manager.status
    if status.paused and status.pause_reason.startswith("daily loss"):
        risk_manager.resume()
        logger.info("daily-loss circuit breaker auto-resumed: new trading day (backtest)")


def _default_registry(database_url: str) -> StrategyRegistry:
    """`breakout_v1` plus every strategy the trader has actually built and
    activated — mirrors `container.py`'s startup wiring so `make backtest`/
    the CLI can run a backtest against any AI-generated or hand-edited
    strategy, not just the hardcoded demo one."""
    registry = StrategyRegistry()
    breakout_v1 = BreakoutV1()
    registry.register(breakout_v1.spec.name, breakout_v1)
    breakout_v2 = BreakoutV2()
    registry.register(breakout_v2.spec.name, breakout_v2)
    trend_structure_v1 = TrendStructureV1()
    registry.register(trend_structure_v1.spec.name, trend_structure_v1)
    trend_structure_v2 = TrendStructureV2()
    registry.register(trend_structure_v2.spec.name, trend_structure_v2)
    mean_reversion_v1 = MeanReversionV1()
    registry.register(mean_reversion_v1.spec.name, mean_reversion_v1)
    session_factory = make_session_factory(database_url)
    strategy_versions = StrategyVersionService(
        repository=StrategyVersionRepository(session_factory),
        registry=registry,
        generated_dir=_STRATEGIES_GENERATED_DIR,
    )
    strategy_versions.load_active_into_registry()
    return registry
