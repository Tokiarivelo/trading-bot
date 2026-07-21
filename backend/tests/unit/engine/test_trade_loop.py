from datetime import UTC, datetime

from src.broker.domain.trading import ExecutionResult, OrderRejected, Position, Side
from src.engine.application.risk_manager import RiskManager
from src.engine.application.trade_loop import TradeEngine, _veto_timeframe
from src.engine.domain.models import RiskCaps
from src.market_data.domain.models import Candle, SymbolInfo, Timeframe
from src.shared.events.bus import EventBus
from src.shared.events.definitions import (
    CandleClosed,
    CircuitBreakerTripped,
    NewsWindowEntered,
    PositionClosed,
)
from src.skills.ports.skill_selector import SkillDecision
from src.strategies.domain.models import Direction, MarketContext, Signal, StrategySpec

XAUUSD_INFO = SymbolInfo(
    symbol="XAUUSD",
    bid=2400.00,
    ask=2400.30,
    spread_points=30,
    point=0.01,
    digits=2,
    stops_level=10,
    contract_size=100.0,
    volume_min=0.01,
    volume_max=100.0,
    volume_step=0.01,
)

CAPS = RiskCaps(
    risk_per_trade_pct=1.0,
    daily_loss_limit_pct=5.0,
    max_open_positions=5,
    max_trades_per_day=20,
    consecutive_loss_pause=5,
)

ALLOWED_DECISION = SkillDecision(
    allowed=True,
    skill_name="normal/xauusd/fake",
    strategy_name="fake",
    risk_multiplier=1.0,
    magic=999,
)
BUY_SIGNAL = Signal(direction=Direction.BUY, sl_points=10.0, tp_points=15.0, reason="test buy")


def _uptrend_candles(symbol: str, timeframe: Timeframe, count: int) -> list[Candle]:
    base = datetime(2026, 7, 11, 8, 0, tzinfo=UTC)
    return [
        Candle(
            symbol=symbol,
            timeframe=timeframe,
            time=base,
            open=2400.0,
            high=2401.0,
            low=2399.0,
            close=2400.0 + i * 0.5,
            tick_volume=100,
            spread_points=30,
        )
        for i in range(count)
    ]


def _downtrend_candles(symbol: str, timeframe: Timeframe, count: int) -> list[Candle]:
    base = datetime(2026, 7, 11, 8, 0, tzinfo=UTC)
    return [
        Candle(
            symbol=symbol,
            timeframe=timeframe,
            time=base,
            open=2450.0,
            high=2451.0,
            low=2449.0,
            close=2450.0 - i * 0.5,
            tick_volume=100,
            spread_points=30,
        )
        for i in range(count)
    ]


class FakeMarketData:
    def __init__(self, info: SymbolInfo = XAUUSD_INFO, bar_count: int = 5, downtrend: bool = False):
        self.info = info
        self.bar_count = bar_count
        self._downtrend = downtrend
        self.requested_timeframes: list[Timeframe] = []

    async def get_candles(self, symbol, timeframe, count):
        self.requested_timeframes.append(timeframe)
        builder = _downtrend_candles if self._downtrend else _uptrend_candles
        return builder(symbol, timeframe, self.bar_count)

    async def get_tick(self, symbol):
        raise NotImplementedError

    async def get_symbol_info(self, symbol):
        return self.info


