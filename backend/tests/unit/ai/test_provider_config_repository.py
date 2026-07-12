"""Per-task provider override persistence roundtrips (AI_PROVIDER_SETTINGS_PLAN.md
§6.3) — mirrors `tests/unit/journal/test_repository.py`'s real-sqlite pattern."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.ai.adapters.provider_config_repository import ProviderConfigRepository
from src.shared.db.base import Base


@pytest.fixture
def repository(tmp_path) -> ProviderConfigRepository:
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    return ProviderConfigRepository(sessionmaker(bind=engine, expire_on_commit=False))


def test_get_all_empty_by_default(repository):
    assert repository.get_all() == {}


def test_set_then_get_all_roundtrips(repository):
    override = repository.set("pdf_extraction", "ollama", "hermes3:8b")
    assert override.task == "pdf_extraction"
    assert override.provider == "ollama"
    assert override.model == "hermes3:8b"

    all_overrides = repository.get_all()
    assert set(all_overrides) == {"pdf_extraction"}
    stored = all_overrides["pdf_extraction"]
    # updated_at is stored as whole-second epoch (matches DraftRepository's
    # created_at convention), so it loses sub-second precision on roundtrip.
    assert stored.task == override.task
    assert stored.provider == override.provider
    assert stored.model == override.model
    assert int(stored.updated_at.timestamp()) == int(override.updated_at.timestamp())


def test_set_overwrites_existing_override_for_same_task(repository):
    repository.set("pdf_extraction", "ollama", "hermes3:8b")
    repository.set("pdf_extraction", "claude_code", "sonnet")

    all_overrides = repository.get_all()
    assert len(all_overrides) == 1
    assert all_overrides["pdf_extraction"].provider == "claude_code"
    assert all_overrides["pdf_extraction"].model == "sonnet"


def test_clear_removes_the_override(repository):
    repository.set("pdf_extraction", "ollama", "hermes3:8b")
    repository.clear("pdf_extraction")
    assert repository.get_all() == {}


def test_clear_is_a_noop_for_a_task_with_no_override(repository):
    repository.clear("pdf_extraction")  # must not raise
    assert repository.get_all() == {}


def test_multiple_tasks_are_independent(repository):
    repository.set("pdf_extraction", "ollama", "hermes3:8b")
    repository.set("code_generation", "claude_code", "sonnet")

    all_overrides = repository.get_all()
    assert set(all_overrides) == {"pdf_extraction", "code_generation"}
