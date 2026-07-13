"""Strategy versioning & activation (§6.5, §8.1): saving generated code
records an immutable, hash-tracked version; activation registers it live and
archives whatever was active before — and doubles as rollback."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.shared.db.base import Base
from src.strategies.adapters.repository import StrategyVersionRepository
from src.strategies.application.versioning import (
    StrategyNameConflictError,
    StrategyValidationError,
    StrategyVersionService,
    VersionActiveError,
    VersionAlreadyArchivedError,
    VersionNotActiveError,
)
from src.strategies.domain.versioning import CodeSource, VersionStatus
from src.strategies.registry import StrategyRegistry

VALID_CODE = """
from src.strategies.domain.models import Direction, MarketContext, Signal, StrategySpec


class Sample:
    def __init__(self):
        self.spec = StrategySpec(
            name="sample", version=1, symbols=("XAUUSD",), entry_timeframe="M5",
            confirmation_timeframes=(), params={},
        )

    def evaluate(self, ctx: MarketContext):
        return None
"""

INVALID_CODE = "import os\nx = 1\n"


@pytest.fixture
def service(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    generated_dir = tmp_path / "generated"
    generated_dir.mkdir()
    registry = StrategyRegistry()
    repository = StrategyVersionRepository(session_factory)
    return StrategyVersionService(repository, registry, generated_dir), registry


def test_save_generated_code_writes_file_and_version(service):
    svc, _ = service
    version = svc.save_generated_code(
        name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED
    )
    assert version.version == 1
    assert version.status == VersionStatus.VALIDATED
    assert version.parent_version_id is None
    assert svc.get_code(version) == VALID_CODE


def test_save_generated_code_rejects_invalid_code(service):
    svc, _ = service
    with pytest.raises(StrategyValidationError):
        svc.save_generated_code(name="evil", code=INVALID_CODE, source=CodeSource.AI_GENERATED)


def test_versions_increment_and_chain_parent(service):
    svc, _ = service
    v1 = svc.save_generated_code(name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED)
    svc.activate_version(v1.id)
    v2 = svc.save_generated_code(name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED)
    assert v2.version == 2
    assert v2.parent_version_id == v1.id


def test_activate_registers_and_archives_previous(service):
    svc, registry = service
    v1 = svc.save_generated_code(name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED)
    svc.activate_version(v1.id)
    assert registry.get("sample") is not None
    assert svc.get_version(v1.id).status == VersionStatus.ACTIVE

    v2 = svc.save_generated_code(name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED)
    svc.activate_version(v2.id)
    assert svc.get_version(v1.id).status == VersionStatus.ARCHIVED
    assert svc.get_version(v2.id).status == VersionStatus.ACTIVE


def test_rollback_is_activating_an_older_version(service):
    svc, registry = service
    v1 = svc.save_generated_code(name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED)
    svc.activate_version(v1.id)
    v2 = svc.save_generated_code(name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED)
    svc.activate_version(v2.id)

    rolled_back = svc.activate_version(v1.id)
    assert rolled_back.status == VersionStatus.ACTIVE
    assert svc.get_version(v2.id).status == VersionStatus.ARCHIVED


def test_activate_unknown_version_raises(service):
    svc, _ = service
    with pytest.raises(ValueError, match="no strategy version"):
        svc.activate_version("does-not-exist")


def test_duplicate_version_forks_into_new_family(service):
    svc, _ = service
    v1 = svc.save_generated_code(name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED)
    dup = svc.duplicate_version(v1.id, new_name="sample_fork")
    assert dup.name == "sample_fork"
    assert dup.version == 1
    assert dup.parent_version_id is None
    assert dup.id != v1.id
    assert svc.get_code(dup) == VALID_CODE
    # The original is untouched — duplicate is a fork, not a supersession.
    assert svc.get_version(v1.id).name == "sample"


def test_duplicate_version_rejects_name_already_in_use(service):
    svc, _ = service
    v1 = svc.save_generated_code(name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED)
    with pytest.raises(StrategyNameConflictError):
        svc.duplicate_version(v1.id, new_name="sample")


def test_duplicate_version_unknown_version_raises(service):
    svc, _ = service
    with pytest.raises(ValueError, match="no strategy version"):
        svc.duplicate_version("does-not-exist", new_name="sample_fork")


def test_duplicate_version_with_symbols_override_rewrites_and_revalidates(service):
    svc, _ = service
    v1 = svc.save_generated_code(name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED)
    dup = svc.duplicate_version(v1.id, new_name="sample_fork", symbols=("BTCUSD", "XAGUSD"))
    assert 'symbols=("BTCUSD", "XAGUSD")' in svc.get_code(dup)


NO_SYMBOLS_LITERAL_CODE = """
from src.strategies.domain.models import Direction, MarketContext, Signal, StrategySpec

SYMBOLS = ("XAUUSD",)


