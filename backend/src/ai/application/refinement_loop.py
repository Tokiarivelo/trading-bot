"""10-trade self-refinement loop (§8.2): on every `TenTradesCompleted`, an AI
reviews the last N closed trades for a symbol and, if it finds a specific,
actionable problem, proposes a revised strategy file. The proposal is always
sandbox-validated and backtested against the version it's based on before
any apply decision — `configs/ai.yaml: refinement.mode` decides whether that
decision is a human clicking "activate" (suggest, the default) or the loop
itself calling `activate_version` when the backtest clears a threshold (auto).

Mirrors `ai/application/pdf_to_strategy.py`'s patterns throughout: same
`LLMPort`/`LLMRouter` boundary, same fence-stripped-JSON parsing with no
retries/schema library, same sandbox-validate-then-version pipeline, same
"missing candle history just skips, never fails the whole flow" tolerance.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from src.ai.adapters.report_repository import AnalysisReportRepository, RefinementProposalRepository
from src.ai.application.llm_router import LLMRouter
from src.ai.application.llm_text import extract_python_code, strip_fences
from src.ai.application.pdf_to_strategy import default_backtest_period
from src.ai.application.sandbox_retry import generate_valid_strategy_code
from src.ai.domain.models import (
    AnalysisReport,
    ProposalStatus,
    RefinementConfig,
    RefinementProposal,
    ReportVerdict,
)
from src.ai.prompts.loader import render_prompt
from src.backtest.application.run_backtest import NoHistoryError, run_backtest
from src.backtest.domain.models import BacktestReport
from src.backtest.reports.writer import write_report
from src.journal.adapters.repository import JournalRepository
from src.journal.domain.models import CandleSnapshot, TradeRecord
from src.shared.events.bus import EventBus
from src.shared.events.definitions import RefinementCompleted, TenTradesCompleted
from src.skills.ports.skill_selector import SkillSelectorPort
from src.strategies.application.versioning import StrategyValidationError, StrategyVersionService
from src.strategies.domain.versioning import CodeSource, VersionStatus
from src.strategies.registry import StrategyRegistry
from src.strategies.sandbox import validate_and_load

logger = logging.getLogger(__name__)


class InvalidProposalStateError(Exception):
    pass


class RefinementLoopService:
    def __init__(
        self,
        report_repository: AnalysisReportRepository,
        proposal_repository: RefinementProposalRepository,
        journal_repository: JournalRepository,
        strategy_versions: StrategyVersionService,
        strategy_registry: StrategyRegistry,
        skill_selector: SkillSelectorPort,
        llm_router: LLMRouter,
        refinement_config: RefinementConfig,
        timezone: str = "UTC",
        backtest_period: str | None = None,
        backtest_database_url: str | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._reports = report_repository
        self._proposals = proposal_repository
        self._journal = journal_repository
        self._strategy_versions = strategy_versions
        self._strategy_registry = strategy_registry
        self._skill_selector = skill_selector
        self._llm_router = llm_router
        self._config = refinement_config
        self._event_bus = event_bus
        self._tz = ZoneInfo(timezone)
        self._backtest_period = backtest_period or default_backtest_period()
        # None means "use run_backtest's own default (the live app's DB)" —
        # only set in tests, so backtests read an isolated candle history.
        self._backtest_database_url = backtest_database_url

    async def on_ten_trades_completed(self, event: TenTradesCompleted) -> None:
        try:
            await self._handle(event)
        except Exception:
            # Never let a malformed LLM response or any other failure break
            # the event bus — this runs as a subscriber alongside the
            # journal/engine handlers `EventBus.publish` already isolates,
            # but a report already saved before the failure should stay
            # visible rather than the whole review vanishing silently.
            logger.exception(
                "refinement loop failed for symbol=%s trade_ids=%s", event.symbol, event.trade_ids
            )

    async def _handle(self, event: TenTradesCompleted) -> None:
        decision = self._skill_selector.select(event.symbol)
        if not decision.strategy_name:
            logger.info("refinement loop: no strategy configured for %s, skipping", event.symbol)
            return

        # Deliberately NOT resolved from TradeRecord.strategy_version — that
        # string's embedded version number is whatever the generating LLM
        # hardcoded into StrategySpec at codegen time and can drift from the
        # DB. The DB's ACTIVE row is the source of truth for "what's trading
        # this symbol right now." A strategy family with no versioned row at
        # all (e.g. the hand-registered baseline) has nothing to review —
        # only versioned (AI-generated/refined) strategies enter this loop.
        active_version = await self._get_active_version(decision.strategy_name)
        if active_version is None:
            logger.info(
                "refinement loop: no active versioned strategy for %s (%s), skipping",
                event.symbol,
                decision.strategy_name,
            )
            return

        strategy_name = decision.strategy_name
        trades = await self._get_trades(event.trade_ids)
        code = await asyncio.to_thread(self._strategy_versions.get_code, active_version)
        spec_json = json.dumps(active_version.spec or {}, indent=2)
        trades_payload = [_serialize_trade(t) for t in trades]

        review_message = render_prompt(
            "review_ten_trades.md",
            strategy_name=strategy_name,
            symbol=event.symbol,
            spec_json=spec_json,
            code=code,
            trades=trades_payload,
            trades_json=json.dumps(trades_payload, indent=2),
        )
        review_llm = self._llm_router.for_task("ten_trade_review")
        raw_review = await review_llm.complete(review_message)
        review_data = _parse_json(raw_review)

        report = AnalysisReport(
            id=str(uuid.uuid4()),
            symbol=event.symbol,
            strategy_name=strategy_name,
            base_version_id=active_version.id,
            trade_ids=event.trade_ids,
            created_at=datetime.now(UTC),
            win_rate=float(review_data.get("win_rate", 0.0)),
            avg_r=float(review_data.get("avg_r", 0.0)),
            common_failure_pattern=str(review_data.get("common_failure_pattern", "")),
            session_or_news_correlation=str(review_data.get("session_or_news_correlation", "")),
            verdict=ReportVerdict(review_data.get("verdict", "no_action")),
            raw_llm_response=raw_review,
        )
        await asyncio.to_thread(self._reports.save, report)
        logger.info(
            "analysis report created: id=%s symbol=%s verdict=%s",
            report.id,
            event.symbol,
            report.verdict,
        )

        if report.verdict != ReportVerdict.REFINEMENT_PROPOSED:
            await self._publish_completed(event.symbol, report.verdict.value, None)
            return

        proposal = await self._propose_refinement(
            report=report,
            strategy_name=strategy_name,
            symbol=event.symbol,
            active_version_id=active_version.id,
            spec=active_version.spec,
            spec_json=spec_json,
            code=code,
            trades_payload=trades_payload,
            refinement_summary=str(review_data.get("refinement_summary", "")),
        )
        await asyncio.to_thread(self._proposals.save, proposal)
        await asyncio.to_thread(self._reports.save, replace(report, proposal_id=proposal.id))
        logger.info(
            "refinement proposal created: id=%s report=%s status=%s applied_mode=%s",
            proposal.id,
            report.id,
            proposal.status,
            proposal.applied_mode,
        )
        await self._publish_completed(event.symbol, report.verdict.value, proposal.id)

    async def _publish_completed(self, symbol: str, verdict: str, proposal_id: str | None) -> None:
        if self._event_bus is None:
            return
        await self._event_bus.publish(
            RefinementCompleted(symbol=symbol, verdict=verdict, proposal_id=proposal_id)
        )

    async def _propose_refinement(
        self,
        *,
        report: AnalysisReport,
        strategy_name: str,
        symbol: str,
        active_version_id: str,
        spec: dict[str, object] | None,
        spec_json: str,
        code: str,
        trades_payload: list[dict],
        refinement_summary: str,
    ) -> RefinementProposal:
        refine_message = render_prompt(
            "refine_strategy_code.md",
            strategy_name=strategy_name,
            symbol=symbol,
            spec_json=spec_json,
            code=code,
            trades=trades_payload,
            common_failure_pattern=report.common_failure_pattern,
            session_or_news_correlation=report.session_or_news_correlation,
            refinement_summary=refinement_summary,
        )
        refine_llm = self._llm_router.for_task("code_refinement")
        raw_refine = await refine_llm.complete(refine_message, max_tokens=8192)
        rationale, first_pass_code = _parse_rationale_and_code(raw_refine)

        proposal_id = str(uuid.uuid4())
        # The first draft sometimes trips the sandbox on something the LLM
        # can plausibly fix itself (an accidentally forbidden import, a
        # construct the static scan flags) — retry against the same errors
        # before rejecting the proposal outright.
        proposed_code, retry_errors = await generate_valid_strategy_code(
            refine_llm, strategy_name, first_pass_code
        )
        if retry_errors:
            logger.warning(
                "refined strategy code failed sandbox validation after retries: "
                "report=%s errors=%s",
                report.id,
                retry_errors,
            )
            return RefinementProposal(
                id=proposal_id,
                report_id=report.id,
                strategy_name=strategy_name,
                base_version_id=active_version_id,
                rationale=rationale,
                proposed_code=proposed_code,
                status=ProposalStatus.REJECTED,
                created_at=datetime.now(UTC),
                sandbox_errors=retry_errors,
            )

        try:
            new_version = await asyncio.to_thread(
                self._strategy_versions.save_generated_code,
                name=strategy_name,
                code=proposed_code,
                source=CodeSource.AI_REFINED,
                spec=spec,
            )
        except StrategyValidationError as exc:
            logger.warning(
                "refined strategy code failed sandbox validation: report=%s errors=%s",
                report.id,
                exc.errors,
            )
            return RefinementProposal(
                id=proposal_id,
                report_id=report.id,
                strategy_name=strategy_name,
                base_version_id=active_version_id,
                rationale=rationale,
                proposed_code=proposed_code,
                status=ProposalStatus.REJECTED,
                created_at=datetime.now(UTC),
                sandbox_errors=exc.errors,
            )

        baseline_bt = await self._run_backtest(strategy_name, symbol, self._strategy_registry)
        candidate_instance, _errors = validate_and_load(proposed_code)
        candidate_registry = StrategyRegistry()
        candidate_registry.register(strategy_name, candidate_instance)
        candidate_bt = await self._run_backtest(strategy_name, symbol, candidate_registry)

        baseline_report_id = await self._write_report(baseline_bt) if baseline_bt else None
        candidate_report_id = await self._write_report(candidate_bt) if candidate_bt else None
        improvement_pct = _improvement_pct(baseline_bt, candidate_bt)

        status = (
            ProposalStatus.BACKTESTED
            if baseline_bt is not None and candidate_bt is not None
            else ProposalStatus.PENDING
        )
        applied_mode: str | None = None

        if status == ProposalStatus.BACKTESTED and self._config.mode == "auto":
            refinements_today = await self._auto_refinements_today(strategy_name)
            if refinements_today >= self._config.max_auto_refinements_per_day:
                logger.info(
                    "refinement loop: auto-apply rate limit hit for %s, leaving for suggest-mode",
                    strategy_name,
                )
            elif (
                improvement_pct is not None
                and improvement_pct >= self._config.auto_apply_min_improvement_pct
            ):
                await asyncio.to_thread(self._strategy_versions.activate_version, new_version.id)
                status = ProposalStatus.APPLIED
                applied_mode = "auto"
            else:
                status = ProposalStatus.REJECTED
                applied_mode = "auto"

        return RefinementProposal(
            id=proposal_id,
            report_id=report.id,
            strategy_name=strategy_name,
            base_version_id=active_version_id,
            rationale=rationale,
            proposed_code=proposed_code,
            status=status,
            created_at=datetime.now(UTC),
            new_version_id=new_version.id,
            baseline_backtest_report_id=baseline_report_id,
            candidate_backtest_report_id=candidate_report_id,
            improvement_pct=improvement_pct,
            applied_mode=applied_mode,
        )

    async def list_reports(self, symbol: str | None = None) -> list[AnalysisReport]:
        return await asyncio.to_thread(self._reports.list_all, symbol)

    async def get_report(self, report_id: str) -> AnalysisReport | None:
        return await asyncio.to_thread(self._reports.get, report_id)

    async def get_proposal(self, proposal_id: str) -> RefinementProposal | None:
        return await asyncio.to_thread(self._proposals.get, proposal_id)

    async def reject_proposal(self, proposal_id: str) -> RefinementProposal:
        proposal = await self.get_proposal(proposal_id)
        if proposal is None:
            raise ValueError(f"no refinement proposal with id {proposal_id!r}")
        if proposal.status in (ProposalStatus.APPLIED, ProposalStatus.REJECTED):
            raise InvalidProposalStateError(
                f"proposal {proposal_id} is {proposal.status}, cannot reject"
            )
        updated = replace(proposal, status=ProposalStatus.REJECTED)
        await asyncio.to_thread(self._proposals.save, updated)
        return updated

    async def _get_active_version(self, name: str):
        versions = await asyncio.to_thread(self._strategy_versions.list_versions, name)
        return next((v for v in versions if v.status == VersionStatus.ACTIVE), None)

    async def _get_trades(self, trade_ids: tuple[str, ...]) -> list[TradeRecord]:
        def _fetch() -> list[TradeRecord]:
            trades = [self._journal.get(tid) for tid in trade_ids]
            return [t for t in trades if t is not None]

        return await asyncio.to_thread(_fetch)

    async def _run_backtest(
        self, strategy_name: str, symbol: str, registry: StrategyRegistry
    ) -> BacktestReport | None:
        kwargs: dict[str, object] = {}
        if self._backtest_database_url is not None:
            kwargs["database_url"] = self._backtest_database_url
        try:
            return await run_backtest(
                strategy_name, symbol, self._backtest_period, strategy_source=registry, **kwargs
            )
        except NoHistoryError:
            logger.warning(
                "refinement backtest skipped, no candle history for %s %s yet",
                symbol,
                self._backtest_period,
            )
            return None

    async def _write_report(self, report: BacktestReport) -> str:
        path = await asyncio.to_thread(write_report, report)
        return path.stem

    async def _auto_refinements_today(self, strategy_name: str) -> int:
        # Counts actually-applied auto-refinements (via the proposal table,
        # not strategy_versions) — the candidate version for *this* proposal
        # already exists as VALIDATED/AI_REFINED by the time this runs, so
        # counting versions instead of applied proposals would make every
        # auto-refinement rate-limited by its own not-yet-applied candidate.
        proposals = await asyncio.to_thread(self._proposals.list_by_strategy, strategy_name)
        today = datetime.now(self._tz).date()
        return sum(
            1
            for p in proposals
            if p.applied_mode == "auto"
            and p.status == ProposalStatus.APPLIED
            and p.created_at.astimezone(self._tz).date() == today
        )


def _improvement_pct(
    baseline: BacktestReport | None, candidate: BacktestReport | None
) -> float | None:
    if baseline is None or candidate is None or baseline.avg_r == 0:
        return None
    return (candidate.avg_r - baseline.avg_r) / abs(baseline.avg_r) * 100


def _serialize_trade(trade: TradeRecord) -> dict:
    return {
        "id": trade.id,
        "side": trade.side,
        "volume": trade.volume,
        "open_price": trade.open_price,
        "open_time": trade.open_time.isoformat(),
        "close_price": trade.close_price,
        "close_time": trade.close_time.isoformat() if trade.close_time else None,
        "sl": trade.sl,
        "tp": trade.tp,
        "profit": trade.profit,
        "spread_points_at_entry": trade.spread_points_at_entry,
        "m5_entry_snapshot": [_serialize_snapshot(c) for c in trade.m5_entry_snapshot],
        "h1_entry_snapshot": [_serialize_snapshot(c) for c in trade.h1_entry_snapshot],
        "m5_exit_snapshot": [_serialize_snapshot(c) for c in trade.m5_exit_snapshot],
        "h1_exit_snapshot": [_serialize_snapshot(c) for c in trade.h1_exit_snapshot],
    }


def _serialize_snapshot(candle: CandleSnapshot) -> dict:
    return {
        "time": candle.time.isoformat(),
        "open": candle.open,
        "high": candle.high,
        "low": candle.low,
        "close": candle.close,
        "tick_volume": candle.tick_volume,
    }


def _parse_json(raw: str) -> dict:
    return json.loads(strip_fences(raw))


def _parse_rationale_and_code(raw: str) -> tuple[str, str]:
    text = raw.strip("\n")
    if text.startswith("RATIONALE:"):
        head, sep, rest = text.partition("\n\n")
        rationale = head.removeprefix("RATIONALE:").strip()
        code = rest if sep else ""
    else:
        rationale, code = "", text
    return rationale, extract_python_code(code.strip())
