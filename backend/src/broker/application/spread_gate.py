"""Pre-trade spread/RR check (§7.1 of the implementation plan).

    live_spread ≤ symbol.max_spread_points
    AND (sl and tp both set) => tp_distance ≥ min_rr × (sl_distance + spread_value)

Pure function of live quotes and config — no I/O, easy to unit test.

`configs/symbols/*.yaml` only covers the engine's own configured symbols
(`configs/app.yaml: symbols`); a manual trade can target any symbol browsed
from the broker's catalog (F-manual-trading), which has no such file. Rather
than reject those outright, `check()` falls back to `DEFAULT_MIN_RR` with no
spread cap — a flat points cap calibrated for one instrument (e.g. XAUUSD's
35pts) is meaningless for an arbitrary symbol's own point/digit scale, so
skipping it is more honest than guessing.

The RR check itself only runs when both `sl_distance` and `tp_distance` are
given — a strategy (automated or a manual trader who chooses to set both)
always gets the RR floor enforced, but a manual discretionary trade with no
`sl`/`tp` (or only one of them) is allowed through; account-level caps
(`ManualTradeGate`/`RiskManager`) and the spread cap above are still the
backstop either way. The automated engine always sets both, so this only
changes behavior for the manual path.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.broker.domain.symbol_config import SymbolTradingConfig

logger = logging.getLogger(__name__)

DEFAULT_MIN_RR = 1.0


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
        sl_distance: float | None,
        tp_distance: float | None,
        max_spread_override: int | None = None,
    ) -> SpreadVeto | None:
        config = self._configs.get(symbol)
        if config is None:
            logger.info(
                "spread gate: no configs/symbols/%s.yaml — using fallback "
                "(no spread cap, min_rr=%.1f)",
                symbol.lower(),
                DEFAULT_MIN_RR,
            )
        max_spread_points = (
            max_spread_override
            if max_spread_override is not None
            else (config.max_spread_points if config is not None else None)
        )
        if max_spread_points is not None and spread_points > max_spread_points:
            return SpreadVeto(reason=f"spread {spread_points}pts > max {max_spread_points}pts")
        if sl_distance is None or tp_distance is None:
            # No RR to evaluate without both — a manual trader who omits
            # sl/tp is accepting that risk explicitly (F-manual-trading).
            return None
        min_rr = config.min_rr if config is not None else DEFAULT_MIN_RR
        spread_value = spread_points * point
        required_tp = min_rr * (sl_distance + spread_value)
        if tp_distance < required_tp:
            return SpreadVeto(
                reason=(
                    f"tp distance {tp_distance:.5f} < required {required_tp:.5f} "
                    f"(min_rr={min_rr}, spread-adjusted)"
                )
            )
        return None
