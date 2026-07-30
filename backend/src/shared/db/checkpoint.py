"""Periodic SQLite WAL checkpoint. `PRAGMA journal_mode=wal` (set for every
sync engine this project creates) lets the `-wal` file grow unbounded
between checkpoints — observed at hundreds of MB uncheckpointed on this
project's dev db. No-ops on any non-SQLite engine (e.g. after the planned
PostgreSQL migration, see IMPLEMENTATION_PLAN.md) since `wal_checkpoint` is
SQLite-specific syntax.

Not a domain module: this touches the shared engine, not any one module's
business data, so it lives in shared/db like `base.py` rather than under a
domain/application split.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)


class WalCheckpointService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        interval_s: float,
        enabled: bool = True,
    ) -> None:
        self._session_factory = session_factory
        self._interval_s = interval_s
        self._enabled = enabled
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if not self._enabled:
            logger.info("WAL checkpoint disabled (configs/maintenance.yaml wal_checkpoint.enabled)")
            return
        self._task = asyncio.create_task(self._run(), name="sqlite-wal-checkpoint")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while True:
            await asyncio.to_thread(self.checkpoint_once)
            await asyncio.sleep(self._interval_s)

    def checkpoint_once(self) -> None:
        with self._session_factory() as session:
            if session.get_bind().dialect.name != "sqlite":
                return
            try:
                session.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
            except Exception:
                logger.exception("WAL checkpoint failed")