class FakeOrderService:
    def __init__(self, positions: list[Position] | None = None, raise_on_open=None):
        self._positions = positions or []
        self.opened: list[dict] = []
        self.closed: list[int] = []
        self._raise_on_open = raise_on_open

    async def get_positions(self, symbol=None):
        return list(self._positions)

    async def open_position(
        self,
        symbol,
        side,
        volume,
        sl=None,
        tp=None,
        comment="",
        strategy_version=None,
        skill=None,
        magic=0,
        max_spread_points=None,
        zone_kind=None,
        zone_price_low=None,
        zone_price_high=None,
        zone_time_start=None,
        zone_time_end=None,
        pattern=None,
        structure=(),
    ):
        if self._raise_on_open:
            raise self._raise_on_open
        ticket = len(self.opened) + 1
        self.opened.append(
            dict(
                symbol=symbol,
                side=side,
                volume=volume,
                sl=sl,
                tp=tp,
                comment=comment,
                strategy_version=strategy_version,
                skill=skill,
                magic=magic,
                max_spread_points=max_spread_points,
                zone_kind=zone_kind,
                zone_price_low=zone_price_low,
                zone_price_high=zone_price_high,
                zone_time_start=zone_time_start,
                zone_time_end=zone_time_end,
                pattern=pattern,
                structure=structure,
            )
        )
        # Reflected in the next get_positions() call, same as a real broker
        # would — lets a later bot's pretrade risk check, in the same
        # candle close, see an earlier bot's just-opened position.
        self._positions.append(
            Position(
                ticket=ticket,
                symbol=symbol,
                side=side,
                volume=volume,
                open_price=2400.30 if side is Side.BUY else 2400.00,
                sl=sl,
                tp=tp,
                open_time=datetime.now(UTC),
                profit=0.0,
                comment=comment,
                magic=magic,
            )
        )
        return ExecutionResult(
            ticket=ticket,
            symbol=symbol,
            side=side,
            volume=volume,
            price=2400.30 if side is Side.BUY else 2400.00,
            sl=sl,
            tp=tp,
            time=datetime.now(UTC),
            spread_points=30,
            comment=comment,
            magic=magic,
        )

    async def close_position(self, ticket, volume=None):
        self.closed.append(ticket)
        return ExecutionResult(
            ticket=ticket,
            symbol="XAUUSD",
            side=Side.BUY,
            volume=volume or 0.1,
            price=2400.0,
            sl=None,
            tp=None,
            time=datetime.now(UTC),
            spread_points=30,
            profit=0.0,
        )

    async def modify_position(self, ticket, sl, tp):
        pass


class FakeAccountService:
    def __init__(self, balance: float | None = 10_000.0):
        self.balance = balance

    async def status(self):
        account = {"balance": self.balance} if self.balance is not None else None
        return {"account": account}


class FakePositionManager:
    def __init__(self):
        self.calls: list[str] = []

    async def on_candle_closed(self, symbol):
        self.calls.append(symbol)


class FakeSkillSelector:
    def __init__(self, decisions: list[SkillDecision]):
        self.decisions = decisions

    def select_all(self, symbol, now):
        return self.decisions


class FakeStrategy:
    def __init__(
        self,
        signal: Signal | None,
        symbols: tuple[str, ...] = ("XAUUSD",),
        entry_timeframe: str = "M5",
        confirmation_timeframes: tuple[str, ...] = ("H1", "H4"),
        params: dict | None = None,
        htf_veto: bool = True,
        close_on_opposite_signal: bool = False,
    ):
        self.spec = StrategySpec(
            name="fake",
            version=1,
            symbols=symbols,
            entry_timeframe=entry_timeframe,
            confirmation_timeframes=confirmation_timeframes,
            params=params if params is not None else {},
            htf_veto=htf_veto,
            close_on_opposite_signal=close_on_opposite_signal,
        )
        self._signal = signal

    def evaluate(self, ctx: MarketContext) -> Signal | None:
        return self._signal


class ThresholdFakeStrategy(FakeStrategy):
    """A strategy whose signal depends on `self.spec.params["threshold"]`,
    read fresh on every `evaluate()` call — mirrors how real generated
    strategies read `self.spec.params`, so per-bot param overrides can be
    exercised without a real generated strategy file."""

    def evaluate(self, ctx: MarketContext) -> Signal | None:
        if self.spec.params.get("threshold", 1) <= 0:
            return BUY_SIGNAL
        return None


class FakeStrategySource:
    def __init__(self, strategies: dict[str, object]):
        self._strategies = strategies

    def get(self, name):
        return self._strategies.get(name)


def make_engine(
    *,
    market_data=None,
    order_service=None,
    account=None,
    position_manager=None,
    skill_selector=None,
    strategy=None,
    strategy_source=None,
    enabled=True,
    risk_manager=None,
    context_bars=5,
    event_bus=None,
):
    market_data = market_data or FakeMarketData(bar_count=context_bars)
    order_service = order_service or FakeOrderService()
    account = account or FakeAccountService()
    position_manager = position_manager or FakePositionManager()
    skill_selector = skill_selector or FakeSkillSelector([ALLOWED_DECISION])
    strategy = strategy if strategy is not None else FakeStrategy(BUY_SIGNAL)
    strategy_source = strategy_source or FakeStrategySource({"fake": strategy})
    risk_manager = risk_manager or RiskManager(caps=CAPS, timezone="UTC")
    event_bus = event_bus if event_bus is not None else EventBus()

    engine = TradeEngine(
        market_data=market_data,
        order_service=order_service,
        account=account,
        risk_manager=risk_manager,
        position_manager=position_manager,
        skill_selector=skill_selector,
        strategy_source=strategy_source,
        entry_timeframe="M5",
        event_bus=event_bus,
        enabled=enabled,
        context_bars=context_bars,
    )
    return engine, order_service, risk_manager, position_manager


