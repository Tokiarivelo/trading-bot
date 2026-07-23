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

# Sentinel for `StrategyVersionService.edit_code`'s `spec` kwarg, distinguishing
# "not given, carry the base version's spec over unchanged" from an explicit
# `spec=None` (clear it) or `spec={...}` (override it).
_UNSET = object()

# Matches the `symbols=(...)` keyword argument inside a generated file's
# `StrategySpec(...)` call — the codegen prompt (ai/prompts/
# generate_strategy_code.md) always produces this as a flat tuple literal of
# quoted symbol names, e.g. `symbols=("XAUUSD", "XAGUSD")`.
_SYMBOLS_LITERAL_RE = re.compile(r"symbols\s*=\s*\([^)]*\)")


def _derive_spec_snapshot(instance: Strategy) -> dict[str, object]:
    """Minimal spec snapshot built from a validated instance's own
    `StrategySpec`, for versions saved without an extracted spec (manual
    uploads/edits, baseline seeds). Gives the Bots UI real symbols/
    timeframes/params to display and retarget instead of no snapshot at
    all — entry/exit rules aren't recoverable from code, so they point at
    the source."""
    spec = instance.spec
    return {
        "name": spec.name,
        "symbols": list(spec.symbols),
        "entry_timeframe": spec.entry_timeframe,
        "confirmation_timeframes": list(spec.confirmation_timeframes),
        "indicators": [],
        "entry_rules": "Not extracted from a spec — defined in the strategy source.",
        "exit_rules": "Not extracted from a spec — defined in the strategy source.",
        "risk_notes": "Derived from code. Enforced caps live in configs/risk.yaml.",
        "params": dict(spec.params),
    }


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


class VersionAlreadyArchivedError(Exception):
    def __init__(self, version_id: str) -> None:
        super().__init__(f"strategy version {version_id!r} is already archived")
        self.version_id = version_id


class VersionActiveError(Exception):
    """Raised when trying to delete a version that's currently live."""

    def __init__(self, version_id: str) -> None:
        super().__init__(f"strategy version {version_id!r} is active; archive it first")
        self.version_id = version_id


class VersionNotActiveError(Exception):
    """Raised when trying to pause/resume a version that isn't the live one."""

    def __init__(self, version_id: str) -> None:
        super().__init__(f"strategy version {version_id!r} is not active")
        self.version_id = version_id


