"""Settings-page provider selection domain models (AI_PROVIDER_SETTINGS_PLAN.md
§4.3/§6.2). Framework-free — no pydantic, no SQLAlchemy; `ai/api/schemas.py`
mirrors these for the wire, `ai/adapters/orm.py` mirrors `TaskProviderOverride`
for storage.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

#: The 4 AI tasks the settings page lists (AI_PROVIDER_SETTINGS_PLAN.md §1),
#: matching the literal `for_task(...)` strings in `pdf_to_strategy.py` /
#: `refinement_loop.py`. `code_regeneration.py` deliberately reuses
#: `code_generation` rather than getting its own entry here — see that
#: module's docstring. A task missing here can never get a settings-page
#: override — `for_task()` silently keeps using `configs/ai.yaml`'s default
#: provider for it regardless of what the settings page shows selected for
#: other tasks.
KNOWN_TASKS = ("pdf_extraction", "code_generation", "ten_trade_review", "code_refinement")


@dataclass(frozen=True)
class TaskProviderOverride:
    """One operator-set `{task: provider+model}` pin, stored in the
    `ai_task_provider_override` table. Takes precedence over the
    `configs/ai.yaml` default for that task until cleared."""

    task: str
    provider: str
    model: str
    updated_at: datetime


@dataclass(frozen=True)
class TaskProviderStatus:
    """A task's current effective provider/model — what `LLMRouter.for_task()`
    would actually build right now — plus whether that came from an override
    or the YAML default, and whether it's usable without revealing secrets."""

    task: str
    provider: str
    model: str
    source: str  # "override" | "default"
    configured: bool


@dataclass(frozen=True)
class ProviderTestResult:
    """Outcome of a live `POST /ai/settings/providers/{provider}/test` probe
    (a throwaway `complete()` call) — never raises, so the settings page can
    render pass/fail inline."""

    provider: str
    ok: bool
    message: str | None = None
    reply: str | None = None
