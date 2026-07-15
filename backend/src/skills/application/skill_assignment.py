"""Symbol -> strategy family routing (§6.6) — the real "apply a bot to a
symbol" action. Distinct from `strategies.application.versioning.activate_version`,
which decides which *version* of a family is live; this decides which
*family* a symbol routes to at all, by rewriting `skills/normal/<symbol>.yaml`
and hot-swapping the running `SkillSelector`.

`assign()` is also where a symbol not yet in the automated-trading universe
gets activated: it persists the symbol into `configs/app.yaml` and hot-adds
it to candle streaming and the spread gate, so clicking "Apply" in the UI is
the one deliberate action that fully turns on live trading for a symbol — no
manual YAML edit, no restart. See the module docstring in
`market_data.application.candle_stream` for why the engine only ever
evaluates a symbol it's actively polling.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from src.broker.application.spread_gate import SpreadGate
from src.market_data.application.candle_stream import CandleStreamService
from src.shared.config.app_config_writer import add_symbol_to_app_config
from src.shared.config.loaders import load_symbol_trading_config_if_exists
from src.skills.adapters.normal_skill_repository import NormalSkillRepository
from src.skills.application.skill_selector import SkillSelector
from src.skills.domain.models import NormalSkill
from src.strategies.registry import StrategyRegistry

logger = logging.getLogger(__name__)


class UnknownSymbolError(Exception):
    pass


class UnknownStrategyError(Exception):
    pass


@dataclass(frozen=True)
class AssignmentResult:
    """`assign()`'s outcome — `newly_activated` is a call outcome, not part
    of the persisted `NormalSkill`, so it doesn't belong on that dataclass."""

    skill: NormalSkill
    newly_activated: bool


class SkillAssignmentService:
    def __init__(
        self,
        repository: NormalSkillRepository,
        selector: SkillSelector,
        strategy_registry: StrategyRegistry,
        candle_stream: CandleStreamService,
        spread_gate: SpreadGate,
        configs_dir: Path,
    ) -> None:
        self._repository = repository
        self._selector = selector
        self._strategy_registry = strategy_registry
        self._candle_stream = candle_stream
        self._spread_gate = spread_gate
        self._configs_dir = configs_dir

    async def list_assignments(self) -> list[NormalSkill]:
        """Every symbol currently routed, i.e. every skills/normal/*.yaml
        file on disk — independent of configs/app.yaml, so a symbol
        activated via `assign()` shows up here immediately."""
        return await asyncio.to_thread(self._repository.list_all)

    async def assign(self, symbol: str, strategy_name: str) -> AssignmentResult:
        config = await asyncio.to_thread(
            load_symbol_trading_config_if_exists, symbol, self._configs_dir
        )
        if config is None:
            raise UnknownSymbolError(f"no configs/symbols/{symbol.lower()}.yaml for {symbol!r}")
        if self._strategy_registry.get(strategy_name) is None:
            raise UnknownStrategyError(
                f"{strategy_name!r} has no currently active, non-paused strategy version"
            )

        # Durable writes first, in-memory hot-swaps after: every step below
        # is individually idempotent, so a retry (or a restart, which just
        # re-reads the now-updated app.yaml) always converges to the same
        # state with no partial-activation window to worry about.
        newly_activated = await asyncio.to_thread(
            add_symbol_to_app_config, symbol, self._configs_dir
        )

        existing = await asyncio.to_thread(self._repository.get, symbol)
        skill = NormalSkill(
            name=existing.name if existing else f"normal/{symbol.lower()}",
            symbol=symbol,
            strategy=strategy_name,
            risk_multiplier=existing.risk_multiplier if existing else 1.0,
            sessions=existing.sessions if existing else (),
        )
        await asyncio.to_thread(self._repository.save, skill)

        self._candle_stream.add_symbol(symbol)
        self._spread_gate.set_config(symbol, config)
        self._selector.update(symbol, skill)

        if newly_activated:
            logger.info(
                "symbol %s newly activated for live automated trading via UI apply "
                "(strategy=%s)",
                symbol,
                strategy_name,
            )
        return AssignmentResult(skill=skill, newly_activated=newly_activated)
