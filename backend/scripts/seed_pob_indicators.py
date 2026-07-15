"""Seed the 15 PoB pattern/confirmation indicators (see
`backend/scripts/pob_indicators/*.py`) into the indicator DB so they show up
in `/indicators` and the chart's IndicatorsDock immediately — after that
they're ordinary `IndicatorDefinition` rows, fully duplicable/editable/
deletable through the normal UI like anything a user creates by hand.

Run from `backend/`:

    uv run python -m scripts.seed_pob_indicators

Safely re-runnable: an indicator whose name already exists is skipped
(logged, not overwritten) rather than erroring the whole run, so re-seeding
after adding a new file doesn't require deleting the DB first.
"""

from __future__ import annotations

import logging
from pathlib import Path

from src.indicators.adapters.repository import IndicatorRepository
from src.indicators.application.service import (
    IndicatorNameConflictError,
    IndicatorService,
    IndicatorValidationError,
)
from src.market_data.adapters.candle_repository import CandleRepository
from src.shared.config.settings import Settings
from src.shared.db.base import make_session_factory

logger = logging.getLogger(__name__)

_INDICATORS_DIR = Path(__file__).resolve().parent / "pob_indicators"

# (file stem, display name) — display names are what traders see in
# /indicators and the IndicatorsDock picker.
_POB_INDICATORS: tuple[tuple[str, str], ...] = (
    ("pob_snrc1", "PoB SNRC1 (Continuation)"),
    ("pob_snrc2", "PoB SNRC2 (Reversal off Zone)"),
    ("pob_qmr", "PoB QMR (Quasimodo Reversal)"),
    ("pob_qm2p", "PoB QM2P (Quasimodo + Head Trendline)"),
    ("pob_qmm", "PoB QMM (Quasimodo Manipulation)"),
    ("pob_qmc", "PoB QMC (Quasimodo Continuation)"),
    ("pob_hybrid1", "PoB Hybrid 1"),
    ("pob_hybrid2", "PoB Hybrid 2"),
    ("pob_blindspot1", "PoB Blindspot 1"),
    ("pob_blindspot2", "PoB Blindspot 2"),
    ("pob_engulfing", "PoB Engulfing Candle"),
    ("pob_pin_bar", "PoB Pin Bar"),
    ("pob_body_candle", "PoB Body/Momentum Candle"),
    ("pob_ck_confluence", "PoB CK Confluence"),
    ("pob_swing_structure", "PoB Swing Structure (HH/HL/LH/LL)"),
)


def seed(service: IndicatorService) -> None:
    for file_stem, display_name in _POB_INDICATORS:
        code = (_INDICATORS_DIR / f"{file_stem}.py").read_text()
        try:
            service.create(name=display_name, code=code)
        except IndicatorNameConflictError:
            logger.info("skipping %r — already seeded", display_name)
        except IndicatorValidationError as exc:
            logger.error("failed to seed %r: %s", display_name, exc)
        else:
            logger.info("seeded %r", display_name)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = Settings()
    session_factory = make_session_factory(settings.database_url)
    candle_repository = CandleRepository(session_factory)
    indicator_repository = IndicatorRepository(session_factory)
    service = IndicatorService(repository=indicator_repository, candle_repository=candle_repository)
    seed(service)


if __name__ == "__main__":
    main()
