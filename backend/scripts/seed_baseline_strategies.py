"""Seed the hardcoded baseline strategies (see `container.py`'s direct
`StrategyRegistry.register()` calls) into the `StrategyVersion` DB table so
they show up in the Bots page / `GET /strategies/versions` like any other
strategy, with real version history, pause/resume, and rollback instead of
only existing as an in-memory registration that the UI can't see.

Run from `backend/`:

    uv run python -m scripts.seed_baseline_strategies

Safely re-runnable: a family that already has any recorded version is
skipped (logged, not overwritten) rather than erroring the whole run.
"""

from __future__ import annotations

import logging
from pathlib import Path

from src.shared.config.settings import Settings
from src.shared.db.base import make_session_factory
from src.strategies.adapters.repository import StrategyVersionRepository
from src.strategies.application.versioning import StrategyVersionService
from src.strategies.domain.versioning import CodeSource
from src.strategies.registry import StrategyRegistry

logger = logging.getLogger(__name__)

_GENERATED_DIR = Path(__file__).resolve().parent.parent / "src" / "strategies" / "generated"

# (family name, source file stem) — the file already lives in generated/ as
# a hand-written baseline; seeding copies its current contents into a
# proper version-1 record rather than mutating the original file.
_BASELINE_STRATEGIES: tuple[tuple[str, str], ...] = (
    ("trend_structure_v1", "trend_structure_v1"),
    ("trend_structure_v2", "trend_structure_v2"),
)


def seed(service: StrategyVersionService, repository: StrategyVersionRepository) -> None:
    for name, file_stem in _BASELINE_STRATEGIES:
        if repository.list_all(name):
            logger.info("skipping %r — already seeded", name)
            continue
        code = (_GENERATED_DIR / f"{file_stem}.py").read_text()
        version = service.save_generated_code(name=name, code=code, source=CodeSource.MANUAL)
        service.activate_version(version.id)
        logger.info(
            "seeded and activated %r (version=%d, id=%s)", name, version.version, version.id
        )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = Settings()
    session_factory = make_session_factory(settings.database_url)
    repository = StrategyVersionRepository(session_factory)
    service = StrategyVersionService(
        repository=repository, registry=StrategyRegistry(), generated_dir=_GENERATED_DIR
    )
    seed(service, repository)


if __name__ == "__main__":
    main()
