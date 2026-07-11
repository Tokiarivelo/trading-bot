"""Trade loop (§6.4, §7.1): the engine's entry point, driven by `CandleClosed`.

On every M5 close: skill selection -> strategy evaluation -> HTF confirmation
-> risk gate & sizing -> order placement. Position management (breakeven,
time-stop) runs every M5 close regardless of timeframe filtering below.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from src.broker.application.account_service import AccountService
from src.broker.application.order_service import OrderService
from src.broker.domain.trading import OrderRejected, Side
from src.engine.application.context import build_market_context
from src.engine.application.mtf_confirm import confirm
from src.engine.application.position_manager import PositionManager
from src.engine.application.risk_manager import RiskManager
from src.engine.domain.models import EngineStatus
from src.engine.ports.strategy_source import StrategySourcePort
from src.market_data.domain.models import MarketDataUnavailable, Timeframe
from src.market_data.ports.market_data import MarketDataPort
from src.shared.events.definitions import CandleClosed, PositionClosed
from src.skills.ports.skill_selector import SkillSelectorPort

logger = logging.getLogger(__name__)

DEFAULT_CONTEXT_BARS = 200


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
        confirmation_timeframes: tuple[str, ...],
        enabled: bool = True,
        context_bars: int = DEFAULT_CONTEXT_BARS,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._market_data = market_data
        self._order_service = order_service
        self._account = account
        self._risk_manager = risk_manager
        self._position_manager = position_manager
        self._skill_selector = skill_selector
        self._strategy_source = strategy_source
        self._entry_timeframe = entry_timeframe
        self._confirmation_timeframes = confirmation_timeframes
        self._enabled = enabled
        self._context_bars = context_bars
        self._clock = clock

    @property
    def status(self) -> EngineStatus:
        return replace(self._risk_manager.status, enabled=self._enabled)

    async def on_candle_closed(self, event: CandleClosed) -> None:
        if event.timeframe == self._entry_timeframe:
            await self._position_manager.on_candle_closed(event.symbol)
        if not self._enabled or event.timeframe != self._entry_timeframe:
            return
        await self._try_enter(event.symbol)

    async def on_position_closed(self, event: PositionClosed) -> None:
        balance = await self._current_balance()
        self._risk_manager.record_trade_closed(event.profit, balance=balance, now=self._clock())

    async def kill_switch(self) -> None:
        """Close every open position and pause the engine (F kill switch)."""
        self._risk_manager.kill()
        for position in await self._order_service.get_positions():
            try:
                await self._order_service.close_position(position.ticket)
            except OrderRejected:
                logger.exception("kill switch: failed to close ticket=%d", position.ticket)

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

    async def _try_enter(self, symbol: str) -> None:
        now = self._clock()
        decision = self._skill_selector.select(symbol, now)
        if not decision.allowed:
            logger.info("skill blocked entry: %s reason=%s", symbol, decision.reason)
            return

        strategy = self._strategy_source.get(decision.strategy_name)
        if strategy is None:
            logger.warning(
                "no strategy registered: symbol=%s wants=%s", symbol, decision.strategy_name
            )
            return
        if symbol not in strategy.spec.symbols:
            return

        open_positions = await self._order_service.get_positions()
        pretrade = self._risk_manager.check_pretrade(len(open_positions), now)
        if not pretrade.approved:
            logger.info("risk gate blocked entry: %s reason=%s", symbol, pretrade.reason)
            return

        timeframes = (self._entry_timeframe, *self._confirmation_timeframes)
        try:
            candles_by_tf = {
                tf: await self._market_data.get_candles(
                    symbol, Timeframe(tf), self._context_bars
                )
                for tf in timeframes
            }
            info = await self._market_data.get_symbol_info(symbol)
        except MarketDataUnavailable as exc:
            logger.warning("market data unavailable, skipping entry check: %s %s", symbol, exc)
            return

        ctx = build_market_context(symbol, candles_by_tf, info.spread_points)
        signal = strategy.evaluate(ctx)
        if signal is None:
            return

        confirmed, veto_reason = confirm(signal.direction, ctx, self._confirmation_timeframes)
        if not confirmed:
            logger.info(
                "signal vetoed by HTF: %s %s reason=%s", symbol, signal.direction.value, veto_reason
            )
            return

        side = Side(signal.direction.value)
        reference_price = info.ask if side is Side.BUY else info.bid
        sign = 1 if side is Side.BUY else -1
        sl_price = reference_price - sign * signal.sl_points
        tp_price = reference_price + sign * signal.tp_points

        balance = await self._current_balance()
        if balance is None:
            logger.info("no account connected, skipping entry: %s", symbol)
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
            logger.info("risk sizing rejected entry: %s reason=%s", symbol, sizing.reason)
            return

        try:
            await self._order_service.open_position(
                symbol,
                side,
                sizing.volume,
                sl=sl_price,
                tp=tp_price,
                comment=signal.reason[:255],
                strategy_version=f"{strategy.spec.name}:v{strategy.spec.version}",
                skill=decision.skill_name,
            )
        except OrderRejected:
            return  # spread/RR gate already logged the veto inside order_service
        self._risk_manager.record_trade_opened(now)
