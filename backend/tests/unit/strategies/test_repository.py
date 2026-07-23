from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.shared.db.base import Base
from src.strategies.adapters.repository import StrategyVersionRepository
from src.strategies.domain.versioning import CodeSource, StrategyVersion, VersionStatus


@pytest.fixture
def repository(tmp_path) -> StrategyVersionRepository:
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    return StrategyVersionRepository(sessionmaker(bind=engine, expire_on_commit=False))


def make_version(id: str, name: str = "breakout_v1", **kw) -> StrategyVersion:
    defaults = dict(
        id=id,
        name=name,
        version=1,
        file_path=f"src/strategies/generated/{name}_v1.py",
        code_hash="abc123",
        source=CodeSource.MANUAL,
        status=VersionStatus.VALIDATED,
        created_at=datetime(2026, 7, 10, tzinfo=UTC),
    )
    return StrategyVersion(**{**defaults, **kw})


def test_roundtrip_preserves_version(repository):
    version = make_version("1")
    repository.save(version)
    assert repository.get("1") == version


def test_list_all_and_active_scope_to_account(repository):
    repository.save(make_version("1", status=VersionStatus.ACTIVE), account_id="ftmo-1")
    repository.save(make_version("2", status=VersionStatus.ACTIVE), account_id="ftmo-2")

    assert [v.id for v in repository.list_all(account_id="ftmo-1")] == ["1"]
    assert [v.id for v in repository.list_active(account_id="ftmo-1")] == ["1"]
    assert [v.id for v in repository.list_active(account_id="ftmo-2")] == ["2"]
    assert repository.list_all(account_id="default") == []


def test_same_name_can_be_active_on_two_different_accounts(repository):
    """A strategy assignment is 'this bot, on this account' — the same
    family name existing on two accounts is not a conflict."""
    repository.save(
        make_version("1", name="breakout_v1", status=VersionStatus.ACTIVE), account_id="ftmo-1"
    )
    repository.save(
        make_version("2", name="breakout_v1", status=VersionStatus.ACTIVE), account_id="ftmo-2"
    )

    assert repository.get_active("breakout_v1", account_id="ftmo-1").id == "1"
    assert repository.get_active("breakout_v1", account_id="ftmo-2").id == "2"


def test_latest_version_number_scopes_to_account(repository):
    repository.save(make_version("1", name="breakout_v1", version=1), account_id="ftmo-1")
    repository.save(make_version("2", name="breakout_v1", version=2), account_id="ftmo-1")
    repository.save(make_version("3", name="breakout_v1", version=1), account_id="ftmo-2")

    assert repository.latest_version_number("breakout_v1", account_id="ftmo-1") == 2
    assert repository.latest_version_number("breakout_v1", account_id="ftmo-2") == 1
    assert repository.latest_version_number("breakout_v1", account_id="default") == 0
