"""workflows — Multi-step workflow run state engine backed by MySQL."""

import logging
from fastapi import FastAPI

from infra.workflows.db import ensure_tables

logger = logging.getLogger(__name__)


def register(app: FastAPI) -> None:
    """
    Call this from your FastAPI startup event.
    Creates the MySQL tables if they do not already exist.
    Non-fatal: a missing MySQL connection will produce a warning but
    will not prevent the harness itself from starting.
    """
    try:
        ensure_tables()
        logger.info("workflows: MySQL tables created / verified")
    except Exception as exc:
        logger.warning(
            "workflows: could not initialise MySQL tables — "
            "workflow endpoints will fail until MySQL is reachable (%s)",
            exc,
        )
