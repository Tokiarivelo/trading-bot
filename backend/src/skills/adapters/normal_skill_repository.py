"""Read/write access to `skills/normal/<symbol>.yaml` (§6.6) — the on-disk
source of truth for which strategy family trades each symbol. Extracted from
`container._load_normal_skill` so `SkillAssignmentService` can both read it
at startup and write reassignments back without duplicating the YAML shape.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from src.shared.config.atomic_write import atomic_write_text
from src.skills.domain.models import NormalSkill, SessionWindow


class NormalSkillRepository:
    def __init__(self, skills_dir: Path) -> None:
        self._dir = skills_dir

    def _path(self, symbol: str) -> Path:
        return self._dir / f"{symbol.lower()}.yaml"

    def load_all(self, symbols: list[str]) -> dict[str, NormalSkill]:
        """One `NormalSkill` per requested symbol — raises FileNotFoundError
        if any symbol in `configs/app.yaml: symbols` has no matching file,
        same as the loader this replaces."""
        return {symbol: self._load(symbol) for symbol in symbols}

    def list_all(self) -> list[NormalSkill]:
        """Every skill file currently on disk — the live routing table as it
        actually is, independent of `configs/app.yaml: symbols` (a symbol
        activated at runtime via `assign()` has a file here immediately,
        whether or not app.yaml has been re-read since)."""
        return [self._load_path(path) for path in sorted(self._dir.glob("*.yaml"))]

    def get(self, symbol: str) -> NormalSkill | None:
        if not self._path(symbol).exists():
            return None
        return self._load(symbol)

    def _load(self, symbol: str) -> NormalSkill:
        return self._load_path(self._path(symbol))

    def _load_path(self, path: Path) -> NormalSkill:
        with path.open() as f:
            data = yaml.safe_load(f)
        sessions = tuple(
            SessionWindow.parse(s["start"], s["end"]) for s in data.get("sessions", [])
        )
        return NormalSkill(
            name=data["name"],
            symbol=data["symbol"],
            strategy=data["strategy"],
            risk_multiplier=data.get("risk_multiplier", 1.0),
            sessions=sessions,
        )

    def save(self, skill: NormalSkill) -> None:
        data = {
            "name": skill.name,
            "symbol": skill.symbol,
            "strategy": skill.strategy,
            "risk_multiplier": skill.risk_multiplier,
            "sessions": [
                {"start": window.start.strftime("%H:%M"), "end": window.end.strftime("%H:%M")}
                for window in skill.sessions
            ],
        }
        self._dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self._path(skill.symbol), yaml.safe_dump(data, sort_keys=False))
