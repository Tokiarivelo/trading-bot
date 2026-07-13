"""Read/write access to `skills/normal/<symbol>.yaml` (§6.6) — the on-disk
source of truth for which strategy family trades each symbol. Extracted from
`container._load_normal_skill` so `SkillAssignmentService` can both read it
at startup and write reassignments back without duplicating the YAML shape.
"""

from __future__ import annotations

from pathlib import Path

import yaml

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

    def get(self, symbol: str) -> NormalSkill | None:
        if not self._path(symbol).exists():
            return None
        return self._load(symbol)

    def _load(self, symbol: str) -> NormalSkill:
        with self._path(symbol).open() as f:
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
        with self._path(skill.symbol).open("w") as f:
            yaml.safe_dump(data, f, sort_keys=False)
