"""
SQLAlchemy listeners for slow query logging.
"""
from __future__ import annotations

import logging
import os
import time
from typing import TYPE_CHECKING

from sqlalchemy import event

from .extensions import db

if TYPE_CHECKING:
    from flask import Flask

logger = logging.getLogger("webapp.slow_sql")


def register_slow_sql_logging(app: Flask) -> None:
    """Log SQL statements that exceed SLOW_SQL_MS threshold."""

    threshold_ms = float(
        app.config.get("SLOW_SQL_MS") or os.getenv("SLOW_SQL_MS", "500")
    )

    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        conn.info.setdefault("query_start_time", []).append(time.perf_counter())

    def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        start_stack = conn.info.get("query_start_time")
        if not start_stack:
            return
        elapsed_ms = (time.perf_counter() - start_stack.pop()) * 1000
        if elapsed_ms >= threshold_ms:
            logger.warning(
                "slow_sql",
                extra={
                    "duration_ms": round(elapsed_ms, 1),
                    "statement": statement[:2000],
                },
            )

    with app.app_context():
        event.listen(db.engine, "before_cursor_execute", _before_cursor_execute)
        event.listen(db.engine, "after_cursor_execute", _after_cursor_execute)
