from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.shared.db.base import Base
from src.shared.db.checkpoint import WalCheckpointService


def make_sqlite_session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    with engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode=wal"))
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


class _FakeDialect:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeSession:
    def __init__(self, dialect_name: str, executed: list[str]) -> None:
        self._dialect_name = dialect_name
        self._executed = executed

    def __enter__(self) -> "_FakeSession":
        return self

    def __exit__(self, *exc_info) -> None:
        return None

    def get_bind(self) -> _FakeDialect:
        return type("Bind", (), {"dialect": _FakeDialect(self._dialect_name)})()

    def execute(self, statement) -> None:
        self._executed.append(str(statement))


def test_checkpoint_once_runs_without_error_on_sqlite(tmp_path):
    session_factory = make_sqlite_session_factory(tmp_path)
    service = WalCheckpointService(session_factory, interval_s=60)

    service.checkpoint_once()  # must not raise


def test_checkpoint_once_skips_non_sqlite_dialects():
    executed: list[str] = []
    service = WalCheckpointService(lambda: _FakeSession("postgresql", executed), interval_s=60)

    service.checkpoint_once()

    assert executed == []


def test_checkpoint_once_runs_pragma_on_sqlite_dialect():
    executed: list[str] = []
    service = WalCheckpointService(lambda: _FakeSession("sqlite", executed), interval_s=60)

    service.checkpoint_once()

    assert len(executed) == 1
    assert "wal_checkpoint" in executed[0].lower()


async def test_start_is_a_noop_when_disabled(tmp_path):
    session_factory = make_sqlite_session_factory(tmp_path)
    service = WalCheckpointService(session_factory, interval_s=60, enabled=False)

    service.start()

    assert service._task is None
