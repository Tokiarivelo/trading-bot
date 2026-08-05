from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.activity.adapters.signal_decision_repository import SignalDecisionRepository
from src.activity.domain.models import SignalDecision
from src.shared.db.base import Base


@pytest.fixture
def repository(tmp_path) -> SignalDecisionRepository:
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    return SignalDecisionRepository(sessionmaker(bind=engine, expire_on_commit=False))


def _decision(
    signal_id: str,
    *,
    at: int = 1000,
    bot: str = "normal/xauusd/breakout_v1",
    account_id: str = "default",
) -> SignalDecision:
    return SignalDecision(
        signal_id=signal_id,
        account_id=account_id,
        bot=bot,
        strategy="breakout_v1",
        symbol="XAUUSD",
        timeframe="M5",
        direction="buy",
        price=2412.35,
        created_at=datetime.fromtimestamp(at, tz=UTC),
        outcome="skipped",
        reason="retest of demand",
        confidence=0.8,
    )


def test_save_and_list_round_trips_every_field(repository):
    repository.save(_decision("a"))

    (loaded,) = repository.list_for_bot(bot="normal/xauusd/breakout_v1")

    assert loaded == _decision("a")


def test_list_for_bot_is_oldest_first_and_scoped(repository):
    repository.save(_decision("a", at=2000))
    repository.save(_decision("b", at=1000))
    repository.save(_decision("c", at=1500, bot="normal/xauusd/other"))
    repository.save(_decision("d", at=1500, account_id="second"))

    ids = [d.signal_id for d in repository.list_for_bot(bot="normal/xauusd/breakout_v1")]

    assert ids == ["b", "a"]


def test_list_for_bot_filters_the_time_range(repository):
    repository.save(_decision("a", at=1000))
    repository.save(_decision("b", at=3000))

    ids = [
        d.signal_id
        for d in repository.list_for_bot(
            bot="normal/xauusd/breakout_v1", created_from=2000, created_to=4000
        )
    ]

    assert ids == ["b"]


def test_set_outcome_updates_outcome_and_reason(repository):
    repository.save(_decision("a"))

    changed = repository.set_outcome("a", "htf_veto", reason="retest of demand — M15 trend down")

    assert changed is True
    (loaded,) = repository.list_for_bot(bot="normal/xauusd/breakout_v1")
    assert loaded.outcome == "htf_veto"
    assert loaded.reason == "retest of demand — M15 trend down"


def test_set_outcome_cannot_downgrade_an_opened_decision(repository):
    repository.save(_decision("a"))
    repository.set_outcome("a", "opened")

    changed = repository.set_outcome("a", "risk_rejected", reason="TP2: below min lot")

    assert changed is False
    (loaded,) = repository.list_for_bot(bot="normal/xauusd/breakout_v1")
    assert loaded.outcome == "opened"


def test_set_outcome_on_unknown_signal_id_is_a_no_op(repository):
    assert repository.set_outcome("missing", "opened") is False


def test_earliest_created_at_is_none_when_empty(repository):
    assert repository.earliest_created_at() is None


def test_earliest_created_at_is_per_account(repository):
    repository.save(_decision("a", at=5000))
    repository.save(_decision("b", at=1000, account_id="second"))

    assert repository.earliest_created_at() == 5000
    assert repository.earliest_created_at(account_id="second") == 1000