async def test_successful_entry_opens_position_with_strategy_and_skill():
    engine, order_service, risk_manager, position_manager = make_engine()
    await engine.on_candle_closed(CandleClosed(symbol="XAUUSD", timeframe="M5"))

    assert len(order_service.opened) == 1
    order = order_service.opened[0]
    assert order["side"] is Side.BUY
    assert order["sl"] == 2400.30 - 10.0
    assert order["tp"] == 2400.30 + 15.0
    assert order["strategy_version"] == "fake:v1"
    assert order["skill"] == "normal/xauusd/fake"
    assert order["magic"] == 999
    assert risk_manager.status.trades_today == 1
    assert position_manager.calls == ["XAUUSD"]


async def test_non_entry_timeframe_is_ignored():
    engine, order_service, _, position_manager = make_engine()
    await engine.on_candle_closed(CandleClosed(symbol="XAUUSD", timeframe="H1"))

    assert order_service.opened == []
    assert position_manager.calls == []


async def test_disabled_engine_still_manages_positions_but_skips_entries():
    engine, order_service, _, position_manager = make_engine(enabled=False)
    await engine.on_candle_closed(CandleClosed(symbol="XAUUSD", timeframe="M5"))

    assert position_manager.calls == ["XAUUSD"]
    assert order_service.opened == []


async def test_skill_blocked_skips_entry():
    decision = SkillDecision(allowed=False, reason="outside trading session")
    engine, order_service, *_ = make_engine(skill_selector=FakeSkillSelector([decision]))
    await engine.on_candle_closed(CandleClosed(symbol="XAUUSD", timeframe="M5"))

    assert order_service.opened == []


async def test_no_active_bots_skips_entry():
    engine, order_service, *_ = make_engine(skill_selector=FakeSkillSelector([]))
    await engine.on_candle_closed(CandleClosed(symbol="XAUUSD", timeframe="M5"))

    assert order_service.opened == []


async def test_missing_strategy_skips_entry():
    decision = SkillDecision(allowed=True, skill_name="normal/xauusd/x", strategy_name="missing")
    engine, order_service, *_ = make_engine(skill_selector=FakeSkillSelector([decision]))
    await engine.on_candle_closed(CandleClosed(symbol="XAUUSD", timeframe="M5"))

    assert order_service.opened == []


async def test_symbol_not_covered_by_strategy_skips_entry():
    strategy = FakeStrategy(BUY_SIGNAL, symbols=("BTCUSD",))
    engine, order_service, *_ = make_engine(strategy=strategy)
    await engine.on_candle_closed(CandleClosed(symbol="XAUUSD", timeframe="M5"))

    assert order_service.opened == []


async def test_no_signal_skips_entry():
    engine, order_service, *_ = make_engine(strategy=FakeStrategy(None))
    await engine.on_candle_closed(CandleClosed(symbol="XAUUSD", timeframe="M5"))

    assert order_service.opened == []


async def test_htf_veto_skips_entry():
    market_data = FakeMarketData(bar_count=60, downtrend=True)
    engine, order_service, *_ = make_engine(market_data=market_data, context_bars=60)
    await engine.on_candle_closed(CandleClosed(symbol="XAUUSD", timeframe="M5"))

    assert order_service.opened == []


async def test_pretrade_risk_block_skips_entry():
    caps = RiskCaps(
        risk_per_trade_pct=1.0,
        daily_loss_limit_pct=5.0,
        max_open_positions=1,
        max_trades_per_day=20,
        consecutive_loss_pause=5,
    )
    risk_manager = RiskManager(caps=caps, timezone="UTC")
    existing = Position(
        ticket=1,
        symbol="XAUUSD",
        side=Side.BUY,
        volume=0.1,
        open_price=2400.0,
        sl=None,
        tp=None,
        open_time=datetime.now(UTC),
        profit=0.0,
    )
    order_service = FakeOrderService(positions=[existing])
    engine, order_service, risk_manager, _ = make_engine(
        order_service=order_service, risk_manager=risk_manager
    )
    await engine.on_candle_closed(CandleClosed(symbol="XAUUSD", timeframe="M5"))

    assert order_service.opened == []


