import logging
import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.activity.adapters.log_handler import attach_activity_log_handler
from src.activity.adapters.repository import ActivityLogRepository
from src.shared.db.base import Base


@pytest.fixture
def repository(tmp_path) -> ActivityLogRepository:
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    return ActivityLogRepository(sessionmaker(bind=engine, expire_on_commit=False))


def test_info_log_under_src_namespace_is_persisted(repository):
    listener = attach_activity_log_handler(repository)
    logger = logging.getLogger("src.engine.application.trade_loop")
    logger.setLevel(logging.INFO)
    try:
        logger.info("signal: XAUUSD buy strategy=breakout_v1 reason=breakout")
        # QueueListener drains on its own thread — give it a beat.
        deadline = time.monotonic() + 2
        entries: list = []
        while time.monotonic() < deadline:
            entries, total = repository.search(q="XAUUSD")
            if total:
                break
            time.sleep(0.05)
    finally:
        listener.stop()
        logging.getLogger("src").handlers.clear()
        logger.setLevel(logging.NOTSET)

    assert len(entries) == 1
    assert "XAUUSD" in entries[0].message
    assert entries[0].logger == "src.engine.application.trade_loop"
    assert entries[0].level == "INFO"


def test_logs_outside_src_namespace_are_not_persisted(repository):
    listener = attach_activity_log_handler(repository)
    logger = logging.getLogger("httpx")
    logger.setLevel(logging.INFO)
    try:
        logger.info("unrelated third-party log line")
        time.sleep(0.2)
        _, total = repository.search()
    finally:
        listener.stop()
        logging.getLogger("src").handlers.clear()
        logger.setLevel(logging.NOTSET)

    assert total == 0
