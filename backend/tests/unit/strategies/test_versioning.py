"""Strategy versioning & activation (§6.5, §8.1): saving generated code
records an immutable, hash-tracked version; activation registers it live and
archives whatever was active before — and doubles as rollback."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.shared.db.base import Base
from src.strategies.adapters.repository import StrategyVersionRepository
from src.strategies.application.versioning import StrategyValidationError, StrategyVersionService
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