async def test_order_rejected_does_not_crash_or_record_trade():
    order_service = FakeOrderService(raise_on_open=OrderRejected("spread too wide"))
    engine, order_service, risk_manager, _ = make_engine(order_service=order_service)
    await engine.on_candle_closed(CandleClosed(symbol="XAUUSD", timeframe="M5"))

    assert order_service.opened == []
    assert risk_manager.status.trades_today == 0


async def test_no_account_connected_skips_entry():
    engine, order_service, *_ = make_engine(account=FakeAccountService(balance=None))
    await engine.on_candle_closed(CandleClosed(symbol="XAUUSD", timeframe="M5"))

    assert order_service.opened == []


async def test_kill_switch_pauses_and_closes_all_positions():
    position = Position(
        ticket=1,
        symbol="XAUUSD",
        side=Side.BUY,
        volume=0.1,
        open_price=2400.0,
        sl=None,
        tp=None,
        open_time=datetime.now(UTC),
        profit=0.0,
    )
    order_service = FakeOrderService(positions=[position])
    engine, order_service, risk_manager, _ = make_engine(order_service=order_service)
    await engine.kill_switch()

    assert risk_manager.paused
    assert order_service.closed == [1]


async def test_news_window_entered_flattens_positions_when_close_all():
    position = Position(
        ticket=7,
        symbol="XAUUSD",
        side=Side.BUY,
        volume=0.1,
        open_price=2400.0,
        sl=None,
        tp=None,
        open_time=datetime.now(UTC),
        profit=0.0,
    )
    order_service = FakeOrderService(positions=[position])
    engine, order_service, risk_manager, _ = make_engine(order_service=order_service)

    await engine.on_news_window_entered(
        NewsWindowEntered(event_name="Non-Farm Payrolls", symbols=("XAUUSD",), close_all=True)
    )

    assert order_service.closed == [7]
    assert not risk_manager.paused  # unlike kill_switch, this never pauses the engine


def _collector():
    published: list[CircuitBreakerTripped] = []

    async def handler(event: CircuitBreakerTripped) -> None:
        published.append(event)

    return published, handler


async def test_kill_switch_publishes_circuit_breaker_tripped_once():
    event_bus = EventBus()
    published, handler = _collector()
    event_bus.subscribe(CircuitBreakerTripped, handler)
    engine, *_ = make_engine(event_bus=event_bus)

    await engine.kill_switch()

    assert len(published) == 1
    assert published[0].reason == "manual kill switch"


async def test_consecutive_loss_pause_publishes_circuit_breaker_tripped_once():
    event_bus = EventBus()
    published, handler = _collector()
    event_bus.subscribe(CircuitBreakerTripped, handler)
    risk_manager = RiskManager(caps=CAPS, timezone="UTC")
    engine, *_ = make_engine(risk_manager=risk_manager, event_bus=event_bus)

    for _ in range(CAPS.consecutive_loss_pause):
        await engine.on_position_closed(
            PositionClosed(symbol="XAUUSD", position_id="1", close_price=2400.0, profit=-10.0)
        )

    assert risk_manager.paused
    assert len(published) == 1
    assert "consecutive losses" in published[0].reason


async def test_news_window_entered_does_nothing_when_close_all_false():
    position = Position(
        ticket=7,
        symbol="XAUUSD",
        side=Side.BUY,
        volume=0.1,
        open_price=2400.0,
        sl=None,
        tp=None,
        open_time=datetime.now(UTC),
        profit=0.0,
    )
    order_service = FakeOrderService(positions=[position])
    engine, order_service, *_ = make_engine(order_service=order_service)

    await engine.on_news_window_entered(
        NewsWindowEntered(event_name="CPI", symbols=("XAUUSD",), close_all=False)
    )

    assert order_service.closed == []


def test_resume_clears_pause():
    engine, _, risk_manager, _ = make_engine()
    risk_manager.kill("test")
    engine.resume()

    assert not risk_manager.paused