class Sample:
    def __init__(self):
        self.spec = StrategySpec(
            name="sample", version=1, symbols=SYMBOLS, entry_timeframe="M5",
            confirmation_timeframes=(), params={},
        )

    def evaluate(self, ctx: MarketContext):
        return None
"""


def test_duplicate_version_symbols_override_fails_without_literal(service):
    svc, _ = service
    v1 = svc.save_generated_code(
        name="sample", code=NO_SYMBOLS_LITERAL_CODE, source=CodeSource.AI_GENERATED
    )
    with pytest.raises(StrategyValidationError):
        svc.duplicate_version(v1.id, new_name="sample_fork", symbols=("BTCUSD",))


def test_rename_family_updates_every_version(service):
    svc, _ = service
    v1 = svc.save_generated_code(name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED)
    svc.activate_version(v1.id)
    v2 = svc.save_generated_code(name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED)

    renamed = svc.rename_family(v1.id, "renamed_sample")
    assert renamed.name == "renamed_sample"
    assert svc.get_version(v1.id).name == "renamed_sample"
    assert svc.get_version(v2.id).name == "renamed_sample"
    # get_code must still resolve from the stored file_path, not the new name.
    assert svc.get_code(svc.get_version(v1.id)) == VALID_CODE


def test_rename_family_rejects_name_already_in_use(service):
    svc, _ = service
    v1 = svc.save_generated_code(name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED)
    svc.save_generated_code(name="other", code=VALID_CODE, source=CodeSource.AI_GENERATED)
    with pytest.raises(StrategyNameConflictError):
        svc.rename_family(v1.id, "other")


def test_rename_family_unknown_version_raises(service):
    svc, _ = service
    with pytest.raises(ValueError, match="no strategy version"):
        svc.rename_family("does-not-exist", "renamed")


def test_load_active_into_registry_restores_after_restart(service, tmp_path):
    svc, registry = service
    v1 = svc.save_generated_code(name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED)
    svc.activate_version(v1.id)

    fresh_registry = StrategyRegistry()
    repository = StrategyVersionRepository(
        sessionmaker(bind=create_engine(f"sqlite:///{tmp_path}/test.db"), expire_on_commit=False)
    )
    fresh_service = StrategyVersionService(repository, fresh_registry, tmp_path / "generated")
    fresh_service.load_active_into_registry()
    assert fresh_registry.get("sample") is not None


def test_load_active_into_registry_restores_pause_after_restart(service, tmp_path):
    svc, registry = service
    v1 = svc.save_generated_code(name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED)
    svc.activate_version(v1.id)
    svc.pause_version(v1.id)

    fresh_registry = StrategyRegistry()
    repository = StrategyVersionRepository(
        sessionmaker(bind=create_engine(f"sqlite:///{tmp_path}/test.db"), expire_on_commit=False)
    )
    fresh_service = StrategyVersionService(repository, fresh_registry, tmp_path / "generated")
    fresh_service.load_active_into_registry()
    assert fresh_registry.get("sample") is None


def test_pause_and_resume_active_version(service):
    svc, registry = service
    v1 = svc.save_generated_code(name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED)
    svc.activate_version(v1.id)

    paused = svc.pause_version(v1.id)
    assert paused.paused is True
    assert paused.status == VersionStatus.ACTIVE
    assert registry.get("sample") is None

    resumed = svc.resume_version(v1.id)
    assert resumed.paused is False
    assert registry.get("sample") is not None


def test_pause_non_active_version_raises(service):
    svc, _ = service
    v1 = svc.save_generated_code(name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED)
    with pytest.raises(VersionNotActiveError):
        svc.pause_version(v1.id)


def test_resume_non_active_version_raises(service):
    svc, _ = service
    v1 = svc.save_generated_code(name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED)
    with pytest.raises(VersionNotActiveError):
        svc.resume_version(v1.id)


def test_pause_unknown_version_raises(service):
    svc, _ = service
    with pytest.raises(ValueError, match="no strategy version"):
        svc.pause_version("does-not-exist")


def test_activating_new_version_clears_pause_from_previous_version(service):
    """A stale pause on a superseded version must not leak into its
    successor — activating a new version of the same name always starts
    unpaused, even if the version it replaces was paused."""
    svc, registry = service
    v1 = svc.save_generated_code(name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED)
    svc.activate_version(v1.id)
    svc.pause_version(v1.id)
    assert registry.get("sample") is None

    v2 = svc.save_generated_code(name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED)
    svc.activate_version(v2.id)
    assert registry.get("sample") is not None
    assert svc.get_version(v2.id).paused is False


def test_archive_active_version_unregisters_it(service):
    svc, registry = service
    v1 = svc.save_generated_code(name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED)
    svc.activate_version(v1.id)

    archived = svc.archive_version(v1.id)
    assert archived.status == VersionStatus.ARCHIVED
    assert registry.get("sample") is None


def test_archive_already_archived_version_raises(service):
    svc, _ = service
    v1 = svc.save_generated_code(name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED)
    svc.activate_version(v1.id)
    svc.archive_version(v1.id)
    with pytest.raises(VersionAlreadyArchivedError):
        svc.archive_version(v1.id)


def test_archive_unknown_version_raises(service):
    svc, _ = service
    with pytest.raises(ValueError, match="no strategy version"):
        svc.archive_version("does-not-exist")


def test_delete_validated_version_removes_row_and_file(service):
    svc, _ = service
    v1 = svc.save_generated_code(name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED)
    file_path = svc._generated_dir / "sample_v1.py"  # noqa: SLF001 - verifying disk cleanup
    assert file_path.exists()

    svc.delete_version(v1.id)
    assert svc.get_version(v1.id) is None
    assert not file_path.exists()


def test_delete_active_version_raises(service):
    svc, _ = service
    v1 = svc.save_generated_code(name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED)
    svc.activate_version(v1.id)
    with pytest.raises(VersionActiveError):
        svc.delete_version(v1.id)


def test_delete_unknown_version_raises(service):
    svc, _ = service
    with pytest.raises(ValueError, match="no strategy version"):
        svc.delete_version("does-not-exist")


def test_delete_version_clears_parent_id_on_children(service):
    svc, _ = service
    v1 = svc.save_generated_code(name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED)
    v2 = svc.edit_code(v1.id, VALID_CODE)
    assert v2.parent_version_id == v1.id

    svc.delete_version(v1.id)

    refreshed = svc.get_version(v2.id)
    assert refreshed is not None
    assert refreshed.parent_version_id is None


def test_edit_code_saves_new_version_parented_on_edited_version(service):
    svc, _ = service
    v1 = svc.save_generated_code(name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED)
    svc.activate_version(v1.id)
    v2 = svc.save_generated_code(name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED)

    # Editing v1 (not the active v2) must parent on v1, not silently rebase
    # onto whatever's currently active.
    edited = svc.edit_code(v1.id, VALID_CODE)
    assert edited.version == 3
    assert edited.parent_version_id == v1.id
    assert edited.status == VersionStatus.VALIDATED
    assert edited.source == CodeSource.MANUAL
    assert svc.get_code(edited) == VALID_CODE
    assert v2.id  # unaffected by the edit


def test_edit_code_carries_over_spec_snapshot(service):
    svc, _ = service
    v1 = svc.save_generated_code(
        name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED, spec={"name": "sample"}
    )
    edited = svc.edit_code(v1.id, VALID_CODE)
    assert edited.spec == {"name": "sample"}


def test_edit_code_accepts_source_override(service):
    svc, _ = service
    v1 = svc.save_generated_code(name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED)
    edited = svc.edit_code(v1.id, VALID_CODE, source=CodeSource.AI_REFINED)
    assert edited.source == CodeSource.AI_REFINED


def test_edit_code_rejects_invalid_code(service):
    svc, _ = service
    v1 = svc.save_generated_code(name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED)
    with pytest.raises(StrategyValidationError):
        svc.edit_code(v1.id, INVALID_CODE)


def test_edit_code_unknown_version_raises(service):
    svc, _ = service
    with pytest.raises(ValueError, match="no strategy version"):
        svc.edit_code("does-not-exist", VALID_CODE)


def test_edit_code_with_new_name_forks_into_new_family(service):
    svc, _ = service
    v1 = svc.save_generated_code(
        name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED, spec={"name": "sample"}
    )
    forked = svc.edit_code(v1.id, VALID_CODE, new_name="sample_fork")
    assert forked.name == "sample_fork"
    assert forked.version == 1
    assert forked.parent_version_id is None
    assert forked.spec == {"name": "sample"}
    # The original family is untouched — this is a fork, not a supersession.
    assert svc.get_version(v1.id).name == "sample"


def test_edit_code_new_name_equal_to_own_family_still_increments(service):
    svc, _ = service
    v1 = svc.save_generated_code(name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED)
    edited = svc.edit_code(v1.id, VALID_CODE, new_name="sample")
    assert edited.version == 2
    assert edited.parent_version_id == v1.id


def test_edit_code_new_name_conflict_raises(service):
    svc, _ = service
    v1 = svc.save_generated_code(name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED)
    svc.save_generated_code(name="other", code=VALID_CODE, source=CodeSource.AI_GENERATED)
    with pytest.raises(StrategyNameConflictError):
        svc.edit_code(v1.id, VALID_CODE, new_name="other")


def test_edit_code_spec_override(service):
    svc, _ = service
    v1 = svc.save_generated_code(
        name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED, spec={"name": "sample"}
    )
    edited = svc.edit_code(v1.id, VALID_CODE, spec={"name": "sample", "entry_rules": "new rule"})
    assert edited.spec == {"name": "sample", "entry_rules": "new rule"}


def test_edit_code_spec_override_can_clear_spec(service):
    svc, _ = service
    v1 = svc.save_generated_code(
        name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED, spec={"name": "sample"}
    )
    edited = svc.edit_code(v1.id, VALID_CODE, spec=None)
    assert edited.spec is None
