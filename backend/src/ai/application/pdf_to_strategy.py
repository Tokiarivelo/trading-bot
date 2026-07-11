"""PDF -> StrategySpec -> generated code pipeline (§8.1).

Never skips human review: `create_draft_from_pdf` only ever produces a
`StrategyDraft` for the user to look at and edit; `generate_code` refuses
anything that isn't `APPROVED`. Code generation always runs the sandbox
before anything is written to `strategies/generated/`, and attempts an
auto-backtest afterwards — a missing candle history just skips the backtest
(logged), it never fails the whole pipeline.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import replace
from datetime import UTC, datetime

import fitz  # PyMuPDF

from src.ai.adapters.repository import DraftRepository
from src.ai.application.llm_router import LLMRouter
from src.ai.domain.models import DraftStatus, ExtractedStrategySpec, GeneratedCode, StrategyDraft
from src.ai.prompts.loader import render_prompt
from src.backtest.application.run_backtest import NoHistoryError, run_backtest
from src.backtest.reports.writer import write_report
from src.strategies.application.versioning import StrategyValidationError, StrategyVersionService
from src.strategies.domain.versioning import CodeSource
from src.strategies.registry import StrategyRegistry
from src.strategies.sandbox import validate_and_load

logger = logging.getLogger(__name__)

DEFAULT_BACKTEST_MONTHS = 6


def default_backtest_period(
    months: int = DEFAULT_BACKTEST_MONTHS, *, now: datetime | None = None
) -> str:
    """The trailing `months`-month window ending this month, in the
    `run_backtest` CLI's `YYYY-MM:YYYY-MM` format (§12 Phase 6: "automatic
    backtest on 6-12 months of data")."""
    now = now or datetime.now(UTC)
    end_year, end_month = now.year, now.month
    zero_based_start = end_year * 12 + (end_month - 1) - (months - 1)
    start_year, start_month = divmod(zero_based_start, 12)
    return f"{start_year:04d}-{start_month + 1:02d}:{end_year:04d}-{end_month:02d}"


class InvalidDraftStateError(Exception):
    pass


def extract_pdf_text(pdf_bytes: bytes) -> str:
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        return "\n\n".join(page.get_text() for page in doc)