async def test_on_position_closed_forwards_to_risk_manager():
    engine, _, risk_manager, _ = make_engine(account=FakeAccountService(balance=10_000.0))
    await engine.on_position_closed(
        PositionClosed(symbol="XAUUSD", position_id="1", close_price=2390.0, profit=-50.0)
    )

    assert risk_manager.status.consecutive_losses == 1


def test_status_reports_enabled_flag():
    engine, *_ = make_engine(enabled=False)
    assert engine.status.enabled is False


async def test_m1_entry_strategy_fires_on_m1_close_not_on_m5():
    # Regression: the engine used to evaluate only on its global entry-TF
    # (M5) closes with M5/H1/H4 context, so an M1-entry scalp strategy could
    # never fire live — its `ctx.candles.get("M1")` was always None.
    strategy = FakeStrategy(BUY_SIGNAL, entry_timeframe="M1", confirmation_timeframes=("M5",))
    engine, order_service, *_ = make_engine(strategy=strategy)

    await engine.on_candle_closed(CandleClosed(symbol="XAUUSD", timeframe="M5"))
    assert order_service.opened == []

    await engine.on_candle_closed(CandleClosed(symbol="XAUUSD", timeframe="M1"))
    assert len(order_service.opened) == 1
    assert order_service.opened[0]["strategy_version"] == "fake:v1"


async def test_context_fetch_covers_strategy_confirmation_and_veto_timeframes():
    # own confirmation timeframe (H4) deliberately differs from the veto
    # timeframe (M5, next_up of M1) so the two are unambiguously exercised.
    strategy = FakeStrategy(BUY_SIGNAL, entry_timeframe="M1", confirmation_timeframes=("H4",))
    market_data = FakeMarketData()
    engine, *_ = make_engine(market_data=market_data, strategy=strategy)

    await engine.on_candle_closed(CandleClosed(symbol="XAUUSD", timeframe="M1"))

    assert set(market_data.requested_timeframes) == {
        Timeframe.M1,  # the strategy's entry timeframe (the closed candle)
        Timeframe.H4,  # the strategy's own confirmation timeframe
        Timeframe.M5,  # this bot's HTF-veto timeframe (next_up of M1)
    }


def test_veto_timeframe_is_next_above_entry_timeframe():
    expected = {
        "M1": "M5",
        "M5": "M15",
        "M15": "M30",
        "M30": "H1",
        "H1": "H4",
        "H4": "D1",
        "D1": "W1",
        "W1": "MN",
        "MN": None,
    }
    for entry_tf, veto_tf in expected.items():
        assert _veto_timeframe(FakeStrategy(BUY_SIGNAL, entry_timeframe=entry_tf)) == veto_tf


async def test_mixed_timeframe_bots_each_fire_on_their_own_closes():
    decisions = [
        SkillDecision(allowed=True, skill_name="normal/xauusd/a", strategy_name="a", magic=111),
        SkillDecision(allowed=True, skill_name="normal/xauusd/b", strategy_name="b", magic=222),
    ]
    strategy_source = FakeStrategySource(
        {
            "a": FakeStrategy(BUY_SIGNAL),  # M5 entry
            "b": FakeStrategy(BUY_SIGNAL, entry_timeframe="M1", confirmation_timeframes=("M5",)),
        }
    )
    engine, order_service, *_ = make_engine(
        skill_selector=FakeSkillSelector(decisions), strategy_source=strategy_source
    )

    await engine.on_candle_closed(CandleClosed(symbol="XAUUSD", timeframe="M5"))
    assert [o["magic"] for o in order_service.opened] == [111]

    await engine.on_candle_closed(CandleClosed(symbol="XAUUSD", timeframe="M1"))
    assert [o["magic"] for o in order_service.opened] == [111, 222]


async def test_two_bots_on_one_symbol_each_place_their_own_order():
    decisions = [
        SkillDecision(allowed=True, skill_name="normal/xauusd/a", strategy_name="a", magic=111),
        SkillDecision(allowed=True, skill_name="normal/xauusd/b", strategy_name="b", magic=222),
    ]
    strategy_source = FakeStrategySource(
        {"a": FakeStrategy(BUY_SIGNAL), "b": FakeStrategy(BUY_SIGNAL)}
    )
    engine, order_service, risk_manager, _ = make_engine(
        skill_selector=FakeSkillSelector(decisions), strategy_source=strategy_source
    )

    await engine.on_candle_closed(CandleClosed(symbol="XAUUSD", timeframe="M5"))

    assert len(order_service.opened) == 2
    assert {o["skill"] for o in order_service.opened} == {"normal/xauusd/a", "normal/xauusd/b"}
    assert {o["magic"] for o in order_service.opened} == {111, 222}
    assert risk_manager.status.trades_today == 2


