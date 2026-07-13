"""Symbol -> strategy family routing (§6.6) — the real "apply a bot to a
symbol" action. Distinct from `strategies.application.versioning.activate_version`,
which decides which *version* of a family is live; this decides which
*family* a symbol routes to at all, by rewriting `skills/normal/<symbol>.yaml`
and hot-swapping the running `SkillSelector`.
"""

from __future__ import annotations

from pathlib import Path

from src.shared.config.loaders import load_symbol_trading_config_if_exists
from src.skills.adapters.normal_skill_repository import NormalSkillRepository
from src.skills.application.skill_selector import SkillSelector
from src.skills.domain.models import NormalSkill
from src.strategies.registry import StrategyRegistry


class UnknownSymbolError(Exception):
    pass


class UnknownStrategyError(Exception):
    pass


class SkillAssignmentService:
    def __init__(
        self,
        repository: NormalSkillRepository,
        selector: SkillSelector,
        strategy_registry: StrategyRegistry,
        symbols: list[str],
        configs_dir: Path,
    ) -> None:
        self._repository = repository
        self._selector = selector
        self._strategy_registry = strategy_registry
        self._symbols = symbols
        self._configs_dir = configs_dir

    def list_assignments(self) -> list[NormalSkill]:
        return [
            skill
            for symbol in self._symbols
            if (skill := self._repository.get(symbol)) is not None
        ]

    def assign(self, symbol: str, strategy_name: str) -> NormalSkill:
        if load_symbol_trading_config_if_exists(symbol, self._configs_dir) is None:
            raise UnknownSymbolError(f"no configs/symbols/{symbol.lower()}.yaml for {symbol!r}")
        if self._strategy_registry.get(strategy_name) is None:
            raise UnknownStrategyError(
                f"{strategy_name!r} has no currently active, non-paused strategy version"
            )
        existing = self._repository.get(symbol)
        skill = NormalSkill(
            name=existing.name if existing else f"normal/{symbol.lower()}",
            symbol=symbol,
            strategy=strategy_name,
            risk_multiplier=existing.risk_multiplier if existing else 1.0,
            sessions=existing.sessions if existing else (),
        )
        self._repository.save(skill)
        self._selector.update(symbol, skill)
        return skill
