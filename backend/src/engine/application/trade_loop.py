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
from src.engine.domain.volatility import (
    VolatilityConfig,
    VolatilityRegime,
    latest_volatility_regime,
)
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
        volatility_config: VolatilityConfig,
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
        self._volatility_config = volatility_config
        self._volatility_guard_enabled = True
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

    @property
    def volatility_config(self) -> VolatilityConfig:
        return self._volatility_config

    @property
    def volatility_guard_enabled(self) -> bool:
        return self._volatility_guard_enabled

    def set_volatility_guard_enabled(self, enabled: bool) -> None:
        """Live-updates whether the volatility guard (EXTREME-regime entry
        block + SL/TP regime scaling here in `_enter_for_bot`, plus the
        mirrored EXTREME/HIGH position-management rules in
        `PositionManager`) is active — takes effect on the very next entry
        decision. When `False`, entries behave exactly as if
        `volatility_config` didn't exist (`sl_mult`/`tp_mult` both 1.0, no
        EXTREME check). Not persisted: a backend restart reverts to
        `configs/volatility.yaml` (enabled by default)."""
        self._volatility_guard_enabled = enabled
        logger.info("trade engine: volatility guard enabled=%s", enabled)

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

        # Fetched once per symbol per candle close, alongside `info` —
        # balance only changes on a realized close (a `close_on_opposite_
        # signal` exit), never from opening a position, so N candidate bots
        # reuse this one value instead of each round-tripping the gateway
        # (+ keyring read) for it. `_enter_for_bot` re-fetches it, but only
        # when `_close_opposite_position` actually closed something.
        balance = await self._current_balance()

        ctx = self._context_builder(symbol, candles_by_tf, info.spread_points)
        for decision, strategy in candidates:
            balance = await self._enter_for_bot(symbol, decision, strategy, ctx, info, now, balance)

    async def _enter_for_bot(
        self,
        symbol: str,
        decision: SkillDecision,
        strategy: Strategy,
        ctx: MarketContext,
        info: SymbolInfo,
        now: datetime,
        balance: float | None,
    ) -> float | None:
        # Fetched fresh per bot (not hoisted above the candidates loop) so a
        # bot later in this same candle sees the position(s) an earlier bot
        # on the same symbol just opened.
        open_positions = await self._order_service.get_positions()

        # Evaluated ahead of the pretrade gate (unlike previously) so a
        # `close_on_opposite_signal` strategy can free up its own slot below
        # before the max-open-positions cap is checked against the count.
        signal_res = strategy.evaluate(ctx)
        if signal_res is None:
            return balance
        signals: tuple[Signal, ...] = (
            tuple(signal_res) if isinstance(signal_res, (list, tuple)) else (signal_res,)
        )
        if not signals:
            return balance

        first_signal = signals[0]
        logger.info(
            "SIGNAL: %s %s (%d target position(s)) via strategy=%s skill=%s — %s",
            symbol,
            first_signal.direction.value,
            len(signals),
            strategy.spec.name,
            decision.skill_name,
            first_signal.reason,
        )

        if strategy.spec.close_on_opposite_signal:
            open_positions, closed = await self._close_opposite_position(
                symbol, decision, strategy, first_signal, open_positions
            )
            if closed:
                # The only thing in this loop that changes account balance
                # mid-candle — re-fetch so this bot's sizing below (and any
                # later bot's, since `balance` is threaded back to the
                # caller) sees the post-close balance instead of the value
                # hoisted once at the top of `_try_enter`.
                balance = await self._current_balance()

        pretrade = self._risk_manager.check_pretrade(len(open_positions), now)
        if not pretrade.approved:
            logger.info(
                "ENTRY BLOCKED (risk gate): %s [%s] — %s",
                symbol,
                decision.skill_name,
                pretrade.reason,
            )
            return balance

        veto_tf = _veto_timeframe(strategy)
        veto_timeframes = (veto_tf,) if veto_tf is not None else ()
        confirmed, veto_reason = confirm(first_signal.direction, ctx, veto_timeframes)
        if not confirmed:
            logger.info(
                "ENTRY BLOCKED (HTF veto): %s %s [%s] — %s",
                symbol,
                first_signal.direction.value,
                decision.skill_name,
                veto_reason,
            )
            return balance

        if balance is None:
            logger.info("ENTRY SKIPPED (no account connected): %s", symbol)
            return balance

        # Volatility guard (bot-agnostic, engine-level): classified off this
        # bot's own entry timeframe so an M1 scalp bot and an M15 swing bot
        # on the same symbol each react to their own candle's regime, not a
        # shared engine-wide one. Computed once for the whole `signals`
        # tuple (not per-signal) since an EXTREME regime blocks the entire
        # entry, not individual tiered TPs. Skipped entirely when the live
        # on/off switch (`set_volatility_guard_enabled`) is off — entries
        # then behave exactly as if `volatility_config` didn't exist.
        if self._volatility_guard_enabled:
            entry_frame = ctx.candles.get(strategy.spec.entry_timeframe)
            if entry_frame is not None and not entry_frame.empty:
                regime, percentile, _atr_value = latest_volatility_regime(
                    entry_frame["high"].to_numpy(),
                    entry_frame["low"].to_numpy(),
                    entry_frame["close"].to_numpy(),
                    atr_period=self._volatility_config.atr_period,
                    regime_lookback_bars=self._volatility_config.regime_lookback_bars,
                    low_percentile=self._volatility_config.low_percentile,
                    high_percentile=self._volatility_config.high_percentile,
                    extreme_percentile=self._volatility_config.extreme_percentile,
                )
            else:
                regime, percentile = VolatilityRegime.NORMAL, float("nan")

            if regime is VolatilityRegime.EXTREME:
                logger.info(
                    "ENTRY BLOCKED (volatility guard): %s %s [%s] — regime=EXTREME percentile=%.1f",
                    symbol,
                    first_signal.direction.value,
                    decision.skill_name,
                    percentile,
                )
                return balance

            sl_mult, tp_mult = {
                VolatilityRegime.LOW: (
                    self._volatility_config.sl_multiplier_low,
                    self._volatility_config.tp_multiplier_low,
                ),
                VolatilityRegime.NORMAL: (
                    self._volatility_config.sl_multiplier_normal,
                    self._volatility_config.tp_multiplier_normal,
                ),
                VolatilityRegime.HIGH: (
                    self._volatility_config.sl_multiplier_high,
                    self._volatility_config.tp_multiplier_high,
                ),
            }[regime]
        else:
            sl_mult, tp_mult = 1.0, 1.0

        # Split risk across multiple targets so total risk per trade setup remains aligned with user config
        pos_risk_multiplier = decision.risk_multiplier / len(signals)

        for idx, signal in enumerate(signals):
            if len(open_positions) + idx >= self._risk_manager._caps.max_open_positions:
                logger.info("ENTRY BLOCKED (max open positions cap reached): %s on TP%d", symbol, idx + 1)
                break

            side = Side(signal.direction.value)
            reference_price = info.ask if side is Side.BUY else info.bid
            sign = 1 if side is Side.BUY else -1
            sl_price = reference_price - sign * signal.sl_points * sl_mult
            tp_price = reference_price + sign * signal.tp_points * tp_mult

            sizing = self._risk_manager.size_position(
                balance=balance,
                sl_distance_price=abs(reference_price - sl_price),
                contract_size=info.contract_size,
                volume_min=info.volume_min,
                volume_max=info.volume_max,
                volume_step=info.volume_step,
                risk_multiplier=pos_risk_multiplier,
            )
            if not sizing.approved:
                logger.info(
                    "ENTRY REJECTED (risk sizing for TP%d): %s %s [%s] — %s (balance=%.2f, sl_distance=%.5f, "
                    "risk_multiplier=%.2f)",
                    idx + 1,
                    symbol,
                    side.value,
                    decision.skill_name,
                    sizing.reason,
                    balance,
                    abs(reference_price - sl_price),
                    pos_risk_multiplier,
                )
                continue
            logger.info(
                "SIZING OK (TP%d/%d): %s %s %.2f lots [%s] (balance=%.2f, risk_multiplier=%.2f)",
                idx + 1,
                len(signals),
                symbol,
                side.value,
                sizing.volume,
                decision.skill_name,
                balance,
                pos_risk_multiplier,
            )

            zone = signal.zone
            comment_text = f"TP{idx+1}:{signal.reason}"[:29] if len(signals) > 1 else signal.reason[:29]
            try:
                await self._order_service.open_position(
                    symbol,
                    side,
                    sizing.volume,
                    sl=sl_price,
                    tp=tp_price,
                    comment=comment_text,
                    strategy_version=f"{strategy.spec.name}:v{strategy.spec.version}",
                    skill=decision.skill_name,
                    magic=decision.magic,
                    max_spread_points=decision.max_spread_points,
                    reason=signal.reason,
                    confidence=signal.confidence,
                    zone_kind=zone.kind.value if zone is not None else None,
                    zone_price_low=zone.price_low if zone is not None else None,
                    zone_price_high=zone.price_high if zone is not None else None,
                    zone_time_start=zone.time_start if zone is not None else None,
                    zone_time_end=zone.time_end if zone is not None else None,
                    zone_pattern=zone.pattern if zone is not None else None,
                    pattern=signal.pattern,
                    structure=tuple((p.label.value, p.price, p.time) for p in signal.structure),
                    indicators=tuple(
                        (r.name, r.value, r.threshold, r.comparison, r.passed)
                        for r in signal.indicators
                    ),
                )
            except OrderRejected:
                continue  # spread/RR gate already logged the veto inside order_service
            self._risk_manager.record_trade_opened(now)
        return balance

    async def _close_opposite_position(
        self,
        symbol: str,
        decision: SkillDecision,
        strategy: Strategy,
        signal: Signal,
        open_positions: list[Position],
    ) -> tuple[list[Position], bool]:
        """For a `close_on_opposite_signal` strategy: closes this bot's own
        open position on `symbol` (matched by `magic`, so other bots' or
        manually-opened positions are untouched) when its side opposes the
        fresh `signal` — a signal-flip exit instead of waiting for
        SL/TP/time-stop. Returns `(open_positions, closed)`: `open_positions`
        has the closed ticket removed so the caller's pretrade gate sees the
        freed slot right away, in the same pass that opens the new position;
        `closed` is `True` only when a position was actually closed here —
        the caller uses it to decide whether account balance needs
        re-fetching, since a realized close is the only thing in this loop
        that changes it."""
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
            return open_positions, False
        try:
            await self._order_service.close_position(position.ticket)
        except OrderRejected:
            logger.exception(
                "SIGNAL FLIP: failed to close ticket=%d %s ahead of new %s signal",
                position.ticket,
                symbol,
                signal.direction.value,
            )
            return open_positions, False
        logger.info(
            "SIGNAL FLIP: %s ticket=%d %s closed [%s] — new %s signal via strategy=%s",
            symbol,
            position.ticket,
            position.side.value,
            decision.skill_name,
            signal.direction.value,
            strategy.spec.name,
        )
        return [p for p in open_positions if p.ticket != position.ticket], True
