"""Activity log domain: one persisted line of what the bot did and why.

Every `logging.getLogger("src.*")` call at INFO+ ends up here too (see
`shared/logging/adapters/handler.py`) — this is what backs the "why did/didn't
it take a position" question after the fact, not just live stdout.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, kw_only=True)
class LogEntry:
    id: int | None
    created_at: datetime
    level: str
    logger: str
    message: str
