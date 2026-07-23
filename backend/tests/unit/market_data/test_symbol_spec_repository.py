import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.market_data.adapters.replay import SymbolSpec
from src.market_data.adapters.symbol_spec_repository import SymbolSpecRepository
from src.shared.db.base import Base


@pytest.fixture
def repository(tmp_path) -> SymbolSpecRepository:
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    return SymbolSpecRepository(sessionmaker(bind=engine, expire_on_commit=False))


def spec(**overrides) -> SymbolSpec:
    defaults = dict(
        point=0.01,
        digits=2,
        stops_level=10,
        contract_size=100.0,
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
    )
    return SymbolSpec(**{**defaults, **overrides})


def test_get_missing_symbol_returns_none(repository):
    assert repository.get("XAUUSD") is None


def test_roundtrip_preserves_spec(repository):
    repository.upsert("XAUUSD", spec())
    assert repository.get("XAUUSD") == spec()


def test_upsert_overwrites_existing_spec(repository):
    repository.upsert("Volatility 75 Index", spec(point=0.01, digits=2))
    repository.upsert("Volatility 75 Index", spec(point=0.001, digits=3))

    stored = repository.get("Volatility 75 Index")
    assert stored.point == 0.001
    assert stored.digits == 3


def test_specs_are_keyed_per_symbol(repository):
    repository.upsert("XAUUSD", spec(contract_size=100.0))
    repository.upsert("XAGUSD", spec(contract_size=5000.0))

    assert repository.get("XAUUSD").contract_size == 100.0
    assert repository.get("XAGUSD").contract_size == 5000.0


def test_specs_are_keyed_per_account(repository):
    """Different brokers quote different point/digits/stops_level for a
    nominally identical symbol — a shared spec keyed only on `symbol` would
    silently mix broker-specific facts across accounts."""
    repository.upsert("XAUUSD", spec(digits=2, point=0.01), account_id="ftmo-1")
    repository.upsert("XAUUSD", spec(digits=3, point=0.001), account_id="ftmo-2")

    assert repository.get("XAUUSD", account_id="ftmo-1").digits == 2
    assert repository.get("XAUUSD", account_id="ftmo-2").digits == 3
    assert repository.get("XAUUSD", account_id="default") is None
