"""Logging setup.

Money-touching decisions (signals, vetoes, spread checks, lot calculations)
are logged at INFO by their modules — this configures where they go.
"""

from __future__ import annotations

import logging


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
