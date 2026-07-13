"""Sandbox-rejection retry loop shared by every AI code-generation path
(§6.5, §8.1, §8.2): `pdf_to_strategy.generate_code`, `code_regeneration.
regenerate`, and `refinement_loop._propose_refinement` all render a prompt,
call an LLM, and hand the result to `strategies.sandbox.validate_and_load`
before anything is persisted. A rejection used to be terminal — the trader
(or the refinement loop) got back the first draft's sandbox errors and had
to retry by hand. This feeds those errors back to the same LLM and asks for
a fix, up to `MAX_ATTEMPTS` times, so a rejection the LLM can plausibly
self-correct (an accidentally forbidden import, a construct the static scan
flags) doesn't dead-end the whole generation.
"""

from __future__ import annotations

import asyncio
import logging

from src.ai.application.llm_text import extract_python_code
from src.ai.ports.llm import LLMPort
from src.ai.prompts.loader import render_prompt
from src.strategies.sandbox import validate_and_load

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3


async def generate_valid_strategy_code(
    llm: LLMPort,
    strategy_name: str,
    initial_code: str,
    *,
    max_tokens: int = 8192,
    max_attempts: int = MAX_ATTEMPTS,
) -> tuple[str, tuple[str, ...]]:
    """Returns `(code, errors)` — `errors` empty means `code` passed the
    sandbox. Starts from `initial_code` (already extracted from the caller's
    first LLM completion) and, on rejection, re-prompts `llm` with the
    sandbox's own error messages, up to `max_attempts` attempts total. Never
    raises: exhausting every attempt just returns the last attempt's code and
    errors, the same shape as a first-try rejection, so a caller's existing
    "sandbox_errors non-empty -> report failure" handling needs no change.
    """
    code = initial_code
    errors: tuple[str, ...] = ()
    for attempt in range(1, max_attempts + 1):
        # `validate_and_load` runs a worker-thread smoke test with a
        # wall-clock join timeout — calling it inline would block the event
        # loop for the timeout's duration on every rejected attempt.
        _, errors = await asyncio.to_thread(validate_and_load, code)
        if not errors:
            return code, ()
        logger.warning(
            "strategy %s: sandbox rejected attempt %d/%d: %s",
            strategy_name,
            attempt,
            max_attempts,
            errors,
        )
        if attempt == max_attempts:
            break
        message = render_prompt(
            "fix_sandbox_errors.md",
            strategy_name=strategy_name,
            errors="\n".join(f"- {e}" for e in errors),
            code=code,
        )
        raw = await llm.complete(message, max_tokens=max_tokens)
        code = extract_python_code(raw)
    return code, errors
