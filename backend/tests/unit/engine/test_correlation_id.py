"""Correlation id (OBSERVABILITY_PLAN.md Phase 5): `TradeEngine._try_enter`
mints a fresh `signal_id` per candidate and binds it via `current_signal_id`
(`shared/logging/account_context.py`) around that candidate's whole
`_enter_for_bot` call — including the `OrderService.open_position` call it
makes. These tests assert on `current_signal_id.get()` as observed *inside*
the fake order service, not just on the `signal_id=` parameter it also
receives, since the whole point of the ContextVar is that downstream log
lines pick it up without every call site threading it through explicitly."""

from src.shared.events.definitions import CandleClosed
from src.shared.logging.account_context import current_signal_id
from src.skills.ports.skill_selector import SkillDecision
from tests.unit.engine.test_trade_loop import (
    BUY_SIGNAL,
    FakeSkillSelector,
    FakeStrategy,
    FakeStrategySource,
    make_engine,
)


async def test_signal_id_is_bound_in_context_when_order_service_is_called():
    engine, order_service, *_ = make_engine()

    await engine.on_candle_closed(CandleClosed(symbol="XAUUSD", timeframe="M5"))

    assert len(order_service.opened) == 1
    seen_in_context = order_service.signal_id_in_context[0]
    assert seen_in_context is not None
    # The ContextVar's value and the explicit `signal_id=` parameter are the
    # exact same id — proof the binding wraps the real call, not a decoy.
    assert seen_in_context == order_service.signal_ids[0]


async def test_two_bots_on_one_symbol_get_distinct_signal_ids():
    decisions = [
        SkillDecision(allowed=True, skill_name="normal/xauusd/a", strategy_name="a", magic=111),
        SkillDecision(allowed=True, skill_name="normal/xauusd/b", strategy_name="b", magic=222),
    ]
    strategy_source = FakeStrategySource(
        {"a": FakeStrategy(BUY_SIGNAL), "b": FakeStrategy(BUY_SIGNAL)}
    )
    engine, order_service, *_ = make_engine(
        skill_selector=FakeSkillSelector(decisions), strategy_source=strategy_source
    )

    await engine.on_candle_closed(CandleClosed(symbol="XAUUSD", timeframe="M5"))

    assert len(order_service.opened) == 2
    first_id, second_id = order_service.signal_id_in_context
    assert first_id is not None
    assert second_id is not None
    assert first_id != second_id  # each candidate's binding is its own, not shared/leaked
    assert order_service.signal_ids == [first_id, second_id]


async def test_context_is_clean_before_and_after_a_candle_close():
    engine, order_service, *_ = make_engine()
    assert current_signal_id.get() is None

    await engine.on_candle_closed(CandleClosed(symbol="XAUUSD", timeframe="M5"))

    # `bind_signal_id` resets on the way out of `_try_enter`'s loop body —
    # nothing about processing this candle leaks into whatever runs next in
    # the same task (e.g. another symbol's candle, or position management).
    assert current_signal_id.get() is None
    assert len(order_service.opened) == 1
