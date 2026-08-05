"""Position manager (§6.4, §7.2): breakeven moves and time-stops on open
positions, driven by the engine's M5 clock. Also manages resting limit/stop
orders placed manually from the chart (F-manual-trading): in paper mode it
triggers them itself once price crosses, gated by the same `RiskManager` as
automated entries; in live mode MT5 triggers them server-side and this only
detects and reconciles the fill afterward.

Runs after every M5 `CandleClosed`, once per symbol, over that symbol's open
positions (from `BrokerPort.get_positions`) rather than the journal, since a
manually-opened position (via the broker API) must be managed too.

Three independent SL-tightening rules apply to every position regardless of
which strategy opened it (bot-agnostic, applies even to manually-opened
positions):

  - Breakeven at +1R: once unrealized progress reaches the initial risk
    distance, SL moves to the exact entry price.
  - Secure-on-base-clear & Structural Continuation Trailing: once a fresh
    RBR/DBD/RBD/DBR continuation base has formed on `secure_timeframe` and
    price has since closed clear of it in the trade's favor, SL moves to
    entry + a small real profit buffer (`secure_buffer_r_mult` x R). Furthermore,
    if the cleared zone sits further along in profit, SL is ratcheted directly
    underneath (for buys) or above (for sells) the zone boundary.
  - "Zone Contraire" Defensive Breakeven: upon approaching or interacting with
    an unbroken opposing base (Supply for buy, Demand for sell) within 0.5R,
    instantly triggers a defensive breakeven lock-in (+ profit buffer) so an
    upcoming liquidity rejection does not turn a running trade into a loss.

All rules only ever tighten SL (never loosen it) — see `_improves` — so
whichever rule's candidate is currently more protective wins, and no
rule fights a tighter level already set by another.

When `volatility_config` is supplied, a fourth, bot-agnostic set of rules
reacts to the symbol's current volatility regime (`engine/domain/volatility.py`):
an EXTREME regime while losing closes the position outright (bypassing the
SL-tightening rules above — this is an exit, not a tighter stop); an EXTREME
regime while winning locks in a fraction of unrealized profit; a HIGH regime
with enough running profit trails SL behind the best price reached so far by
a multiple of ATR ("chandelier" exit). `volatility_config=None` disables all
of this and reproduces pre-Phase-B behavior exactly.
"""

from __future__ import annotations

