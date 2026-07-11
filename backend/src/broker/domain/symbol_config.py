"""Per-symbol trading config (`configs/symbols/<symbol>.yaml`) — read-only here."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class SymbolTradingConfig:
    symbol: str
    max_spread_points: int
    min_rr: float
    # Static broker facts — live trading reads these from MT5 symbol_info
    # instead; the config copy exists so the replay adapter (backtests) has
    # them offline. See configs/symbols/<symbol>.yaml.
    contract_size: float
    point: float
    digits: int
    stops_level: int
    volume_min: float
    volume_max: float
    volume_step: float
