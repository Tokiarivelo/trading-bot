"""User-triggered AI code regeneration for an existing strategy version
(§6.5 code editor).

Distinct from `pdf_to_strategy.py` (spec -> first code) and
`refinement_loop.py` (automated, trade-review-driven proposals): this is a
human typing free-form instructions ("tighten the stop loss", "only trade
during the London session") against a version they're already looking at,
on demand. Always produces a new 'validated' `StrategyVersion` parented on
the one being regenerated — never activates anything, and never runs a
backtest (the trader can request one separately once they like the result).

Deliberately reuses the `code_generation` LLM task (not a separate
`code_regeneration` task) — the Settings page has exactly one "Strategy code
generation" provider row, and whatever it's set to is what both the initial
PDF-to-code pipeline and this on-demand rewrite use. A distinct task here
would need its own settings-page override the trader has to remember to set
a second time, silently falling back to `configs/ai.yaml`'s default (and its
own API key requirement) otherwise.
"""

from __future__ import annotations

import asyncio
import json
import logging

from src.ai.application.llm_router import LLMRouter
from src.ai.application.llm_text import extract_python_code
from src.ai.application.sandbox_retry import generate_valid_strategy_code
from src.ai.domain.models import RegeneratedCode
from src.ai.prompts.loader import render_prompt
from src.strategies.application.versioning import (
    StrategyNameConflictError,
    StrategyValidationError,
    StrategyVersionService,
)
from src.strategies.domain.versioning import CodeSource

logger = logging.getLogger(__name__)


class CodeRegenerationService:
    def __init__(
        self,
        strategy_versions: StrategyVersionService,
        llm_router: LLMRouter,
    ) -> None:
        self._strategy_versions = strategy_versions
        self._llm_router = llm_router

    async def regenerate(
        self,
        version_id: str,
        instructions: str,
        *,
        spec: dict[str, object] | None = None,
        new_name: str | None = None,
    ) -> RegeneratedCode:
        """`spec`, if given, overrides `version_id`'s stored spec snapshot —
        both in the prompt sent to the LLM and on the resulting version —
        letting the trader tweak the spec (symbols, entry/exit rules, ...)
        before regenerating instead of being stuck with what it was
        extracted/saved as. Omit to use the version's spec unchanged. `new_name`
        picks the save destination exactly like `StrategyVersionService.edit_code`:
        omitted increments within this version's family, a different name forks
        into a brand-new one. Raises `StrategyNameConflictError` if `new_name`
        is already a different, existing family."""
        version = await asyncio.to_thread(self._strategy_versions.get_version, version_id)
        if version is None:
            raise ValueError(f"no strategy version with id {version_id!r}")
        if new_name is not None and new_name != version.name:
            # Fail fast on a name collision before spending an LLM call on
            # code that `edit_code` would reject anyway once it gets there.
            existing = await asyncio.to_thread(self._strategy_versions.list_versions, new_name)
            if existing:
                raise StrategyNameConflictError(new_name)

        effective_spec = spec if spec is not None else version.spec
        code = await asyncio.to_thread(self._strategy_versions.get_code, version)
        message = render_prompt(
            "regenerate_strategy_code.md",
            strategy_name=version.name,
            spec_json=json.dumps(effective_spec or {}, indent=2),
            code=code,
            instructions=instructions,
        )
        llm = self._llm_router.for_task("code_generation")
        raw = await llm.complete(message, max_tokens=8192)
        first_pass_code = extract_python_code(raw)
        # The first draft sometimes trips the sandbox on something the LLM
        # can plausibly fix itself (an accidentally forbidden import, a
        # construct the static scan flags) — retry against the same errors
        # before handing the trader a rejection to fix by hand.
        new_code, retry_errors = await generate_valid_strategy_code(
            llm, version.name, first_pass_code
        )
        if retry_errors:
            logger.warning(
                "AI-regenerated strategy code failed sandbox validation after retries: "
                "version=%s errors=%s",
                version_id,
                retry_errors,
            )
            return RegeneratedCode(
                version_id=version_id,
                instructions=instructions,
                code=new_code,
                sandbox_errors=retry_errors,
            )

        try:
            new_version = await asyncio.to_thread(
                self._strategy_versions.edit_code,
                version_id,
                new_code,
                source=CodeSource.AI_REFINED,
                new_name=new_name,
                spec=effective_spec,
            )
        except StrategyValidationError as exc:
            logger.warning(
                "AI-regenerated strategy code failed sandbox validation: version=%s errors=%s",
                version_id,
                exc.errors,
            )
            return RegeneratedCode(
                version_id=version_id,
                instructions=instructions,
                code=new_code,
                sandbox_errors=exc.errors,
            )

        logger.info(
            "strategy code regenerated by AI: base=%s new_version=%s", version_id, new_version.id
        )
        return RegeneratedCode(
            version_id=version_id,
            instructions=instructions,
            code=new_code,
            new_version_id=new_version.id,
        )
