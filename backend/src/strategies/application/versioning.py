"""Strategy versioning & activation (§6.5, §8.1).

Every piece of generated code that passes the sandbox becomes a new
immutable version — written to `generated/`, hashed, and recorded with its
parent, so rollback is always "activate an older version id", never an
edit-in-place. Activation (and therefore rollback) is always a user action
via the API — the AI codegen pipeline only ever produces `VALIDATED`
versions, never `ACTIVE` ones.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from src.strategies.adapters.repository import StrategyVersionRepository
from src.strategies.domain.models import Strategy
from src.strategies.domain.versioning import CodeSource, StrategyVersion, VersionStatus
from src.strategies.registry import StrategyRegistry
from src.strategies.sandbox import validate_and_load

logger = logging.getLogger(__name__)


class StrategyValidationError(Exception):
    def __init__(self, errors: tuple[str, ...]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


class StrategyVersionService:
    def __init__(
        self,
        repository: StrategyVersionRepository,
        registry: StrategyRegistry,
        generated_dir: Path,
    ) -> None:
        self._repository = repository
        self._registry = registry
        self._generated_dir = generated_dir

    def save_generated_code(
        self,
        *,
        name: str,
        code: str,
        source: CodeSource,
        spec: dict[str, object] | None = None,
        draft_id: str | None = None,
    ) -> StrategyVersion:
        """Validate `code` in the sandbox and, if it passes, write it to
        `generated/` and record a new version. Raises `StrategyValidationError`
        if the sandbox rejects it — nothing is written to disk in that case."""
        instance, errors = validate_and_load(code)
        if instance is None:
            raise StrategyValidationError(errors)

        next_version = self._repository.latest_version_number(name) + 1
        file_name = f"{name}_v{next_version}.py"
        (self._generated_dir / file_name).write_text(code)

        parent = self._repository.get_active(name)
        version = StrategyVersion(
            id=str(uuid.uuid4()),
            name=name,
            version=next_version,
            file_path=f"src/strategies/generated/{file_name}",
            code_hash=hashlib.sha256(code.encode()).hexdigest(),
            source=source,
            status=VersionStatus.VALIDATED,
            created_at=datetime.now(UTC),
            parent_version_id=parent.id if parent else None,
            draft_id=draft_id,
            spec=spec,
        )
        self._repository.save(version)
        logger.info(
            "strategy version saved: name=%s version=%d id=%s", name, next_version, version.id
        )
        return version

    def list_versions(self, name: str | None = None) -> list[StrategyVersion]:
        return self._repository.list_all(name)

    def get_version(self, version_id: str) -> StrategyVersion | None:
        return self._repository.get(version_id)

    def get_code(self, version: StrategyVersion) -> str:
        file_name = f"{version.name}_v{version.version}.py"
        return (self._generated_dir / file_name).read_text()

    def activate_version(self, version_id: str) -> StrategyVersion:
        """Re-validate the file on disk (never trust a stale in-memory
        instance), register it live in the `StrategyRegistry`, archive the
        previously active version for the same name, and mark this one
        active. Also how rollback works: activate an older version id."""
        version = self._repository.get(version_id)
        if version is None:
            raise ValueError(f"no strategy version with id {version_id!r}")

        instance = self._load_instance(version)

        previous_active = self._repository.get_active(version.name)
        if previous_active is not None and previous_active.id != version.id:
            self._repository.save(replace(previous_active, status=VersionStatus.ARCHIVED))

        activated = replace(version, status=VersionStatus.ACTIVE)
        self._repository.save(activated)
        self._registry.register(instance)
        logger.info(
            "strategy version activated: name=%s version=%d id=%s",
            version.name,
            version.version,
            version.id,
        )
        return activated

    def load_active_into_registry(self) -> None:
        """Called once at startup so a backend restart doesn't lose whichever
        AI-generated versions were active before it went down."""
        for version in self._repository.list_active():
            try:
                instance = self._load_instance(version)
            except Exception:
                logger.exception(
                    "active strategy version failed re-validation on startup: "
                    "name=%s version=%d",
                    version.name,
                    version.version,
                )
                continue
            self._registry.register(instance)
            logger.info(
                "active strategy version loaded at startup: name=%s version=%d",
                version.name,
                version.version,
            )

    def _load_instance(self, version: StrategyVersion) -> Strategy:
        instance, errors = validate_and_load(self.get_code(version))
        if instance is None:
            raise StrategyValidationError(errors)
        return instance
