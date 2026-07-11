"""Strategy version records (§6.5, §8.1): every generated strategy file is
tracked here with its hash, parent, and backtest result so the AI
refinement loop (Phase 7) and the activation UI can diff/rollback.

Kept separate from `domain/models.py` (the sandboxed `Strategy` contract
itself) because this is bookkeeping metadata, never seen by generated code.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class VersionStatus(StrEnum):
    VALIDATED = "validated"  # passed sandbox validation, not yet activated
    ACTIVE = "active"  # currently registered in the StrategyRegistry
    ARCHIVED = "archived"  # was active, superseded by a newer/rolled-back version


class CodeSource(StrEnum):
    AI_GENERATED = "ai_generated"
    MANUAL = "manual"
    AI_REFINED = "ai_refined"  # produced by the 10-trade refinement loop (§8.2)


@dataclass(frozen=True)
class StrategyVersion:
    id: str
    name: str
    version: int
    file_path: str
    code_hash: str
    source: CodeSource
    status: VersionStatus
    created_at: datetime
    parent_version_id: str | None = None
    draft_id: str | None = None
    spec: dict[str, Any] | None = None
    backtest_report_id: str | None = None
