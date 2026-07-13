"""User-triggered AI code regeneration (§6.5 code editor): free-form
instructions against an existing strategy version always produce a new
'validated' version parented on the one they started from — never active,
and rejected input never touches disk."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.ai.application.code_regeneration import CodeRegenerationService
from src.ai.application.llm_router import LLMProviderNotConfiguredError
from src.ai.ports.llm import LLMCallError
from src.shared.db.base import Base
from src.strategies.adapters.repository import StrategyVersionRepository
from src.strategies.application.versioning import StrategyNameConflictError, StrategyVersionService
from src.strategies.domain.versioning import CodeSource, VersionStatus
from src.strategies.registry import StrategyRegistry

VALID_CODE = """
from src.strategies.domain.models import Direction, MarketContext, Signal, StrategySpec


class Sample:
    def __init__(self):
        self.spec = StrategySpec(
            name="sample", version=1, symbols=("XAUUSD",), entry_timeframe="M5",
            confirmation_timeframes=(), params={},
        )

    def evaluate(self, ctx: MarketContext):
        return None
"""

REGENERATED_CODE = VALID_CODE + "\n# regenerated\n"


class FakeRegenerationLLM:
    def __init__(self, code: str) -> None:
        self.code = code
        self.last_message = None

    async def complete(self, message, *, max_tokens=4096):
        self.last_message = message
        return f"```python\n{self.code}\n```"


class InvalidCodeLLM:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, message, *, max_tokens=4096):
        self.calls += 1
        return "import os\nx = 1\n"


class RetryThenValidLLM:
    """First completion fails the sandbox (forbidden import); the retry
    prompt (fed the sandbox's error) gets a valid one — mirrors an LLM
    self-correcting once shown what it broke."""

    def __init__(self, bad_code: str, good_code: str) -> None:
        self.bad_code = bad_code
        self.good_code = good_code
        self.calls = 0

    async def complete(self, message, *, max_tokens=4096):
        self.calls += 1
        code = self.bad_code if self.calls == 1 else self.good_code
        return f"```python\n{code}\n```"


class FailingLLM:
    async def complete(self, message, *, max_tokens=4096):
        raise LLMCallError("provider call failed")


class UnconfiguredRouter:
    def for_task(self, task: str):
        raise LLMProviderNotConfiguredError("no key set")


class FakeRouter:
    def __init__(self, llm) -> None:
        self._llm = llm

    def for_task(self, task: str):
        assert task == "code_generation"
        return self._llm


@pytest.fixture
def strategy_versions(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    generated_dir = tmp_path / "generated"
    generated_dir.mkdir()
    return StrategyVersionService(
        StrategyVersionRepository(session_factory), StrategyRegistry(), generated_dir
    )


async def test_regenerate_saves_new_version(strategy_versions):
    v1 = strategy_versions.save_generated_code(
        name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED
    )
    llm = FakeRegenerationLLM(REGENERATED_CODE)
    service = CodeRegenerationService(strategy_versions, FakeRouter(llm))

    result = await service.regenerate(v1.id, "only trade during the London session")

    assert result.is_valid
    assert result.new_version_id is not None
    assert result.code == REGENERATED_CODE.strip()
    new_version = strategy_versions.get_version(result.new_version_id)
    assert new_version.parent_version_id == v1.id
    assert new_version.source == CodeSource.AI_REFINED
    assert new_version.status == VersionStatus.VALIDATED
    assert "only trade during the London session" in llm.last_message.user


async def test_regenerate_invalid_code_returns_sandbox_errors(strategy_versions):
    v1 = strategy_versions.save_generated_code(
        name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED
    )
    llm = InvalidCodeLLM()
    service = CodeRegenerationService(strategy_versions, FakeRouter(llm))

    result = await service.regenerate(v1.id, "add an os import")

    assert not result.is_valid
    assert result.new_version_id is None
    assert result.sandbox_errors
    # 1 initial completion + 2 retries (MAX_ATTEMPTS=3 sandbox checks total),
    # then gives up rather than looping forever against an LLM that never
    # fixes the problem.
    assert llm.calls == 3


async def test_regenerate_retries_after_sandbox_rejection_then_succeeds(strategy_versions):
    v1 = strategy_versions.save_generated_code(
        name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED
    )
    llm = RetryThenValidLLM(bad_code="import os\nx = 1\n", good_code=REGENERATED_CODE)
    service = CodeRegenerationService(strategy_versions, FakeRouter(llm))

    result = await service.regenerate(v1.id, "add an os import, then use pandas instead")

    assert result.is_valid
    assert result.new_version_id is not None
    assert result.code == REGENERATED_CODE.strip()
    assert llm.calls == 2
    new_version = strategy_versions.get_version(result.new_version_id)
    assert new_version.parent_version_id == v1.id


async def test_regenerate_unknown_version_raises(strategy_versions):
    router = FakeRouter(FakeRegenerationLLM(VALID_CODE))
    service = CodeRegenerationService(strategy_versions, router)
    with pytest.raises(ValueError, match="no strategy version"):
        await service.regenerate("does-not-exist", "tighten the stop loss")


async def test_regenerate_propagates_llm_call_error(strategy_versions):
    v1 = strategy_versions.save_generated_code(
        name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED
    )
    service = CodeRegenerationService(strategy_versions, FakeRouter(FailingLLM()))
    with pytest.raises(LLMCallError):
        await service.regenerate(v1.id, "tighten the stop loss")


async def test_regenerate_propagates_provider_not_configured(strategy_versions):
    v1 = strategy_versions.save_generated_code(
        name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED
    )
    service = CodeRegenerationService(strategy_versions, UnconfiguredRouter())
    with pytest.raises(LLMProviderNotConfiguredError):
        await service.regenerate(v1.id, "tighten the stop loss")


async def test_regenerate_uses_spec_override_in_prompt_and_new_version(strategy_versions):
    v1 = strategy_versions.save_generated_code(
        name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED, spec={"name": "sample"}
    )
    llm = FakeRegenerationLLM(REGENERATED_CODE)
    service = CodeRegenerationService(strategy_versions, FakeRouter(llm))

    result = await service.regenerate(
        v1.id, "tighten the stop loss", spec={"name": "sample", "entry_rules": "new rule"}
    )

    assert result.is_valid
    assert "new rule" in llm.last_message.user
    new_version = strategy_versions.get_version(result.new_version_id)
    assert new_version.spec == {"name": "sample", "entry_rules": "new rule"}


async def test_regenerate_without_spec_override_keeps_stored_spec(strategy_versions):
    v1 = strategy_versions.save_generated_code(
        name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED, spec={"name": "sample"}
    )
    llm = FakeRegenerationLLM(REGENERATED_CODE)
    service = CodeRegenerationService(strategy_versions, FakeRouter(llm))

    result = await service.regenerate(v1.id, "tighten the stop loss")

    new_version = strategy_versions.get_version(result.new_version_id)
    assert new_version.spec == {"name": "sample"}


async def test_regenerate_with_new_name_forks_into_new_family(strategy_versions):
    v1 = strategy_versions.save_generated_code(
        name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED
    )
    llm = FakeRegenerationLLM(REGENERATED_CODE)
    service = CodeRegenerationService(strategy_versions, FakeRouter(llm))

    result = await service.regenerate(v1.id, "tighten the stop loss", new_name="sample_fork")

    new_version = strategy_versions.get_version(result.new_version_id)
    assert new_version.name == "sample_fork"
    assert new_version.version == 1
    assert new_version.parent_version_id is None
    # The original family is untouched.
    assert strategy_versions.get_version(v1.id).name == "sample"


async def test_regenerate_new_name_conflict_raises_without_calling_llm(strategy_versions):
    v1 = strategy_versions.save_generated_code(
        name="sample", code=VALID_CODE, source=CodeSource.AI_GENERATED
    )
    strategy_versions.save_generated_code(
        name="other", code=VALID_CODE, source=CodeSource.AI_GENERATED
    )

    class ExplodingLLM:
        async def complete(self, message, *, max_tokens=4096):
            raise AssertionError("should never be called for a name conflict")

    service = CodeRegenerationService(strategy_versions, FakeRouter(ExplodingLLM()))
    with pytest.raises(StrategyNameConflictError):
        await service.regenerate(v1.id, "tighten the stop loss", new_name="other")