async def test_second_bot_sizing_sees_first_bots_fresh_position():
    # max_open_positions=1 means the second bot in the same candle close
    # must see the first bot's just-opened position and get blocked by the
    # risk gate — proving the pretrade check is re-fetched per bot, not
    # hoisted once for the whole candle.
    caps = RiskCaps(
        risk_per_trade_pct=1.0,
        daily_loss_limit_pct=5.0,
        max_open_positions=1,
        max_trades_per_day=20,
        consecutive_loss_pause=5,
    )
    decisions = [
        SkillDecision(allowed=True, skill_name="normal/xauusd/a", strategy_name="a", magic=111),
        SkillDecision(allowed=True, skill_name="normal/xauusd/b", strategy_name="b", magic=222),
    ]
    strategy_source = FakeStrategySource(
        {"a": FakeStrategy(BUY_SIGNAL), "b": FakeStrategy(BUY_SIGNAL)}
    )
    engine, order_service, risk_manager, _ = make_engine(
        skill_selector=FakeSkillSelector(decisions),
        strategy_source=strategy_source,
        risk_manager=RiskManager(caps=caps, timezone="UTC"),
    )

    await engine.on_candle_closed(CandleClosed(symbol="XAUUSD", timeframe="M5"))

    assert len(order_service.opened) == 1
    assert order_service.opened[0]["magic"] == 111


async def test_param_override_reaches_strategy_evaluate():
    strategy = ThresholdFakeStrategy(None, params={"threshold": 100})
    decision = SkillDecision(
        allowed=True,
        skill_name="normal/xauusd/fake",
        strategy_name="fake",
        magic=999,
        param_overrides={"threshold": 0},
    )
    engine, order_service, *_ = make_engine(
        skill_selector=FakeSkillSelector([decision]),
        strategy_source=FakeStrategySource({"fake": strategy}),
    )

    await engine.on_candle_closed(CandleClosed(symbol="XAUUSD", timeframe="M5"))

    assert len(order_service.opened) == 1
    # The shared StrategyRegistry instance's own spec is never mutated.
    assert strategy.spec.params == {"threshold": 100}


async def test_param_override_absent_keeps_strategy_default_behavior():
    strategy = ThresholdFakeStrategy(None, params={"threshold": 100})
    decision = SkillDecision(
        allowed=True, skill_name="normal/xauusd/fake", strategy_name="fake", magic=999
    )
    engine, order_service, *_ = make_engine(
        skill_selector=FakeSkillSelector([decision]),
        strategy_source=FakeStrategySource({"fake": strategy}),
    )

    await engine.on_candle_closed(CandleClosed(symbol="XAUUSD", timeframe="M5"))

    assert order_service.opened == []


async def test_two_bots_same_strategy_different_param_overrides_do_not_leak():
    # Both bots share one StrategyRegistry-registered Strategy instance —
    # only bot "a"'s override should affect its own evaluation.
    strategy = ThresholdFakeStrategy(None, params={"threshold": 100})
    decisions = [
        SkillDecision(
            allowed=True,
            skill_name="normal/xauusd/a",
            strategy_name="fake",
            magic=111,
            param_overrides={"threshold": 0},
        ),
        SkillDecision(allowed=True, skill_name="normal/xauusd/b", strategy_name="fake", magic=222),
    ]
    engine, order_service, *_ = make_engine(
        skill_selector=FakeSkillSelector(decisions),
        strategy_source=FakeStrategySource({"fake": strategy}),
    )

    await engine.on_candle_closed(CandleClosed(symbol="XAUUSD", timeframe="M5"))

    assert [o["magic"] for o in order_service.opened] == [111]
    assert strategy.spec.params == {"threshold": 100}


