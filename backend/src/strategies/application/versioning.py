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
import re
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

# Matches the `symbols=(...)` keyword argument inside a generated file's
# `StrategySpec(...)` call — the codegen prompt (ai/prompts/
# generate_strategy_code.md) always produces this as a flat tuple literal of
# quoted symbol names, e.g. `symbols=("XAUUSD", "XAGUSD")`.
_SYMBOLS_LITERAL_RE = re.compile(r"symbols\s*=\s*\([^)]*\)")


def _rewrite_symbols(code: str, symbols: tuple[str, ...]) -> tuple[str, bool]:
    """Best-effort rewrite of the `symbols=(...)` literal in generated code.
    Returns (new_code, replaced) — `replaced` is False if no such literal was
    found, which the caller should treat as "can't safely retarget this
    version's code"."""
    literal = "(" + ", ".join(f'"{s}"' for s in symbols) + ("," if len(symbols) == 1 else "") + ")"
    new_code, count = _SYMBOLS_LITERAL_RE.subn(f"symbols={literal}", code, count=1)
    return new_code, count > 0


class StrategyValidationError(Exception):
    def __init__(self, errors: tuple[str, ...]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


class StrategyNameConflictError(Exception):
    def __init__(self, name: str) -> None:
        super().__init__(f"strategy name {name!r} is already in use")
        self.name = name


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

    def duplicate_version(
        self,
        version_id: str,
        *,
        new_name: str,
        symbols: tuple[str, ...] | None = None,
    ) -> StrategyVersion:
        """Clone `version_id`'s code (and spec snapshot) into a brand-new,
        independent strategy family: `new_name`, version 1, no parent — a
        fork for retargeting (e.g. same logic, different symbol), not a
        supersession of the original. Pass `symbols` to also retarget the
        clone: rewrites the `StrategySpec(symbols=...)` literal in the
        source and re-validates in the sandbox before saving. Raises
        `ValueError` if `version_id` doesn't exist, `StrategyNameConflictError`
        if `new_name` is already a strategy family, and
        `StrategyValidationError` if the (possibly retargeted) clone fails
        sandbox validation."""
        source = self._repository.get(version_id)
        if source is None:
            raise ValueError(f"no strategy version with id {version_id!r}")
        if self._repository.latest_version_number(new_name) > 0:
            raise StrategyNameConflictError(new_name)

        code = self.get_code(source)
        new_spec = dict(source.spec) if source.spec else None
        if symbols is not None:
            code, replaced = _rewrite_symbols(code, symbols)
            if not replaced:
                raise StrategyValidationError(
                    (
                        "couldn't find a `symbols=(...)` literal in this version's "
                        "StrategySpec to retarget — duplicate without a symbols "
                        "override and edit the generated file directly instead",
                    )
                )
            if new_spec is not None:
                new_spec["symbols"] = list(symbols)

        instance, errors = validate_and_load(code)
        if instance is None:
            raise StrategyValidationError(errors)

        file_name = f"{new_name}_v1.py"
        (self._generated_dir / file_name).write_text(code)

        duplicated = StrategyVersion(
            id=str(uuid.uuid4()),
            name=new_name,
            version=1,
            file_path=f"src/strategies/generated/{file_name}",
            code_hash=hashlib.sha256(code.encode()).hexdigest(),
            source=CodeSource.MANUAL,
            status=VersionStatus.VALIDATED,
            created_at=datetime.now(UTC),
            parent_version_id=None,
            draft_id=None,
            spec=new_spec,
            backtest_report_id=None,
        )
        self._repository.save(duplicated)
        logger.info(
            "strategy version duplicated: source_id=%s new_name=%s new_id=%s",
            version_id,
            new_name,
            duplicated.id,
        )
        return duplicated

    def rename_family(self, version_id: str, new_name: str) -> StrategyVersion:
        """Rename the strategy family `version_id` belongs to — updates the
        stored `name` on every version that shares it (all versions of the
        same strategy share a display name), never the generated file's
        on-disk name or contents. Returns the renamed version matching
        `version_id`. Raises `ValueError` if `version_id` doesn't exist, and
        `StrategyNameConflictError` if `new_name` is already in use."""
        anchor = self._repository.get(version_id)
        if anchor is None:
            raise ValueError(f"no strategy version with id {version_id!r}")
        if new_name != anchor.name and self._repository.latest_version_number(new_name) > 0:
            raise StrategyNameConflictError(new_name)

        renamed_anchor = None
        for version in self._repository.list_all(anchor.name):
            renamed = replace(version, name=new_name)
            self._repository.save(renamed)
            if version.id == version_id:
                renamed_anchor = renamed
        logger.info("strategy family renamed: %s -> %s (id=%s)", anchor.name, new_name, version_id)
        assert renamed_anchor is not None
        return renamed_anchor

    def list_versions(
        self, name: str | None = None, status: VersionStatus | None = None
    ) -> list[StrategyVersion]:
        return self._repository.list_all(name, status)

    def get_version(self, version_id: str) -> StrategyVersion | None:
        return self._repository.get(version_id)

    def get_code(self, version: StrategyVersion) -> str:
        # Derived from the stored `file_path`, not reconstructed from
        # `name`/`version` — renaming a family (rename_family) only touches
        # the stored name, never the on-disk file, so this must stay valid
        # after a rename.
        return (self._generated_dir / Path(version.file_path).name).read_text()

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
                    "active strategy version failed re-validation on startup: name=%s version=%d",
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
