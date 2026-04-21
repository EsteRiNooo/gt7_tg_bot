"""Shared logging setup for race sources (GT7, LMU, LFM)."""

from __future__ import annotations

import logging

_races_logging_configured = False


def ensure_races_logging_configured() -> None:
    """Call ``logging.basicConfig(level=logging.INFO)`` at most once."""
    global _races_logging_configured
    if _races_logging_configured:
        return
    logging.basicConfig(level=logging.INFO)
    _races_logging_configured = True


logger = logging.getLogger("races")