import logging
import math
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
from src.engine.domain.volatility import (
    VolatilityConfig,
    VolatilityRegime,
    latest_volatility_regime,
)
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
        volatility_config: VolatilityConfig | None = None,
    ) -> None:
        self._order_service = order_service
        self._market_data = market_data
        self._reconciliation = reconciliation
        self._risk_manager = risk_manager
        self._time_stop_candles = time_stop_candles
        self._secure_timeframe = secure_timeframe
        self._secure_lookback_bars = secure_lookback_bars
        self._secure_buffer_r_mult = secure_buffer_r_mult
        self._volatility_config = volatility_config
        self._volatility_guard_enabled = True
        self._candles_since_open: dict[int, int] = {}
        # ticket -> best favorable mark seen since entry (max for BUY, min
        # for SELL), used only by the HIGH-regime chandelier trailing rule.
        self._trade_extreme_favorable: dict[int, float] = {}
        # symbol -> {ticket: order}, as of the last candle close — kept so a
        # vanished ticket's side/volume is still known when reconciling.
        self._pending_seen: dict[str, dict[int, PendingOrder]] = {}

    def set_volatility_guard_enabled(self, enabled: bool) -> None:
        """Live-updates whether the volatility-regime position-management
        rules (`_manage`'s Rules 0/4/5 — EXTREME forced close/profit-lock,
        HIGH chandelier trailing) are active — takes effect on the very
        next `on_candle_closed`. When `False`, `_detect_bases` no longer
        classifies a regime at all, so `_manage` sees `regime=None` and
        skips those rules exactly as it does when `volatility_config=None`.
        Not persisted: a backend restart reverts to
        `configs/volatility.yaml` (enabled by default). Set together with
        `TradeEngine.set_volatility_guard_enabled` by the same API call —
        see `engine/api/routes.py`."""
        self._volatility_guard_enabled = enabled
        logger.info("position manager: volatility guard enabled=%s", enabled)

    async def on_candle_closed(self, symbol: str) -> None:
        positions = await self._order_service.get_positions(symbol)
        open_tickets = {p.ticket for p in positions}
        vanished = [t for t in self._candles_since_open if t not in open_tickets]
        for ticket in vanished:
            del self._candles_since_open[ticket]
            self._trade_extreme_favorable.pop(ticket, None)
        # A ticket we were tracking that's no longer in the broker's open
        # list closed server-side (SL/TP fill) — nothing else in the system
        # would ever find out otherwise (§12 Phase 9).
        if vanished and self._reconciliation is not None:
            await self._reconciliation.reconcile_vanished(symbol, set(vanished))

        if positions:
            bases, regime, atr_value = await self._detect_bases(symbol)
            # One symbol-info fetch per symbol per candle close, shared by every
            # open position on that symbol — same cost concern/pattern as the
            # `_detect_bases` hoist above: two+ positions on the same symbol
            # would otherwise duplicate this gateway call per position.
            info = await self._market_data.get_symbol_info(symbol)
            for position in positions:
                self._candles_since_open[position.ticket] = (
                    self._candles_since_open.get(position.ticket, 0) + 1
                )
                await self._manage(position, bases, info, regime, atr_value)

        if self._risk_manager is not None:
            await self._manage_pending_orders(symbol)

    async def _detect_bases(
        self, symbol: str
    ) -> tuple[list[Base], VolatilityRegime | None, float | None]:
        """One zone scan per symbol per candle close, shared by every open
        position on that symbol — cheaper than re-fetching/re-detecting per
        position, and `on_candle_closed` is already scoped to one symbol.
        Also classifies the current volatility regime off these same
        `secure_timeframe` candles when `self._volatility_config` is set, so
        the volatility guard in `_manage` never needs a second market-data
        round trip. Returns `(bases, regime, atr_value)`; `regime`/`atr_value`
        are `(None, None)` whenever no `volatility_config` was supplied."""
        try:
            candles = await self._market_data.get_candles(
                symbol, self._secure_timeframe, self._secure_lookback_bars
            )
        except MarketDataUnavailable:
            return [], None, None
        if len(candles) < DEFAULT_ATR_PERIOD * 2 + 10:
            return [], None, None
        opens_arr = np.array([c.open for c in candles])
        highs_arr = np.array([c.high for c in candles])
        lows_arr = np.array([c.low for c in candles])
        closes_arr = np.array([c.close for c in candles])
        atr_values = atr(highs_arr, lows_arr, closes_arr, DEFAULT_ATR_PERIOD)
        bases = detect_bases(opens_arr, highs_arr, lows_arr, closes_arr, atr_values)

        regime: VolatilityRegime | None = None
        atr_value: float | None = None
        if self._volatility_config is not None and self._volatility_guard_enabled:
            regime, _percentile, atr_value = latest_volatility_regime(
                highs_arr,
                lows_arr,
                closes_arr,
                atr_period=self._volatility_config.atr_period,
                regime_lookback_bars=self._volatility_config.regime_lookback_bars,
                low_percentile=self._volatility_config.low_percentile,
                high_percentile=self._volatility_config.high_percentile,
                extreme_percentile=self._volatility_config.extreme_percentile,
            )
        return bases, regime, atr_value

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

    def _select_nearest_opposing_base(
        self, bases: list[Base], side: Side, mark: float
    ) -> Base | None:
        """Finds the closest unbroken opposing base ahead of or around current
        market price (`mark`): for a BUY, unbroken Supply zones above or near
        mark; for a SELL, unbroken Demand zones below or near mark."""
        best_base: Base | None = None
        if side is Side.BUY:
            min_low = float("inf")
            for base in bases:
                if base.broken or base.kind != BaseKind.SUPPLY:
                    continue
                if mark > base.price_high:
                    continue
                if base.price_low < min_low:
                    min_low = base.price_low
                    best_base = base
        else:
            max_high = float("-inf")
            for base in bases:
                if base.broken or base.kind != BaseKind.DEMAND:
                    continue
                if mark < base.price_low:
                    continue
                if base.price_high > max_high:
                    max_high = base.price_high
                    best_base = base
        return best_base

    @staticmethod
    def _improves(candidate: float | None, current_sl: float, direction: int) -> bool:
        """Whether moving SL to `candidate` tightens it in the position's
        favor — buys only ever move SL up, sells only ever move it down.
        Both SL rules use this so neither ever loosens a level the other
        already set."""
        if candidate is None:
            return False
        return (candidate - current_sl) * direction > 0

    async def _manage(
        self,
        position: Position,
        bases: list[Base],
        info: SymbolInfo,
        regime: VolatilityRegime | None = None,
        atr_value: float | None = None,
    ) -> None:
        if position.sl is None:
            return
        mark = info.bid if position.side is Side.BUY else info.ask
        direction = 1 if position.side is Side.BUY else -1
        risk = abs(position.open_price - position.sl)
        progress = (mark - position.open_price) * direction

        volatility_active = (
            self._volatility_config is not None
            and atr_value is not None
            and not math.isnan(atr_value)
        )

        # Rule 0 (volatility guard): EXTREME regime while losing closes the
        # position outright instead of tightening SL — bypasses every
        # SL-tightening rule below entirely.
        if (
            volatility_active
            and regime is VolatilityRegime.EXTREME
            and progress <= 0
            and self._volatility_config is not None
            and self._volatility_config.extreme_close_if_losing
        ):
            await self._order_service.close_position(
                position.ticket, reason="volatility guard: EXTREME regime while losing"
            )
            logger.info(
                "volatility guard: ticket=%d %s closed — EXTREME regime while losing",
                position.ticket,
                position.symbol,
            )
            self._candles_since_open.pop(position.ticket, None)
            self._trade_extreme_favorable.pop(position.ticket, None)
            return

        target_sl: float | None = None
        target_sl_reason: str | None = None

        # Rule 1: breakeven at +1R.
        if risk > 0 and progress >= risk:
            candidate = position.open_price
            if self._improves(candidate, position.sl, direction):
                target_sl = candidate
                target_sl_reason = "breakeven at +1R"

        # Rule 2: secure a small real profit once a fresh base has been
        # cleared, and ratchet SL via structural continuation trailing if the
        # cleared base sits further along in profit.
        if risk > 0:
            secure_base = self._select_secure_base(bases, position.side, mark)
            if secure_base is not None:
                buffer_price = risk * self._secure_buffer_r_mult
                candidate = position.open_price + direction * buffer_price
                zone_trail_sl = (
                    secure_base.price_low - buffer_price
                    if position.side is Side.BUY
                    else secure_base.price_high + buffer_price
                )
                if self._improves(zone_trail_sl, candidate, direction):
                    candidate = zone_trail_sl
                floor = target_sl if target_sl is not None else position.sl
                if self._improves(candidate, floor, direction):
                    target_sl = candidate
                    target_sl_reason = "secure-base trailing"

        # Rule 3: "Zone Contraire" defensive breakeven — if approaching or
        # interacting with an unbroken opposing zone ahead of or around current
        # market price, instantly lock in breakeven (+ buffer).
        if risk > 0:
            opposing_base = self._select_nearest_opposing_base(bases, position.side, mark)
            if opposing_base is not None:
                distance = (
                    opposing_base.price_low - mark
                    if position.side is Side.BUY
                    else mark - opposing_base.price_high
                )
                if distance <= 0.5 * risk:
                    candidate = position.open_price + direction * risk * self._secure_buffer_r_mult
                    if (mark - candidate) * direction > 0:
                        floor = target_sl if target_sl is not None else position.sl
                        if self._improves(candidate, floor, direction):
                            target_sl = candidate
                            target_sl_reason = "zone-contraire defensive breakeven"

        # Rule 4 (volatility guard): EXTREME regime while winning locks in a
        # fraction of unrealized profit — feeds the same target_sl/_improves
        # merge as the rules above, so it never fights or loosens whatever
        # they already proposed.
        if (
            volatility_active
            and regime is VolatilityRegime.EXTREME
            and progress > 0
            and self._volatility_config is not None
        ):
            candidate = (
                position.open_price
                + direction * progress * self._volatility_config.extreme_profit_lock_r_mult
            )
            floor = target_sl if target_sl is not None else position.sl
            if self._improves(candidate, floor, direction):
                target_sl = candidate
                target_sl_reason = "volatility guard: EXTREME profit-lock"

        # Rule 5 (volatility guard): HIGH regime with enough running profit
        # trails SL behind the best favorable price reached since entry by a
        # multiple of ATR ("chandelier" exit) — same target_sl/_improves
        # merge, so a pullback that hasn't breached the trailed level never
        # loosens the stop.
        if (
            volatility_active
            and regime is VolatilityRegime.HIGH
            and risk > 0
            and self._volatility_config is not None
            and progress >= self._volatility_config.chandelier_min_profit_r * risk
        ):
            favorable = self._trade_extreme_favorable.get(position.ticket)
            if favorable is None:
                favorable = mark
            elif position.side is Side.BUY:
                favorable = max(favorable, mark)
            else:
                favorable = min(favorable, mark)
            self._trade_extreme_favorable[position.ticket] = favorable
            atr_distance = self._volatility_config.chandelier_atr_mult * atr_value
            candidate = favorable - direction * atr_distance
            floor = target_sl if target_sl is not None else position.sl
            if self._improves(candidate, floor, direction):
                target_sl = candidate
                target_sl_reason = "volatility guard: HIGH-regime chandelier trail"

        if target_sl is not None:
            await self._order_service.modify_position(
                position.ticket, sl=target_sl, tp=position.tp, reason=target_sl_reason or ""
            )
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
            await self._order_service.close_position(
                position.ticket, reason="time-stop: no progress"
            )
            logger.info(
                "time-stop: ticket=%d %s closed after %d candles without progress",
                position.ticket,
                position.symbol,
                candles_open,
            )
            del self._candles_since_open[position.ticket]
