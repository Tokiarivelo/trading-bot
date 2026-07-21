"""Trade loop (§6.4, §7.1): the engine's entry point, driven by `CandleClosed`.

On every candle close: each active bot whose strategy's own
`spec.entry_timeframe` matches the closed timeframe runs skill selection ->
strategy evaluation -> HTF confirmation -> risk gate & sizing -> order
placement. This is what lets M1 scalp and M15 swing strategies fire live —
the engine-level `entry_timeframe` config is only the default cadence for
position management and for reporting bots that can't be resolved to a
strategy. Position management (breakeven, time-stop) still runs every
engine-entry-TF (M5) close regardless of the filtering below.

HTF confirmation is per-bot, not a fixed engine-wide list: the veto
timeframe is always the single timeframe immediately above the bot's own
`spec.entry_timeframe` (`Timeframe.next_up`) — an M1 bot is vetoed by M5,
an M5 bot by M15, and so on. There is no separate global config for this;
two bots entering on different timeframes get different veto timeframes.
"""

from __future__ import annotations

import copy
import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from src.broker.application.account_service import AccountService
from src.broker.application.order_service import OrderService
from src.broker.domain.trading import OrderRejected, Position, Side
from src.engine.application.context import build_market_context
from src.engine.application.mtf_confirm import confirm
from src.engine.application.position_manager import PositionManager
from src.engine.application.risk_manager import RiskManager
from src.engine.domain.models import EngineStatus
from src.engine.ports.strategy_source import StrategySourcePort
from src.market_data.domain.models import Candle, MarketDataUnavailable, SymbolInfo, Timeframe
from src.market_data.ports.market_data import MarketDataPort
from src.shared.events.bus import EventBus
from src.shared.events.definitions import (
    CandleClosed,
    CircuitBreakerTripped,
    NewsWindowEntered,
    PositionClosed,
)
from src.skills.ports.skill_selector import SkillDecision, SkillSelectorPort
from src.strategies.domain.models import Direction, MarketContext, Signal, Strategy

logger = logging.getLogger(__name__)

DEFAULT_CONTEXT_BARS = 200


def _veto_timeframe(strategy: Strategy) -> str | None:
    """The bot's own HTF veto timeframe: the one immediately above its
    `entry_timeframe`. `None` for a bot already entering on `MN` (nothing to
    veto against above it) or for a bot with `spec.htf_veto=False` (opted
    out — see `StrategySpec.htf_veto`)."""
    if not strategy.spec.htf_veto:
        return None
    above = Timeframe(strategy.spec.entry_timeframe).next_up()
    return above.value if above is not None else None


def _effective_strategy(strategy: Strategy, decision: SkillDecision) -> Strategy:
    """Per-bot view of `strategy` with this decision's param/htf_veto
    overrides merged in (see `NormalSkill.param_overrides`/`htf_veto_override`)
    — a fresh shallow copy, since `StrategyRegistry` stores one `Strategy`
    instance shared by every bot on this strategy family; mutating it in
    place would leak one bot's overrides onto every other bot trading the
    same strategy."""
    if not decision.param_overrides and decision.htf_veto_override is None:
        return strategy
    merged_params = {**strategy.spec.params, **decision.param_overrides}
    htf_veto = (
        decision.htf_veto_override
        if decision.htf_veto_override is not None
        else strategy.spec.htf_veto
    )
    effective = copy.copy(strategy)
    effective.spec = replace(strategy.spec, params=merged_params, htf_veto=htf_veto)
    return effective