class StrategyVersionService:
    def __init__(
        self,
        repository: StrategyVersionRepository,
        registry: StrategyRegistry,
        generated_dir: Path,
        account_id: str = "default",
    ) -> None:
        self._repository = repository
        self._registry = registry
        self._generated_dir = generated_dir
        self._account_id = account_id

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
        `generated/` and record a new version. When no `spec` snapshot is
        given (manual uploads, baseline seeds), a minimal one is derived from
        the code's own `StrategySpec` so the Bots UI can always show and
        retarget symbols. Raises `StrategyValidationError` if the sandbox
        rejects it — nothing is written to disk in that case."""
        instance, errors = validate_and_load(code)
        if instance is None:
            raise StrategyValidationError(errors)
        if spec is None:
            spec = _derive_spec_snapshot(instance)

        next_version = self._repository.latest_version_number(name, self._account_id) + 1
        file_name = f"{name}_v{next_version}.py"
        (self._generated_dir / file_name).write_text(code)

        parent = self._repository.get_active(name, self._account_id)
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
        self._repository.save(version, self._account_id)
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
        if self._repository.latest_version_number(new_name, self._account_id) > 0:
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
        if new_spec is None:
            # Derived after the symbols rewrite, so a retargeted clone's
            # snapshot reflects the new symbols, not the source's.
            new_spec = _derive_spec_snapshot(instance)

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
        self._repository.save(duplicated, self._account_id)
        logger.info(
            "strategy version duplicated: source_id=%s new_name=%s new_id=%s",
            version_id,
            new_name,
            duplicated.id,
        )
        return duplicated

    def edit_code(
        self,
        version_id: str,
        code: str,
        *,
        source: CodeSource = CodeSource.MANUAL,
        new_name: str | None = None,
        spec: dict[str, object] | None | object = _UNSET,
    ) -> StrategyVersion:
        """Validate `code` in the sandbox and, if it passes, save it as a new
        version — used by both the manual code editor and AI regeneration
        (`ai/application/code_regeneration.py`).

        Two save destinations, chosen by `new_name`:
        - Omitted (or equal to `version_id`'s own family name): increments
          within that family, parented explicitly on `version_id` — unlike
          `save_generated_code` (whose parent is always whatever's currently
          ACTIVE), this always parents on the exact version being edited, so
          editing an old or archived version doesn't silently rebase onto
          the live one.
        - A different name: forks into a brand-new family at version 1, no
          parent — same fork semantics as `duplicate_version`, just with
          edited/regenerated code instead of a verbatim copy.

        `spec` defaults to carrying `version_id`'s spec snapshot over
        unchanged; pass an explicit dict (or `None`) to override it, e.g.
        when the trader edited the spec before an AI regeneration. Raises
        `ValueError` if `version_id` doesn't exist, `StrategyNameConflictError`
        if `new_name` is already a different, existing family, and
        `StrategyValidationError` if `code` fails sandbox validation —
        nothing is written to disk in either error case."""
        base = self._repository.get(version_id)
        if base is None:
            raise ValueError(f"no strategy version with id {version_id!r}")

        forking = new_name is not None and new_name != base.name
        if forking and self._repository.latest_version_number(new_name, self._account_id) > 0:
            raise StrategyNameConflictError(new_name)

        instance, errors = validate_and_load(code)
        if instance is None:
            raise StrategyValidationError(errors)

        target_name = new_name if forking else base.name
        next_version = (
            1
            if forking
            else self._repository.latest_version_number(base.name, self._account_id) + 1
        )
        parent_version_id = None if forking else base.id
        effective_spec = base.spec if spec is _UNSET else spec
        if spec is _UNSET and effective_spec is None:
            # Base version predates spec snapshots (or was saved without
            # one) — derive from the edited code so the new version shows
            # up with symbols/params instead of no snapshot. An explicit
            # `spec=None` still clears it, per the docstring.
            effective_spec = _derive_spec_snapshot(instance)

        file_name = f"{target_name}_v{next_version}.py"
        (self._generated_dir / file_name).write_text(code)

        version = StrategyVersion(
            id=str(uuid.uuid4()),
            name=target_name,
            version=next_version,
            file_path=f"src/strategies/generated/{file_name}",
            code_hash=hashlib.sha256(code.encode()).hexdigest(),
            source=source,
            status=VersionStatus.VALIDATED,
            created_at=datetime.now(UTC),
            parent_version_id=parent_version_id,
            draft_id=None,
            spec=effective_spec,
            backtest_report_id=None,
        )
        self._repository.save(version, self._account_id)
        logger.info(
            "strategy version edited: name=%s version=%d id=%s source=%s base=%s forked=%s",
            target_name,
            next_version,
            version.id,
            source,
            version_id,
            forking,
        )
        return version

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
        if (
            new_name != anchor.name
            and self._repository.latest_version_number(new_name, self._account_id) > 0
        ):
            raise StrategyNameConflictError(new_name)

        renamed_anchor = None
        for version in self._repository.list_all(anchor.name, account_id=self._account_id):
            renamed = replace(version, name=new_name)
            self._repository.save(renamed, self._account_id)
            if version.id == version_id:
                renamed_anchor = renamed
        logger.info("strategy family renamed: %s -> %s (id=%s)", anchor.name, new_name, version_id)
        assert renamed_anchor is not None
        return renamed_anchor

    def update_spec(self, version_id: str, spec: dict[str, object]) -> StrategyVersion:
        """Overwrite `version_id`'s spec snapshot in place with `spec` — an
        annotation-only edit, like `rename_family`: it never touches the
        generated code, never re-runs sandbox validation, and doesn't create
        a new version, because the spec snapshot is descriptive metadata for
        the trader/chart, not the tradeable artifact (that's the code, which
        `edit_code` always version-forks instead of mutating). Raises
        `ValueError` if `version_id` doesn't exist."""
        version = self._repository.get(version_id)
        if version is None:
            raise ValueError(f"no strategy version with id {version_id!r}")

        updated = replace(version, spec=spec)
        self._repository.save(updated, self._account_id)
        logger.info(
            "strategy version spec updated: name=%s version=%d id=%s",
            version.name,
            version.version,
            version.id,
        )
        return updated

    def list_versions(
        self, name: str | None = None, status: VersionStatus | None = None
    ) -> list[StrategyVersion]:
        return self._repository.list_all(name, status, self._account_id)

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
        active. Also how rollback works: activate an older version id.
        Always starts the newly activated version unpaused — including
        clearing any pause left over from the version it supersedes, so a
        paused bot doesn't stay silently hidden under a new version id."""
        version = self._repository.get(version_id)
        if version is None:
            raise ValueError(f"no strategy version with id {version_id!r}")

        instance = self._load_instance(version)

        previous_active = self._repository.get_active(version.name, self._account_id)
        if previous_active is not None and previous_active.id != version.id:
            self._repository.save(
                replace(previous_active, status=VersionStatus.ARCHIVED, paused=False),
                self._account_id,
            )

        activated = replace(version, status=VersionStatus.ACTIVE, paused=False)
        self._repository.save(activated, self._account_id)
        self._registry.resume(version.name)
        self._registry.register(version.name, instance)
        logger.info(
            "strategy version activated: name=%s version=%d id=%s",
            version.name,
            version.version,
            version.id,
        )
        return activated

    def archive_version(self, version_id: str) -> StrategyVersion:
        """Retires this version without deleting it: marks it ARCHIVED and,
        if it was the live ACTIVE version, unregisters it from the
        StrategyRegistry so the engine stops evaluating it on the next
        candle close. Unlike activate_version's implicit archive-on-
        supersede, this is a direct user action with no replacement
        version — the strategy family can end up with no active version at
        all. Raises `ValueError` if `version_id` doesn't exist, and
        `VersionAlreadyArchivedError` if it's already archived."""
        version = self._repository.get(version_id)
        if version is None:
            raise ValueError(f"no strategy version with id {version_id!r}")
        if version.status == VersionStatus.ARCHIVED:
            raise VersionAlreadyArchivedError(version_id)

        archived = replace(version, status=VersionStatus.ARCHIVED, paused=False)
        self._repository.save(archived, self._account_id)
        if version.status == VersionStatus.ACTIVE:
            self._registry.unregister(version.name)
        logger.info(
            "strategy version archived: name=%s version=%d id=%s",
            version.name,
            version.version,
            version.id,
        )
        return archived

    def delete_version(self, version_id: str) -> None:
        """Hard-deletes the version's DB row and its generated file, and clears
        `parent_version_id` on any child versions so they never point at a
        row that no longer exists. Refuses to delete a currently ACTIVE
        version — archive it (or activate a replacement) first, so the
        engine is never left pointing at a file that's about to disappear.
        Raises `ValueError` if `version_id` doesn't exist, and
        `VersionActiveError` if it's the active version."""
        version = self._repository.get(version_id)
        if version is None:
            raise ValueError(f"no strategy version with id {version_id!r}")
        if version.status == VersionStatus.ACTIVE:
            raise VersionActiveError(version_id)

        self._repository.delete(version_id)
        self._repository.clear_parent_references(version_id)
        (self._generated_dir / Path(version.file_path).name).unlink(missing_ok=True)
        logger.info(
            "strategy version deleted: name=%s version=%d id=%s",
            version.name,
            version.version,
            version.id,
        )

    def pause_version(self, version_id: str) -> StrategyVersion:
        """Suspends live trading for this ACTIVE version without
        deactivating or archiving it: the StrategyRegistry stops returning
        it to the engine, so no new entries are evaluated for it, but it
        stays ACTIVE and `resume_version` brings it straight back. Distinct
        from the engine-wide kill switch (`POST /engine/kill`), which pauses
        every strategy at once. Raises `ValueError` if `version_id` doesn't
        exist, and `VersionNotActiveError` if it isn't the active version."""
        version = self._repository.get(version_id)
        if version is None:
            raise ValueError(f"no strategy version with id {version_id!r}")
        if version.status != VersionStatus.ACTIVE:
            raise VersionNotActiveError(version_id)

        paused = replace(version, paused=True)
        self._repository.save(paused, self._account_id)
        self._registry.pause(version.name)
        logger.info(
            "strategy version paused: name=%s version=%d id=%s",
            version.name,
            version.version,
            version.id,
        )
        return paused

    def resume_version(self, version_id: str) -> StrategyVersion:
        """Reverses `pause_version`: the StrategyRegistry resumes returning
        this version to the engine. Raises `ValueError` if `version_id`
        doesn't exist, and `VersionNotActiveError` if it isn't the active
        version."""
        version = self._repository.get(version_id)
        if version is None:
            raise ValueError(f"no strategy version with id {version_id!r}")
        if version.status != VersionStatus.ACTIVE:
            raise VersionNotActiveError(version_id)

        resumed = replace(version, paused=False)
        self._repository.save(resumed, self._account_id)
        self._registry.resume(version.name)
        logger.info(
            "strategy version resumed: name=%s version=%d id=%s",
            version.name,
            version.version,
            version.id,
        )
        return resumed

    def backfill_missing_specs(self) -> int:
        """One-shot repair for versions recorded before spec snapshots were
        derived for manual saves: any version with no spec gets one derived
        from its own code's `StrategySpec` (symbols, timeframes, params).
        Versions whose code no longer validates are logged and skipped.
        Returns the number of versions backfilled. Safe to re-run."""
        backfilled = 0
        for version in self._repository.list_all(account_id=self._account_id):
            if version.spec is not None:
                continue
            try:
                instance = self._load_instance(version)
            except Exception:
                logger.exception(
                    "spec backfill skipped — code failed validation: name=%s version=%d",
                    version.name,
                    version.version,
                )
                continue
            self._repository.save(
                replace(version, spec=_derive_spec_snapshot(instance)), self._account_id
            )
            backfilled += 1
            logger.info(
                "spec snapshot backfilled: name=%s version=%d id=%s",
                version.name,
                version.version,
                version.id,
            )
        return backfilled

    def load_active_into_registry(self) -> None:
        """Called once at startup so a backend restart doesn't lose whichever
        AI-generated versions were active before it went down."""
        for version in self._repository.list_active(self._account_id):
            try:
                instance = self._load_instance(version)
            except Exception:
                logger.exception(
                    "active strategy version failed re-validation on startup: name=%s version=%d",
                    version.name,
                    version.version,
                )
                continue
            self._registry.register(version.name, instance)
            if version.paused:
                self._registry.pause(version.name)
            logger.info(
                "active strategy version loaded at startup: name=%s version=%d paused=%s",
                version.name,
                version.version,
                version.paused,
            )

    def _load_instance(self, version: StrategyVersion) -> Strategy:
        instance, errors = validate_and_load(self.get_code(version))
        if instance is None:
            raise StrategyValidationError(errors)
        return instance
