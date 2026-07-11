"""Pre-trade spread/RR check (§7.1 of the implementation plan).

    live_spread ≤ symbol.max_spread_points
    AND tp_distance ≥ min_rr × (sl_distance + spread_value)

Pure function of live quotes and config — no I/O, easy to unit test.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.broker.domain.symbol_config import SymbolTradingConfig


@dataclass(frozen=True, kw_only=True)
class SpreadVeto:
    reason: str


class SpreadGate:
    def __init__(self, configs: dict[str, SymbolTradingConfig]) -> None:
        self._configs = configs

    def check(
        self,
        symbol: str,
        spread_points: int,
        point: float,
        sl_distance: float,
        tp_distance: float,
    ) -> SpreadVeto | None:
        config = self._configs.get(symbol)
        if config is None:
            return SpreadVeto(reason=f"no trading config for {symbol}")
        if spread_points > config.max_spread_points:
            return SpreadVeto(
                reason=f"spread {spread_points}pts > max {config.max_spread_points}pts"
            )
        spread_value = spread_points * point
        required_tp = config.min_rr * (sl_distance + spread_value)
        if tp_distance < required_tp:
            return SpreadVeto(
                reason=(
                    f"tp distance {tp_distance:.5f} < required {required_tp:.5f} "
                    f"(min_rr={config.min_rr}, spread-adjusted)"
                )
            )
        return None