async def test_htf_veto_override_forces_veto_on_despite_strategy_default_off():
    market_data = FakeMarketData(bar_count=60, downtrend=True)
    strategy = FakeStrategy(BUY_SIGNAL, htf_veto=False)
    decision = SkillDecision(
        allowed=True,
        skill_name="normal/xauusd/fake",
        strategy_name="fake",
        magic=999,
        htf_veto_override=True,
    )
    engine, order_service, *_ = make_engine(
        market_data=market_data,
        context_bars=60,
        skill_selector=FakeSkillSelector([decision]),
        strategy_source=FakeStrategySource({"fake": strategy}),
    )

    await engine.on_candle_closed(CandleClosed(symbol="XAUUSD", timeframe="M5"))

    assert order_service.opened == []


async def test_htf_veto_override_forces_veto_off_despite_strategy_default_on():
    market_data = FakeMarketData(bar_count=60, downtrend=True)
    strategy = FakeStrategy(BUY_SIGNAL, htf_veto=True)
    decision = SkillDecision(
        allowed=True,
        skill_name="normal/xauusd/fake",
        strategy_name="fake",
        magic=999,
        htf_veto_override=False,
    )
    engine, order_service, *_ = make_engine(
        market_data=market_data,
        context_bars=60,
        skill_selector=FakeSkillSelector([decision]),
        strategy_source=FakeStrategySource({"fake": strategy}),
    )

    await engine.on_candle_closed(CandleClosed(symbol="XAUUSD", timeframe="M5"))

    assert len(order_service.opened) == 1


async def test_close_on_opposite_signal_flips_this_bots_position():
    # An open SELL from this same bot (magic=999, matching ALLOWED_DECISION)
    # plus a fresh BUY signal from a close_on_opposite_signal strategy ->
    # the SELL is closed and the BUY opens in the same pass, instead of
    # waiting for SL/TP/time-stop.
    existing = Position(
        ticket=7,
        symbol="XAUUSD",
        side=Side.SELL,
        volume=0.1,
        open_price=2450.0,
        sl=2460.0,
        tp=2430.0,
        open_time=datetime.now(UTC),
        profit=0.0,
        magic=999,
    )
    order_service = FakeOrderService(positions=[existing])
    strategy = FakeStrategy(BUY_SIGNAL, close_on_opposite_signal=True)
    engine, order_service, risk_manager, _ = make_engine(
        order_service=order_service, strategy=strategy
    )

    await engine.on_candle_closed(CandleClosed(symbol="XAUUSD", timeframe="M5"))

    assert order_service.closed == [7]
    assert len(order_service.opened) == 1
    assert order_service.opened[0]["side"] is Side.BUY
    assert order_service.opened[0]["magic"] == 999


async def test_close_on_opposite_signal_ignores_other_bots_and_manual_positions():
    # A SELL on the same symbol but a different magic (another bot, or a
    # manually-opened position) must never be touched by this bot's flip.
    other_bots_position = Position(
        ticket=8,
        symbol="XAUUSD",
        side=Side.SELL,
        volume=0.1,
        open_price=2450.0,
        sl=2460.0,
        tp=2430.0,
        open_time=datetime.now(UTC),
        profit=0.0,
        magic=111,
    )
    order_service = FakeOrderService(positions=[other_bots_position])
    strategy = FakeStrategy(BUY_SIGNAL, close_on_opposite_signal=True)
    engine, order_service, *_ = make_engine(order_service=order_service, strategy=strategy)

    await engine.on_candle_closed(CandleClosed(symbol="XAUUSD", timeframe="M5"))

    assert order_service.closed == []
    assert len(order_service.opened) == 1


async def test_close_on_opposite_signal_false_leaves_opposite_position_open():
    # Default behavior (unset on every existing strategy): an opposing
    # position from the same bot is left alone; SL/TP/time-stop still own
    # its exit.
    existing = Position(
        ticket=9,
        symbol="XAUUSD",
        side=Side.SELL,
        volume=0.1,
        open_price=2450.0,
        sl=2460.0,
        tp=2430.0,
        open_time=datetime.now(UTC),
        profit=0.0,
        magic=999,
    )
    order_service = FakeOrderService(positions=[existing])
    engine, order_service, *_ = make_engine(order_service=order_service)

    await engine.on_candle_closed(CandleClosed(symbol="XAUUSD", timeframe="M5"))

    assert order_service.closed == []
    assert len(order_service.opened) == 1