class TradeEngine:
    def __init__(
        self,
        *,
        market_data: MarketDataPort,
        order_service: OrderService,
        account: AccountService,
        risk_manager: RiskManager,
        position_manager: PositionManager,
        skill_selector: SkillSelectorPort,
        strategy_source: StrategySourcePort,
        entry_timeframe: str,
        event_bus: EventBus | None = None,
        enabled: bool = True,
        context_bars: int = DEFAULT_CONTEXT_BARS,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        context_builder: Callable[
            [str, dict[str, list[Candle]], float], MarketContext
        ] = build_market_context,
    ) -> None:
        self._market_data = market_data
        self._order_service = order_service
        self._account = account
        self._risk_manager = risk_manager
        self._position_manager = position_manager
        self._skill_selector = skill_selector
        self._strategy_source = strategy_source
        self._entry_timeframe = entry_timeframe
        self._event_bus = event_bus
        self._enabled = enabled
        self._context_bars = context_bars
        self._clock = clock
        # Swappable only so the backtest runner can serve cached DataFrame
        # slices over replay history instead of rebuilding frames on every
        # bar; the frames it produces are value-identical to
        # `build_market_context`'s (see backtest/adapters/context_builder.py).
        self._context_builder = context_builder

    @property
    def status(self) -> EngineStatus:
        return replace(self._risk_manager.status, enabled=self._enabled)

    async def on_candle_closed(self, event: CandleClosed) -> None:
        if event.timeframe == self._entry_timeframe:
            await self._position_manager.on_candle_closed(event.symbol)
        if not self._enabled:
            return
        await self._try_enter(event.symbol, event.timeframe)

    async def on_position_closed(self, event: PositionClosed) -> None:
        balance = await self._current_balance()
        was_paused = self._risk_manager.paused
        self._risk_manager.record_trade_closed(event.profit, balance=balance, now=self._clock())
        if not was_paused and self._risk_manager.paused:
            await self._publish_pause_alert()

    async def kill_switch(self) -> None:
        """Close every open position and pause the engine (F kill switch)."""
        self._risk_manager.kill()
        await self._publish_pause_alert()
        for position in await self._order_service.get_positions():
            try:
                await self._order_service.close_position(position.ticket)
            except OrderRejected:
                logger.exception("kill switch: failed to close ticket=%d", position.ticket)

    async def _publish_pause_alert(self) -> None:
        if self._event_bus is None:
            return
        await self._event_bus.publish(
            CircuitBreakerTripped(reason=self._risk_manager.status.pause_reason)
        )

    async def on_news_window_entered(self, event: NewsWindowEntered) -> None:
        """Pre-news flatten (§6.6, §8): closes open positions in the news
        skill's `symbols` when `pre_event.close_all` requested it. Unlike
        `kill_switch`, this never pauses the engine — new-entry blocking for
        the window is handled entirely by `NewsSkillSelector` returning
        `allowed=False`."""
        if not event.close_all:
            return
        for symbol in event.symbols:
            for position in await self._order_service.get_positions(symbol):
                try:
                    await self._order_service.close_position(position.ticket)
                except OrderRejected:
                    logger.exception(
                        "news flatten: failed to close ticket=%d ahead of %s",
                        position.ticket,
                        event.event_name,
                    )
            logger.info("news flatten: closed %s positions ahead of %s", symbol, event.event_name)

    def resume(self) -> None:
        self._risk_manager.resume()

    async def _current_balance(self) -> float | None:
        try:
            status = await self._account.status()
        except Exception:
            logger.exception("could not fetch account status")
            return None
        account = status.get("account")
        return account["balance"] if account else None

    async def _try_enter(self, symbol: str, timeframe: str) -> None:
        now = self._clock()
        decisions = self._skill_selector.select_all(symbol, now)
        if not decisions:
            if timeframe == self._entry_timeframe:
                logger.info("ENTRY BLOCKED (skill routing): %s — no active bots", symbol)
            return

        candidates: list[tuple[SkillDecision, Strategy]] = []
        for decision in decisions:
            strategy = (
                self._strategy_source.get(decision.strategy_name)
                if decision.strategy_name
                else None
            )
            if strategy is not None:
                if symbol not in strategy.spec.symbols:
                    continue
                if strategy.spec.entry_timeframe != timeframe:
                    continue  # this bot enters on a different timeframe's closes
            elif timeframe != self._entry_timeframe:
                # Bots we can't resolve to a strategy (blocked with no
                # strategy_name, or unregistered) get reported once per
                # engine-entry-TF close, not on every finer close.
                continue
            if not decision.allowed:
                logger.info(
                    "ENTRY BLOCKED (skill routing): %s [%s] — %s",
                    symbol,
                    decision.skill_name,
                    decision.reason,
                )
                continue
            if strategy is None:
                logger.warning(
                    "ENTRY BLOCKED (no strategy registered): %s [%s] wants strategy=%s",
                    symbol,
                    decision.skill_name,
                    decision.strategy_name,
                )
                continue
            # Applied here, before the veto-timeframe candle prefetch below,
            # so a bot whose override changes htf_veto has the right
            # timeframe's candles already fetched by the time _enter_for_bot
            # runs confirm() against it.
            candidates.append((decision, _effective_strategy(strategy, decision)))
        if not candidates:
            return

        # Fetched once per symbol per candle close — every bot on this
        # symbol evaluates against the same bars/spread, so N bots cost the
        # same one round trip a single bot would. The context carries the
        # closed entry timeframe, each candidate strategy's own confirmation
        # timeframes, and each candidate's own HTF-veto timeframe (the one
        # immediately above its entry_timeframe).
        timeframes = dict.fromkeys(
            (
                timeframe,
                *(
                    tf
                    for _, strategy in candidates
                    for tf in strategy.spec.confirmation_timeframes
                ),
                *(
                    veto_tf
                    for _, strategy in candidates
                    if (veto_tf := _veto_timeframe(strategy)) is not None
                ),
            )
        )
        try:
            candles_by_tf = {
                tf: await self._market_data.get_candles(symbol, Timeframe(tf), self._context_bars)
                for tf in timeframes
            }
            info = await self._market_data.get_symbol_info(symbol)
        except MarketDataUnavailable as exc:
            logger.warning("ENTRY SKIPPED (no market data): %s — %s", symbol, exc)
            return

        ctx = self._context_builder(symbol, candles_by_tf, info.spread_points)
        for decision, strategy in candidates:
            await self._enter_for_bot(symbol, decision, strategy, ctx, info, now)

    async def _enter_for_bot(
        self,
        symbol: str,
        decision: SkillDecision,
        strategy: Strategy,
        ctx: MarketContext,
        info: SymbolInfo,
        now: datetime,
    ) -> None:
        # Fetched fresh per bot (not hoisted above the candidates loop) so a
        # bot later in this same candle sees the position(s) an earlier bot
        # on the same symbol just opened.
        open_positions = await self._order_service.get_positions()

        # Evaluated ahead of the pretrade gate (unlike previously) so a
        # `close_on_opposite_signal` strategy can free up its own slot below
        # before the max-open-positions cap is checked against the count.
        signal = strategy.evaluate(ctx)
        if signal is None:
            return
        logger.info(
            "SIGNAL: %s %s via strategy=%s skill=%s — %s",
            symbol,
            signal.direction.value,
            strategy.spec.name,
            decision.skill_name,
            signal.reason,
        )

        if strategy.spec.close_on_opposite_signal:
            open_positions = await self._close_opposite_position(
                symbol, decision, strategy, signal, open_positions
            )

        pretrade = self._risk_manager.check_pretrade(len(open_positions), now)
        if not pretrade.approved:
            logger.info(
                "ENTRY BLOCKED (risk gate): %s [%s] — %s",
                symbol,
                decision.skill_name,
                pretrade.reason,
            )
            return

        veto_tf = _veto_timeframe(strategy)
        veto_timeframes = (veto_tf,) if veto_tf is not None else ()
        confirmed, veto_reason = confirm(signal.direction, ctx, veto_timeframes)
        if not confirmed:
            logger.info(
                "ENTRY BLOCKED (HTF veto): %s %s [%s] — %s",
                symbol,
                signal.direction.value,
                decision.skill_name,
                veto_reason,
            )
            return

        side = Side(signal.direction.value)
        reference_price = info.ask if side is Side.BUY else info.bid
        sign = 1 if side is Side.BUY else -1
        sl_price = reference_price - sign * signal.sl_points
        tp_price = reference_price + sign * signal.tp_points

        balance = await self._current_balance()
        if balance is None:
            logger.info("ENTRY SKIPPED (no account connected): %s", symbol)
            return

        sizing = self._risk_manager.size_position(
            balance=balance,
            sl_distance_price=abs(reference_price - sl_price),
            contract_size=info.contract_size,
            volume_min=info.volume_min,
            volume_max=info.volume_max,
            volume_step=info.volume_step,
            risk_multiplier=decision.risk_multiplier,
        )
        if not sizing.approved:
            logger.info(
                "ENTRY REJECTED (risk sizing): %s %s [%s] — %s (balance=%.2f, sl_distance=%.5f, "
                "risk_multiplier=%.2f)",
                symbol,
                side.value,
                decision.skill_name,
                sizing.reason,
                balance,
                abs(reference_price - sl_price),
                decision.risk_multiplier,
            )
            return
        logger.info(
            "SIZING OK: %s %s %.2f lots [%s] (balance=%.2f, risk_multiplier=%.2f)",
            symbol,
            side.value,
            sizing.volume,
            decision.skill_name,
            balance,
            decision.risk_multiplier,
        )

        zone = signal.zone
        try:
            await self._order_service.open_position(
                symbol,
                side,
                sizing.volume,
                sl=sl_price,
                tp=tp_price,
                comment=signal.reason[:29],
                strategy_version=f"{strategy.spec.name}:v{strategy.spec.version}",
                skill=decision.skill_name,
                magic=decision.magic,
                max_spread_points=decision.max_spread_points,
                zone_kind=zone.kind.value if zone is not None else None,
                zone_price_low=zone.price_low if zone is not None else None,
                zone_price_high=zone.price_high if zone is not None else None,
                zone_time_start=zone.time_start if zone is not None else None,
                zone_time_end=zone.time_end if zone is not None else None,
                pattern=signal.pattern,
                structure=tuple((p.label.value, p.price, p.time) for p in signal.structure),
            )
        except OrderRejected:
            return  # spread/RR gate already logged the veto inside order_service
        self._risk_manager.record_trade_opened(now)

    async def _close_opposite_position(
        self,
        symbol: str,
        decision: SkillDecision,
        strategy: Strategy,
        signal: Signal,
        open_positions: list[Position],
    ) -> list[Position]:
        """For a `close_on_opposite_signal` strategy: closes this bot's own
        open position on `symbol` (matched by `magic`, so other bots' or
        manually-opened positions are untouched) when its side opposes the
        fresh `signal` — a signal-flip exit instead of waiting for
        SL/TP/time-stop. Returns `open_positions` with the closed ticket
        removed so the caller's pretrade gate sees the freed slot right
        away, in the same pass that opens the new position."""
        opposite_side = Side.SELL if signal.direction == Direction.BUY else Side.BUY
        position = next(
            (
                p
                for p in open_positions
                if p.symbol == symbol and p.magic == decision.magic and p.side is opposite_side
            ),
            None,
        )
        if position is None:
            return open_positions
        try:
            await self._order_service.close_position(position.ticket)
        except OrderRejected:
            logger.exception(
                "SIGNAL FLIP: failed to close ticket=%d %s ahead of new %s signal",
                position.ticket,
                symbol,
                signal.direction.value,
            )
            return open_positions
        logger.info(
            "SIGNAL FLIP: %s ticket=%d %s closed [%s] — new %s signal via strategy=%s",
            symbol,
            position.ticket,
            position.side.value,
            decision.skill_name,
            signal.direction.value,
            strategy.spec.name,
        )
        return [p for p in open_positions if p.ticket != position.ticket]
