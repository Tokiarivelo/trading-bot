"""Backtest report endpoints + on-demand backtest runner.

Read-only report endpoints (list / get) serve the JSON files written by the
backtest CLI.  The two new endpoints added here —
    GET  /backtest/bots           – enumerate every available (bot, symbol) pair
    POST /backtest/run            – launch a backtest job in the background
    GET  /backtest/run/{job_id}   – poll job status / retrieve the new report
expose the same logic as `python -m src.backtest.cli` through the UI so the
trader never needs to open a terminal.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi import Path as PathParam
from pydantic import BaseModel, Field

from src.backtest.api.schemas import (
    BacktestReportDetailOut,
    BacktestReportListOut,
    BacktestReportSummaryOut,
)
from src.backtest.application.period import parse_period
from src.backtest.application.run_backtest import (
    DEFAULT_STARTING_BALANCE,
    HISTORY_BUFFER,
    NoHistoryError,
    NoSymbolSpecError,
    run_backtest,
)
from src.backtest.reports.writer import REPORTS_DIR, write_report
from src.market_data.application.history import CandleHistoryService
from src.market_data.domain.models import MarketDataUnavailable, Timeframe
from src.shared.config.settings import Settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/backtest", tags=["backtest"])

_VALID_ID = re.compile(r"^[A-Za-z0-9 _-]+$")

# ── In-memory job store (per-process; fine for a single-user trading bot) ────

class _JobStatus:
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"

_jobs: dict[str, dict[str, Any]] = {}

# ── Bot / symbol discovery ────────────────────────────────────────────────────

_STRATEGIES_GENERATED_DIR = (
    Path(__file__).resolve().parent.parent.parent / "strategies" / "generated"
)


def _discover_bots() -> list[dict[str, Any]]:
    """One entry per strategy family the backtester can run: `breakout_v1`,
    `trend_structure_v1`, `trend_structure_v2`, and `mean_reversion_v1` (the
    hardcoded baselines) plus every non-archived `StrategyVersion` family in
    the DB, deduplicated active-first — the same version each family would
    actually resolve to at `_build_full_registry` time.

    `id` is a stable identifier — pass it back to `POST /backtest/run`; it's
    the literal string `"breakout_v1"`/`"trend_structure_v1"`/
    `"trend_structure_v2"`/`"mean_reversion_v1"` for the baselines, or a
    `StrategyVersion.id` (a UUID) for everything else.
    `name` is the family's display label only: it's human-typed, not
    guaranteed unique, can be renamed (`rename_family`) or collide with
    another family's internal `spec.name` (see `strategies/registry.py`'s
    module docstring) — never used to look anything up here.
    """
    from src.shared.config.settings import Settings
    from src.shared.db.base import make_session_factory
    from src.strategies.adapters.repository import StrategyVersionRepository
    from src.strategies.domain.versioning import VersionStatus
    from src.strategies.generated.breakout_v1 import BreakoutV1
    from src.strategies.generated.mean_reversion_v1 import MeanReversionV1
    from src.strategies.generated.trend_structure_v1 import TrendStructureV1
    from src.strategies.generated.trend_structure_v2 import TrendStructureV2
    from src.strategies.sandbox import validate_and_load

    settings = Settings()
    bots: list[dict[str, Any]] = [
        {"id": "breakout_v1", "name": "breakout_v1", "symbols": list(BreakoutV1().spec.symbols)},
        {
            "id": "trend_structure_v1",
            "name": "trend_structure_v1",
            "symbols": list(TrendStructureV1().spec.symbols),
        },
        {
            "id": "trend_structure_v2",
            "name": "trend_structure_v2",
            "symbols": list(TrendStructureV2().spec.symbols),
        },
        {
            "id": "mean_reversion_v1",
            "name": "mean_reversion_v1",
            "symbols": list(MeanReversionV1().spec.symbols),
        },
    ]

    try:
        repo = StrategyVersionRepository(make_session_factory(settings.database_url))
        non_archived = [v for v in repo.list_all() if v.status != VersionStatus.ARCHIVED]
        # Active first, so a family with both an active and a validated
        # version is represented by the one that would actually run.
        non_archived.sort(key=lambda v: 0 if v.status == VersionStatus.ACTIVE else 1)

        seen_families: set[str] = set()
        for version in non_archived:
            if version.name in seen_families:
                continue
            symbols: list[str] = list((version.spec or {}).get("symbols", []))
            if not symbols:
                # No spec snapshot (e.g. a hand-written version) — fall back
                # to loading the generated file to read spec.symbols.
                try:
                    code_path = _STRATEGIES_GENERATED_DIR / Path(version.file_path).name
                    if code_path.exists():
                        instance, _errors = validate_and_load(code_path.read_text())
                        if instance is not None:
                            symbols = list(instance.spec.symbols)
                except Exception:  # noqa: BLE001
                    pass
            if symbols:
                bots.append({"id": version.id, "name": version.name, "symbols": symbols})
                seen_families.add(version.name)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not load strategy versions for bot discovery: %s", exc)

    bots.sort(key=lambda b: b["name"])
    return bots


def _resolve_strategy_name(strategy_id: str, database_url: str) -> str:
    """`strategy_id` is a bot `id` from `GET /backtest/bots` — resolves it to
    the family name `run_backtest`/`StrategyRegistry` actually key strategies
    by. Raises `ValueError` if `strategy_id` doesn't match anything, which
    `_run_job` already treats as a normal job failure."""
    if strategy_id in (
        "breakout_v1",
        "trend_structure_v1",
        "trend_structure_v2",
        "mean_reversion_v1",
    ):
        return strategy_id

    from src.shared.db.base import make_session_factory
    from src.strategies.adapters.repository import StrategyVersionRepository

    repo = StrategyVersionRepository(make_session_factory(database_url))
    version = repo.get(strategy_id)
    if version is None:
        raise ValueError(f"unknown strategy id: {strategy_id!r}")
    return version.name


# ── Background job runner ─────────────────────────────────────────────────────

async def _run_job(
    job_id: str,
    strategy_id: str,
    symbol: str,
    period: str,
    candle_history: CandleHistoryService,
    starting_balance: float = DEFAULT_STARTING_BALANCE,
    min_lot_fallback_enabled: bool | None = None,
    max_risk_per_trade_pct: float | None = None,
    min_rr: float | None = None,
) -> None:
    _jobs[job_id]["status"] = _JobStatus.RUNNING
    try:
        settings = Settings()
        strategy_name = _resolve_strategy_name(strategy_id, settings.database_url)
        # `strategy_id` may name a validated-but-not-active version (e.g. a
        # draft just saved from the inline backtest editor) — pass it through
        # so the registry loads THAT exact version rather than silently
        # falling back to whatever's currently active for the family.
        preferred_version_id = None if strategy_id == "breakout_v1" else strategy_id
        registry = _build_full_registry(settings.database_url, preferred_version_id)
        try:
            report = await run_backtest(
                strategy_name,
                symbol,
                period,
                database_url=settings.database_url,
                strategy_source=registry,
                starting_balance=starting_balance,
                min_lot_fallback_enabled=min_lot_fallback_enabled,
                max_risk_per_trade_pct=max_risk_per_trade_pct,
                min_rr=min_rr,
            )
        except NoHistoryError:
            # The local DB is missing (part of) the requested range — pull it
            # from the gateway and retry exactly once. A second NoHistoryError
            # means the broker's own history doesn't reach that far back, so
            # it's reported to the user rather than retried again.
            logger.info(
                "backtest job %s: no history for %s %s — auto-backfilling", job_id, symbol, period
            )
            await _auto_backfill(candle_history, symbol, period)
            report = await run_backtest(
                strategy_name,
                symbol,
                period,
                database_url=settings.database_url,
                strategy_source=registry,
                starting_balance=starting_balance,
                min_lot_fallback_enabled=min_lot_fallback_enabled,
                max_risk_per_trade_pct=max_risk_per_trade_pct,
                min_rr=min_rr,
            )
        path = write_report(report)
        _jobs[job_id]["status"] = _JobStatus.DONE
        _jobs[job_id]["report_id"] = path.stem
    except MarketDataUnavailable as exc:
        _jobs[job_id]["status"] = _JobStatus.ERROR
        _jobs[job_id]["error"] = f"gateway unreachable, could not auto-backfill history: {exc}"
    except (ValueError, NoHistoryError, NoSymbolSpecError) as exc:
        _jobs[job_id]["status"] = _JobStatus.ERROR
        _jobs[job_id]["error"] = str(exc)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Backtest job %s failed", job_id)
        _jobs[job_id]["status"] = _JobStatus.ERROR
        _jobs[job_id]["error"] = repr(exc)


async def _auto_backfill(candle_history: CandleHistoryService, symbol: str, period: str) -> None:
    """Pulls every timeframe's candle history for `symbol` back to `period`'s
    start (minus `run_backtest`'s own warmup buffer, so indicators have real
    history on the first replayed bar too) from the live gateway. Also
    refreshes the symbol's broker facts, so a `NoSymbolSpecError` on a
    never-backfilled symbol is resolved by the same retry.

    A single timeframe's `MarketDataUnavailable` (e.g. the broker's terminal
    rejecting `copy_rates_from_pos` for one odd timeframe on a synthetic
    index, seen in practice for H4) does NOT abort the whole backfill — only
    M5 is actually required for the retry to succeed; the others are used for
    strategies' optional multi-timeframe confirmation and are simply skipped
    by `run_backtest` when absent. Only raises `MarketDataUnavailable` (so the
    caller reports "gateway unreachable" instead of retrying against
    still-missing data) when *every* call failed, i.e. the gateway itself is
    down rather than one symbol/timeframe combination being flaky."""
    start, _end = parse_period(period)
    backfill_start = start - HISTORY_BUFFER

    succeeded = False
    last_error: MarketDataUnavailable | None = None

    try:
        await candle_history.sync_symbol_spec(symbol)
        succeeded = True
    except MarketDataUnavailable as exc:
        last_error = exc
        logger.warning("auto-backfill: could not sync symbol spec for %s: %s", symbol, exc)

    for timeframe in Timeframe:
        try:
            await candle_history.backfill(symbol, timeframe, 5000, backfill_start)
            succeeded = True
        except MarketDataUnavailable as exc:
            last_error = exc
            logger.warning(
                "auto-backfill: %s %s failed, continuing with other timeframes: %s",
                symbol,
                timeframe.value,
                exc,
            )

    if not succeeded:
        assert last_error is not None
        raise last_error


def _build_full_registry(
    database_url: str, preferred_version_id: str | None = None
):  # -> StrategyRegistry (imported locally)
    """Build a registry with ALL non-archived strategies (active + validated).

    `run_backtest._default_registry` only loads the active version of each
    strategy family.  For backtest purposes, any version whose file exists on
    disk and passes sandbox validation is runnable — so we load every
    non-archived version here.

    Strategies are registered under their DB **family name** (e.g.
    ``"pob_price_action_snd  for boom 1000"``), not their Python
    ``spec.name`` field — those two can differ when a strategy was duplicated
    or renamed in the UI without touching the generated file.
    `StrategyRegistry.register()` takes that family name explicitly for
    exactly this reason, so `registry.get(family_name)` always works
    regardless of what `instance.spec.name` says inside the file.

    Because the registry is keyed by family name (not version id), the
    active-first dedup below normally wins over any other version of the
    same family — so requesting a backtest of a validated-but-not-active
    version id would otherwise silently run the active version's code
    instead. Pass that version id as `preferred_version_id` to load and
    register it last, overriding whatever the dedup picked for its family.
    """
    from src.shared.db.base import make_session_factory
    from src.strategies.adapters.repository import StrategyVersionRepository
    from src.strategies.application.versioning import StrategyVersionService
    from src.strategies.domain.versioning import VersionStatus
    from src.strategies.generated.breakout_v1 import BreakoutV1
    from src.strategies.registry import StrategyRegistry

    registry = StrategyRegistry()
    breakout_v1 = BreakoutV1()
    registry.register(breakout_v1.spec.name, breakout_v1)

    session_factory = make_session_factory(database_url)
    repo = StrategyVersionRepository(session_factory)
    svc = StrategyVersionService(
        repository=repo,
        registry=registry,
        generated_dir=_STRATEGIES_GENERATED_DIR,
    )

    # Load all non-archived versions, active first so they take priority when
    # two versions share the same family name (shouldn't happen, but be safe).
    all_versions = repo.list_all()
    active_first = sorted(
        [v for v in all_versions if v.status != VersionStatus.ARCHIVED],
        key=lambda v: 0 if v.status == VersionStatus.ACTIVE else 1,
    )

    seen_families: set[str] = set()
    for version in active_first:
        if version.name in seen_families:
            continue  # already loaded a better version of this family
        try:
            instance = svc._load_instance(version)  # noqa: SLF001
            # Register under the DB family name so the backtest runner can
            # find it regardless of what spec.name says inside the file.
            registry.register(version.name, instance)
            seen_families.add(version.name)
            logger.debug(
                "backtest registry: loaded strategy db_name=%r spec_name=%r version=%d",
                version.name,
                instance.spec.name,
                version.version,
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "backtest registry: could not load strategy name=%r version=%d",
                version.name,
                version.version,
            )

    if preferred_version_id is not None:
        preferred = repo.get(preferred_version_id)
        if preferred is not None and preferred.status != VersionStatus.ARCHIVED:
            try:
                instance = svc._load_instance(preferred)  # noqa: SLF001
                registry.register(preferred.name, instance)
                logger.debug(
                    "backtest registry: overrode family=%r with requested version=%d (id=%s)",
                    preferred.name,
                    preferred.version,
                    preferred_version_id,
                )
            except Exception:  # noqa: BLE001
                logger.warning(
                    "backtest registry: could not load preferred version id=%s",
                    preferred_version_id,
                )

    return registry


# ── New endpoints ────────────────────────────────────────────────────────────

class BotOut(BaseModel):
    id: str = Field(
        description="Stable identifier — pass this to POST /backtest/run's `strategy_id`. "
        "The literal string 'breakout_v1' for the hardcoded baseline, or a strategy "
        "version id (UUID) for everything else."
    )
    name: str = Field(
        description="Display label for this strategy family. Human-typed, not guaranteed "
        "unique or stable (can be renamed) — for showing in the UI only, never for "
        "looking anything up; use `id` for that."
    )
    symbols: list[str] = Field(description="Symbols this strategy can be backtested on.")


class RunBacktestIn(BaseModel):
    strategy_id: str = Field(description="A bot `id` from GET /backtest/bots.")
    symbol: str
    period: str = Field(
        description="'YYYY-MM:YYYY-MM' — must match candle history already in the DB."
    )
    starting_balance: float = Field(
        default=DEFAULT_STARTING_BALANCE,
        gt=0,
        description="Simulated account balance the bookkeeper starts from. "
        f"Defaults to {DEFAULT_STARTING_BALANCE:.0f} when omitted.",
    )
    min_lot_fallback_enabled: bool | None = Field(
        default=None,
        description="Override configs/risk.yaml's min-lot fallback for this run only — "
        "trades the broker minimum lot even when risk_per_trade_pct alone computes "
        "less, as long as max_risk_per_trade_pct allows it (see RiskManager.size_position). "
        "Null (default) uses whatever is currently configured (file default, or the live "
        "engine override from PUT /engine/risk-caps/min-lot-fallback).",
    )
    max_risk_per_trade_pct: float | None = Field(
        default=None,
        gt=0,
        le=100,
        description="Override configs/risk.yaml's fallback risk ceiling (%) for this run "
        "only. Only matters when min_lot_fallback_enabled ends up true. Null uses "
        "whatever is currently configured.",
    )
    min_rr: float | None = Field(
        default=None,
        gt=0,
        description="Override configs/symbols/<symbol>.yaml's min_rr (minimum spread-"
        "adjusted reward:risk ratio) for this run only. A tighter-stop strategy (e.g. a "
        "scalping variant) can fail the RR floor a swing-trading min_rr was tuned for — "
        "this lets you find a working value before flipping it on live via "
        "PUT /broker/symbols/{symbol}/min-rr. Null uses whatever is currently configured. "
        "No effect if the symbol has no configs/symbols/ file at all.",
    )


class RunBacktestOut(BaseModel):
    job_id: str
    status: str


class JobStatusOut(BaseModel):
    job_id: str
    status: str
    report_id: str | None = None
    error: str | None = None


@router.get(
    "/bots",
    response_model=list[BotOut],
    summary="List all available bots and their tradeable symbols",
    description=(
        "Returns every (id, name, symbols[]) the backtester can run — `breakout_v1` "
        "plus every non-archived strategy family in the DB. Use this to populate the "
        "'Run Backtest' launcher in the UI: show `name`, submit `id`."
    ),
)
async def list_bots() -> list[BotOut]:
    return [BotOut(**b) for b in _discover_bots()]


@router.post(
    "/run",
    response_model=RunBacktestOut,
    status_code=202,
    summary="Launch a backtest job",
    description=(
        "Starts a backtest asynchronously. Poll `GET /backtest/run/{job_id}` "
        "for status. When status is 'done', `report_id` can be fetched via "
        "`GET /backtest/reports/{report_id}`. If the local database doesn't "
        "have candle history covering all of `period` yet, this automatically "
        "backfills the missing range from the MT5 gateway before replaying — "
        "no need to call `POST /market-data/backfill` yourself first. That "
        "backfill can take a while for a long period on a fine timeframe, and "
        "fails the job (status 'error') if the gateway is unreachable or the "
        "broker's own history doesn't reach that far back."
    ),
)
async def start_backtest(
    body: RunBacktestIn,
    background_tasks: BackgroundTasks,
    request: Request,
) -> RunBacktestOut:
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": _JobStatus.PENDING, "report_id": None, "error": None}
    candle_history = request.app.state.container.candle_history
    background_tasks.add_task(
        _run_job,
        job_id,
        body.strategy_id,
        body.symbol,
        body.period,
        candle_history,
        body.starting_balance,
        body.min_lot_fallback_enabled,
        body.max_risk_per_trade_pct,
        body.min_rr,
    )
    return RunBacktestOut(job_id=job_id, status=_JobStatus.PENDING)


@router.get(
    "/run/{job_id}",
    response_model=JobStatusOut,
    summary="Poll a backtest job's status",
    responses={404: {"description": "No job with that id."}},
)
async def get_job_status(
    job_id: str = PathParam(description="Job ID returned by POST /backtest/run."),
) -> JobStatusOut:
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return JobStatusOut(
        job_id=job_id,
        status=job["status"],
        report_id=job.get("report_id"),
        error=job.get("error"),
    )


# ── Existing report-read endpoints ────────────────────────────────────────────

@router.get(
    "/reports",
    response_model=BacktestReportListOut,
    summary="List saved backtest reports",
    description=(
        "Headline stats for report files under `backend/src/backtest/reports/`, "
        "newest first, paginated via `limit`/`offset`. Reports are written by "
        "`python -m src.backtest.cli <strategy> <symbol> <period>` (or `make "
        "backtest`); this endpoint never triggers a run itself."
    ),
)
async def list_reports(
    limit: int = Query(
        default=20, ge=1, le=200, description="Max number of reports to return."
    ),
    offset: int = Query(
        default=0, ge=0, description="Number of newest reports to skip before this page."
    ),
) -> BacktestReportListOut:
    if not REPORTS_DIR.exists():
        return BacktestReportListOut(items=[], total=0, limit=limit, offset=offset)
    paths = sorted(REPORTS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    page = paths[offset : offset + limit]
    items = [_summary(_load(p), p.stem) for p in page]
    return BacktestReportListOut(items=items, total=len(paths), limit=limit, offset=offset)


@router.get(
    "/reports/{report_id}",
    response_model=BacktestReportDetailOut,
    summary="Get a single backtest report",
    description=(
        "Full report for `report_id` (the filename stem returned by "
        "`GET /backtest/reports`) — every trade and the equity curve, for the "
        "report detail page's trade table and equity chart."
    ),
    responses={404: {"description": "No report file with that id."}},
)
async def get_report(
    report_id: str = PathParam(description="Report id, as returned by GET /backtest/reports."),
) -> BacktestReportDetailOut:
    if not _VALID_ID.match(report_id):
        raise HTTPException(status_code=404, detail="report not found")
    path = REPORTS_DIR / f"{report_id}.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="report not found")
    data = _load(path)
    return BacktestReportDetailOut(
        **_summary(data, report_id).model_dump(),
        trades=[_trade_out(t) for t in data["trades"]],
        equity_curve=_equity_curve_out(data["equity_curve"]),
        activity_log=[_activity_log_entry_out(e) for e in data.get("activity_log", [])],
    )


@router.delete(
    "/reports/{report_id}",
    status_code=204,
    summary="Delete a saved backtest report",
    description=(
        "Hard-deletes the report file for `report_id` under "
        "`backend/src/backtest/reports/`. This cannot be undone."
    ),
    responses={404: {"description": "No report file with that id."}},
)
async def delete_report(
    report_id: str = PathParam(description="Report id, as returned by GET /backtest/reports."),
) -> None:
    if not _VALID_ID.match(report_id):
        raise HTTPException(status_code=404, detail="report not found")
    path = REPORTS_DIR / f"{report_id}.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="report not found")
    path.unlink()


def _load(path: Any) -> dict[str, Any]:
    with path.open() as f:
        return json.load(f)


def _summary(data: dict[str, Any], report_id: str) -> BacktestReportSummaryOut:
    return BacktestReportSummaryOut(
        id=report_id,
        strategy=data["strategy"],
        symbol=data["symbol"],
        period=data["period"],
        trade_count=len(data["trades"]),
        win_rate=data["win_rate"],
        profit_factor=data["profit_factor"],
        max_drawdown_pct=data["max_drawdown_pct"],
        avg_r=data["avg_r"],
        worst_losing_streak=data["worst_losing_streak"],
        starting_balance=data["starting_balance"],
        ending_balance=data["ending_balance"],
        min_rr=data.get("min_rr", 1.0),
        risk_per_trade_pct=data.get("risk_per_trade_pct", 0.5),
        daily_loss_limit_pct=data.get("daily_loss_limit_pct", 2.0),
        max_open_positions=data.get("max_open_positions", 100),
        max_trades_per_day=data.get("max_trades_per_day", 8),
        consecutive_loss_pause=data.get("consecutive_loss_pause", 10),
        min_lot_fallback_enabled=data.get("min_lot_fallback_enabled", False),
        max_risk_per_trade_pct=data.get("max_risk_per_trade_pct"),
    )


def _trade_out(trade: dict[str, Any]) -> dict[str, Any]:
    zone = trade.get("zone")
    structure = trade.get("structure") or []
    return {
        **trade,
        "open_time": _epoch(trade["open_time"]),
        "close_time": _epoch(trade["close_time"]),
        "zone": _zone_out(zone) if zone is not None else None,
        "structure": [
            {"label": label, "price": price, "time": _epoch(time_iso)}
            for label, price, time_iso in structure
        ],
    }


def _zone_out(zone: dict[str, Any]) -> dict[str, Any]:
    return {
        **zone,
        "time_start": _epoch(zone["time_start"]),
        "time_end": _epoch(zone["time_end"]),
    }


def _epoch(iso: str) -> int:
    return int(datetime.fromisoformat(iso).astimezone(UTC).timestamp())


def _activity_log_entry_out(entry: dict[str, Any]) -> dict[str, Any]:
    return {**entry, "time": _epoch(entry["time"])}


def _equity_curve_out(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse same-second points to strictly ascending epochs.

    `lightweight-charts` rejects non-increasing timestamps. Two positions can
    close within the same second (or, for legacy report files predating the
    bookkeeper's same-bar coalescing, the same bar); keep the last balance
    for that second rather than crash the report page.
    """
    out: list[dict[str, Any]] = []
    for p in points:
        epoch = _epoch(p["time"])
        if out and out[-1]["time"] == epoch:
            out[-1] = {"time": epoch, "balance": p["balance"]}
        else:
            out.append({"time": epoch, "balance": p["balance"]})
    return out