class PdfToStrategyService:
    def __init__(
        self,
        draft_repository: DraftRepository,
        strategy_versions: StrategyVersionService,
        llm_router: LLMRouter,
        backtest_period: str | None = None,
        backtest_database_url: str | None = None,
    ) -> None:
        self._drafts = draft_repository
        self._strategy_versions = strategy_versions
        self._llm_router = llm_router
        self._backtest_period = backtest_period or default_backtest_period()
        # None means "use run_backtest's own default (the live app's DB)" —
        # only set in tests, so the auto-backtest reads an isolated candle
        # history instead of the real `data/trading.db`.
        self._backtest_database_url = backtest_database_url

    async def create_draft_from_pdf(self, filename: str, pdf_bytes: bytes) -> StrategyDraft:
        text = await asyncio.to_thread(extract_pdf_text, pdf_bytes)
        message = render_prompt("extract_method_from_pdf.md", filename=filename, pdf_text=text)
        llm = self._llm_router.for_task("pdf_extraction")
        raw = await llm.complete(message)
        spec = ExtractedStrategySpec.from_dict(_parse_json(raw))
        draft = StrategyDraft(
            id=str(uuid.uuid4()),
            source_filename=filename,
            created_at=datetime.now(UTC),
            extracted_spec=spec,
        )
        await asyncio.to_thread(self._drafts.save, draft)
        logger.info("strategy draft created from PDF: id=%s filename=%s", draft.id, filename)
        return draft

    async def get_draft(self, draft_id: str) -> StrategyDraft | None:
        return await asyncio.to_thread(self._drafts.get, draft_id)

    async def list_drafts(self) -> list[StrategyDraft]:
        return await asyncio.to_thread(self._drafts.list_all)

    async def update_draft_spec(
        self, draft_id: str, edited_spec: ExtractedStrategySpec
    ) -> StrategyDraft:
        draft = await self._require_draft(draft_id)
        if draft.status not in (DraftStatus.PENDING_REVIEW, DraftStatus.APPROVED):
            raise InvalidDraftStateError(f"draft {draft_id} is {draft.status}, cannot edit")
        updated = replace(draft, edited_spec=edited_spec, status=DraftStatus.PENDING_REVIEW)
        await asyncio.to_thread(self._drafts.save, updated)
        return updated

    async def approve_draft(self, draft_id: str) -> StrategyDraft:
        draft = await self._require_draft(draft_id)
        if draft.status != DraftStatus.PENDING_REVIEW:
            raise InvalidDraftStateError(f"draft {draft_id} is {draft.status}, cannot approve")
        updated = replace(draft, status=DraftStatus.APPROVED)
        await asyncio.to_thread(self._drafts.save, updated)
        logger.info("strategy draft approved: id=%s", draft_id)
        return updated

    async def reject_draft(self, draft_id: str) -> StrategyDraft:
        draft = await self._require_draft(draft_id)
        updated = replace(draft, status=DraftStatus.REJECTED)
        await asyncio.to_thread(self._drafts.save, updated)
        logger.info("strategy draft rejected: id=%s", draft_id)
        return updated

    async def generate_code(self, draft_id: str) -> GeneratedCode:
        draft = await self._require_draft(draft_id)
        if draft.status != DraftStatus.APPROVED:
            raise InvalidDraftStateError(
                f"draft {draft_id} is {draft.status}, must be approved before code generation"
            )
        spec = draft.effective_spec
        message = render_prompt(
            "generate_strategy_code.md",
            spec_json=json.dumps(spec.to_dict(), indent=2),
            class_name=_class_name(spec.name),
            file_name=f"{spec.name}_vN.py",
        )
        llm = self._llm_router.for_task("code_generation")
        raw = await llm.complete(message, max_tokens=8192)
        code = _strip_fences(raw)

        try:
            version = await asyncio.to_thread(
                self._strategy_versions.save_generated_code,
                name=spec.name,
                code=code,
                source=CodeSource.AI_GENERATED,
                spec=spec.to_dict(),
                draft_id=draft.id,
            )
        except StrategyValidationError as exc:
            logger.warning(
                "generated strategy code failed sandbox validation: draft=%s errors=%s",
                draft_id,
                exc.errors,
            )
            return GeneratedCode(draft_id=draft_id, code=code, sandbox_errors=exc.errors)

        backtest_report_id = await asyncio.to_thread(self._auto_backtest, spec, code)

        updated = replace(draft, status=DraftStatus.CODE_GENERATED)
        await asyncio.to_thread(self._drafts.save, updated)
        logger.info(
            "strategy code generated: draft=%s version=%s backtest_report=%s",
            draft_id,
            version.id,
            backtest_report_id,
        )

        return GeneratedCode(
            draft_id=draft_id,
            code=code,
            version_id=version.id,
            backtest_report_id=backtest_report_id,
        )

    def _auto_backtest(self, spec: ExtractedStrategySpec, code: str) -> str | None:
        if not spec.symbols:
            return None
        instance, errors = validate_and_load(code)
        if instance is None:
            logger.error("auto-backtest skipped, code no longer validates: %s", errors)
            return None
        registry = StrategyRegistry()
        registry.register(instance)
        symbol = spec.symbols[0]
        kwargs: dict[str, object] = {}
        if self._backtest_database_url is not None:
            kwargs["database_url"] = self._backtest_database_url
        try:
            report = asyncio.run(
                run_backtest(
                    spec.name, symbol, self._backtest_period, strategy_source=registry, **kwargs
                )
            )
        except NoHistoryError:
            logger.warning(
                "auto-backtest skipped, no candle history for %s %s yet — run the historical "
                "backfill job (POST /market-data/backfill) to enable it",
                symbol,
                self._backtest_period,
            )
            return None
        path = write_report(report)
        return path.stem

    async def _require_draft(self, draft_id: str) -> StrategyDraft:
        draft = await self.get_draft(draft_id)
        if draft is None:
            raise ValueError(f"no draft with id {draft_id!r}")
        return draft


def _class_name(slug: str) -> str:
    return "".join(word.capitalize() for word in slug.split("_")) or "GeneratedStrategy"


def _parse_json(raw: str) -> dict:
    return json.loads(_strip_fences(raw))


def _strip_fences(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()
