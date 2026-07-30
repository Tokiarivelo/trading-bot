"""Position manager (§6.4, §7.2): breakeven moves and time-stops on open
positions, driven by the engine's M5 clock. Also manages resting limit/stop
orders placed manually from the chart (F-manual-trading): in paper mode it
triggers them itself once price crosses, gated by the same `RiskManager` as
automated entries; in live mode MT5 triggers them server-side and this only
detects and reconciles the fill afterward.

Runs after every M5 `CandleClosed`, once per symbol, over that symbol's open
positions (from `BrokerPort.get_positions`) rather than the journal, since a
manually-opened position (via the broker API) must be managed too.

Two independent SL-tightening rules apply to every position regardless of
which strategy opened it (bot-agnostic, applies even to manually-opened
positions):

  - Breakeven at +1R: once unrealized progress reaches the initial risk
    distance, SL moves to the exact entry price.
  - Secure-on-base-clear: once a fresh RBR/DBD/RBD/DBR base has formed on
    `secure_timeframe` and price has since closed clear of it in the trade's
    favor, SL moves to entry + a small real profit buffer
    (`secure_buffer_r_mult` x R) — so a position that reverses after
    confirming trend continuation locks in a scratch-plus rather than a full
    round-trip back to a loss. Detected independently of the strategy that
    opened the position (`engine.domain.zone_detection`, a trusted
    engine-side counterpart to the same geometry duplicated across sandboxed
    strategy files), so it also protects strategies with no zone concept of
    their own (breakout_v1, mean_reversion_v1, ...).

Both rules only ever tighten SL (never loosen it) — see `_improves` — so
whichever rule's candidate is currently more protective wins, and neither
rule fights a tighter level already set by the other.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import numpy as np

from src.broker.application.order_service import OrderService
from src.broker.application.reconciliation import ReconciliationService
from src.broker.domain.trading import (
    OrderRejected,
    PendingOrder,
    Position,
    Side,
    pending_order_triggered,
)
from src.engine.application.risk_manager import RiskManager
from src.engine.domain.zone_detection import DEFAULT_ATR_PERIOD, Base, BaseKind, atr, detect_bases
from src.market_data.domain.models import MarketDataUnavailable, SymbolInfo, Timeframe
from src.market_data.ports.market_data import MarketDataPort

logger = logging.getLogger(__name__)

DEFAULT_TIME_STOP_CANDLES = 48  # 4 hours of M5 bars with no progress
DEFAULT_SECURE_TIMEFRAME = Timeframe.M5
DEFAULT_SECURE_LOOKBACK_BARS = 200
DEFAULT_SECURE_BUFFER_R_MULT = 0.2  # locked-in profit once a base is cleared, as a fraction of R


class PositionManager:
    def __init__(
        self,
        order_service: OrderService,
        market_data: MarketDataPort,
        reconciliation: ReconciliationService | None = None,
        risk_manager: RiskManager | None = None,
        time_stop_candles: int = DEFAULT_TIME_STOP_CANDLES,
        secure_timeframe: Timeframe = DEFAULT_SECURE_TIMEFRAME,
        secure_lookback_bars: int = DEFAULT_SECURE_LOOKBACK_BARS,
        secure_buffer_r_mult: float = DEFAULT_SECURE_BUFFER_R_MULT,
    ) -> None:
        self._order_service = order_service
        self._market_data = market_data
        self._reconciliation = reconciliation
        self._risk_manager = risk_manager
        self._time_stop_candles = time_stop_candles
        self._secure_timeframe = secure_timeframe
        self._secure_lookback_bars = secure_lookback_bars
        self._secure_buffer_r_mult = secure_buffer_r_mult
        self._candles_since_open: dict[int, int] = {}
        # symbol -> {ticket: order}, as of the last candle close — kept so a
        # vanished ticket's side/volume is still known when reconciling.
        self._pending_seen: dict[str, dict[int, PendingOrder]] = {}

    async def on_candle_closed(self, symbol: str) -> None:
        positions = await self._order_service.get_positions(symbol)
        open_tickets = {p.ticket for p in positions}
        vanished = [t for t in self._candles_since_open if t not in open_tickets]
        for ticket in vanished:
            del self._candles_since_open[ticket]
        # A ticket we were tracking that's no longer in the broker's open
        # list closed server-side (SL/TP fill) — nothing else in the system
        # would ever find out otherwise (§12 Phase 9).
        if vanished and self._reconciliation is not None:
            await self._reconciliation.reconcile_vanished(symbol, set(vanished))

        if positions:
            bases = await self._detect_bases(symbol)
            # One symbol-info fetch per symbol per candle close, shared by every
            # open position on that symbol — same cost concern/pattern as the
            # `_detect_bases` hoist above: two+ positions on the same symbol
            # would otherwise duplicate this gateway call per position.
            info = await self._market_data.get_symbol_info(symbol)
            for position in positions:
                self._candles_since_open[position.ticket] = (
                    self._candles_since_open.get(position.ticket, 0) + 1
                )
                await self._manage(position, bases, info)

        if self._risk_manager is not None:
            await self._manage_pending_orders(symbol)

    async def _detect_bases(self, symbol: str) -> list[Base]:
        """One zone scan per symbol per candle close, shared by every open
        position on that symbol — cheaper than re-fetching/re-detecting per
        position, and `on_candle_closed` is already scoped to one symbol."""
        try:
            candles = await self._market_data.get_candles(
                symbol, self._secure_timeframe, self._secure_lookback_bars
            )
        except MarketDataUnavailable:
            return []
        if len(candles) < DEFAULT_ATR_PERIOD * 2 + 10:
            return []
        opens_arr = np.array([c.open for c in candles])
        highs_arr = np.array([c.high for c in candles])
        lows_arr = np.array([c.low for c in candles])
        closes_arr = np.array([c.close for c in candles])
        atr_values = atr(highs_arr, lows_arr, closes_arr, DEFAULT_ATR_PERIOD)
        return detect_bases(opens_arr, highs_arr, lows_arr, closes_arr, atr_values)

    async def _manage_pending_orders(self, symbol: str) -> None:
        pending = await self._order_service.get_pending_orders(symbol)
        if self._order_service.simulates_pending_fills:
            await self._fill_triggered_paper_orders(symbol, pending)
        else:
            await self._reconcile_live_pending_fills(symbol, pending)

    async def _fill_triggered_paper_orders(self, symbol: str, pending: list[PendingOrder]) -> None:
        if not pending:
            return
        info = await self._market_data.get_symbol_info(symbol)
        risk_manager = self._risk_manager
        assert risk_manager is not None
        for order in pending:
            if not pending_order_triggered(order, info.bid, info.ask):
                continue
            open_count = len(await self._order_service.get_positions())
            decision = risk_manager.check_pretrade(open_count, datetime.now(UTC))
            if not decision.approved:
                logger.info(
                    "pending order ticket=%d not filled this candle: %s",
                    order.ticket,
                    decision.reason,
                )
                continue
            try:
                await self._order_service.open_position(
                    order.symbol, order.side, order.volume, order.sl, order.tp, order.comment
                )
            except OrderRejected as exc:
                logger.info("pending order ticket=%d not filled this candle: %s", order.ticket, exc)
                continue
            await self._order_service.cancel_pending_order(order.ticket)
            risk_manager.record_trade_opened(datetime.now(UTC))

    async def _reconcile_live_pending_fills(self, symbol: str, pending: list[PendingOrder]) -> None:
        current = {o.ticket: o for o in pending}
        previous = self._pending_seen.get(symbol, {})
        vanished_tickets = set(previous) - set(current)
        self._pending_seen[symbol] = current
        if not vanished_tickets or self._reconciliation is None:
            return
        risk_manager = self._risk_manager
        assert risk_manager is not None
        for ticket in vanished_tickets:
            order = previous[ticket]
            filled = await self._reconciliation.reconcile_pending_fill(
                symbol, ticket, order.side, order.volume
            )
            if filled:
                risk_manager.record_trade_opened(datetime.now(UTC))

    def _select_secure_base(
        self, bases: list[Base], side: Side, mark: float
    ) -> Base | None:
        """Most recent unbroken base, matching the position's direction,
        that price has already closed clear of — "a base was created and
        price passed that base." Iterates most-recent-first so an older,
        already-superseded base never wins over a fresher one."""
        demand_wanted = side is Side.BUY
        for base in reversed(bases):
            if base.broken:
                continue
            if (base.kind == BaseKind.DEMAND) != demand_wanted:
                continue
            proximal = base.price_high if demand_wanted else base.price_low
            cleared = mark > proximal if demand_wanted else mark < proximal
            if not cleared:
                continue
            return base
        return None

    @staticmethod
    def _improves(candidate: float | None, current_sl: float, direction: int) -> bool:
        """Whether moving SL to `candidate` tightens it in the position's
        favor — buys only ever move SL up, sells only ever move it down.
        Both SL rules use this so neither ever loosens a level the other
        already set."""
        if candidate is None:
            return False
        return (candidate - current_sl) * direction > 0

    async def _manage(self, position: Position, bases: list[Base], info: SymbolInfo) -> None:
        if position.sl is None:
            return
        mark = info.bid if position.side is Side.BUY else info.ask
        direction = 1 if position.side is Side.BUY else -1
        risk = abs(position.open_price - position.sl)
        progress = (mark - position.open_price) * direction

        target_sl: float | None = None

        # Rule 1: breakeven at +1R.
        if risk > 0 and progress >= risk:
            candidate = position.open_price
            if self._improves(candidate, position.sl, direction):
                target_sl = candidate

        # Rule 2: secure a small real profit once a fresh base has been
        # cleared, bot-agnostic (works even without a matching Rule 1 trigger,
        # and independently of Rule 1's own candidate — whichever is more
        # protective wins).
        if risk > 0:
            secure_base = self._select_secure_base(bases, position.side, mark)
            if secure_base is not None:
                candidate = position.open_price + direction * risk * self._secure_buffer_r_mult
                floor = target_sl if target_sl is not None else position.sl
                if self._improves(candidate, floor, direction):
                    target_sl = candidate

        if target_sl is not None:
            await self._order_service.modify_position(position.ticket, sl=target_sl, tp=position.tp)
            logger.info(
                "sl secured: ticket=%d %s sl moved to %.5f (entry %.5f)",
                position.ticket,
                position.symbol,
                target_sl,
                position.open_price,
            )
            return

        candles_open = self._candles_since_open.get(position.ticket, 0)
        if candles_open >= self._time_stop_candles and progress <= 0:
            await self._order_service.close_position(position.ticket)
            logger.info(
                "time-stop: ticket=%d %s closed after %d candles without progress",
                position.ticket,
                position.symbol,
                candles_open,
            )
            del self._candles_since_open[position.ticket]
