"""Read/write access to `skills/normal/<symbol>/<bot_slug>.yaml` (§6.6) — the
on-disk source of truth for which bots trade each symbol. A symbol is a
directory; each file inside it is one concurrently-active bot on that
symbol. Extracted from `container._load_normal_skill` so `SkillAssignmentService`
can both read it at startup and write reassignments back without duplicating
the YAML shape.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from src.shared.config.atomic_write import atomic_write_text
from src.skills.domain.models import NormalSkill, SessionWindow


class NormalSkillRepository:
    def __init__(self, skills_dir: Path) -> None:
        self._dir = skills_dir

    def _symbol_dir(self, symbol: str) -> Path:
        return self._dir / symbol.lower()

    def _path(self, symbol: str, bot_slug: str) -> Path:
        return self._symbol_dir(symbol) / f"{bot_slug}.yaml"

    def load_all(self, symbols: list[str]) -> dict[str, list[NormalSkill]]:
        """Every bot currently routed for each requested symbol — a symbol
        with no `skills/normal/<symbol>/` directory yet (zero active bots)
        yields an empty list rather than raising, since that's now a valid
        state (e.g. after removing a symbol's last bot)."""
        return {symbol: self.list_for_symbol(symbol) for symbol in symbols}

    def list_for_symbol(self, symbol: str) -> list[NormalSkill]:
        """Every bot currently active on `symbol` alone — used by
        `SkillAssignmentService.add_bot()` to tell whether a symbol had zero
        bots before this call (first-activation path)."""
        directory = self._symbol_dir(symbol)
        if not directory.is_dir():
            return []
        return [self._load_path(path) for path in sorted(directory.glob("*.yaml"))]

    def list_all(self) -> list[NormalSkill]:
        """Every bot on every symbol currently on disk — the live routing
        table as it actually is, independent of `configs/app.yaml: symbols`
        (a bot added at runtime via `add_bot()` has a file here immediately,
        whether or not app.yaml has been re-read since)."""
        return [self._load_path(path) for path in sorted(self._dir.glob("*/*.yaml"))]

    def get(self, symbol: str, bot_slug: str) -> NormalSkill | None:
        path = self._path(symbol, bot_slug)
        if not path.exists():
            return None
        return self._load_path(path)

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
            param_overrides=data.get("param_overrides") or {},
            htf_veto_override=data.get("htf_veto_override"),
        )

    def save(self, skill: NormalSkill) -> None:
        """Writes `skill` to `skills/normal/<symbol>/<bot_slug>.yaml`, where
        `bot_slug` is the last `/`-separated segment of `skill.name`
        (`normal/<symbol>/<bot_slug>`)."""
        bot_slug = skill.name.rsplit("/", 1)[-1]
        data = {
            "name": skill.name,
            "symbol": skill.symbol,
            "strategy": skill.strategy,
            "risk_multiplier": skill.risk_multiplier,
            "sessions": [
                {"start": window.start.strftime("%H:%M"), "end": window.end.strftime("%H:%M")}
                for window in skill.sessions
            ],
            "param_overrides": dict(skill.param_overrides),
            "htf_veto_override": skill.htf_veto_override,
        }
        self._symbol_dir(skill.symbol).mkdir(parents=True, exist_ok=True)
        atomic_write_text(self._path(skill.symbol, bot_slug), yaml.safe_dump(data, sort_keys=False))

    def delete(self, symbol: str, bot_slug: str) -> None:
        self._path(symbol, bot_slug).unlink(missing_ok=True)
