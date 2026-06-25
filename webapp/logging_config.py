"""
Centralized logging configuration for production observability.

Outputs structured JSON logs to stdout (Docker/systemd friendly).
"""
from __future__ import annotations

import logging
import logging.config
import os
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask import Flask


class _RequestContextFilter(logging.Filter):
    """Attach request_id from Flask g to log records when available."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            from flask import g, has_request_context

            if has_request_context():
                record.request_id = getattr(g, "request_id", None)
            else:
                record.request_id = None
        except Exception:
            record.request_id = None
        return True


def configure_logging(app: Flask | None = None) -> None:
    """
    Configure root and framework loggers with JSON output to stdout.

    Args:
        app: Optional Flask app for level/config lookup.
    """
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    if app is not None:
        log_level = str(app.config.get("LOG_LEVEL", log_level)).upper()

    use_json = os.getenv("LOG_JSON", "1").lower() in ("1", "true", "yes")
    if app is not None:
        if app.config.get("TESTING"):
            use_json = False
        else:
            use_json = bool(app.config.get("LOG_JSON", use_json))

    formatter_name = "json" if use_json else "plain"

    formatters: dict = {
        "plain": {
            "format": "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        },
    }
    if use_json:
        formatters["json"] = {
            "()": "pythonjsonlogger.json.JsonFormatter",
            "format": (
                "%(asctime)s %(levelname)s %(name)s %(message)s "
                "%(request_id)s"
            ),
        }

    config = {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "request_context": {
                "()": _RequestContextFilter,
            },
        },
        "formatters": formatters,
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "formatter": formatter_name,
                "filters": ["request_context"],
            },
        },
        "root": {
            "level": log_level,
            "handlers": ["console"],
        },
        "loggers": {
            "werkzeug": {
                "level": "WARNING",
                "handlers": ["console"],
                "propagate": False,
            },
            "gunicorn.error": {
                "level": log_level,
                "handlers": ["console"],
                "propagate": False,
            },
            "gunicorn.access": {
                "level": log_level,
                "handlers": ["console"],
                "propagate": False,
            },
            "sqlalchemy.engine": {
                "level": "WARNING",
                "handlers": ["console"],
                "propagate": False,
            },
        },
    }

    logging.config.dictConfig(config)

    if app is not None:
        app.logger.handlers.clear()
        app.logger.propagate = True
        app.logger.setLevel(getattr(logging, log_level, logging.INFO))


def init_sentry(app: Flask) -> None:
    """Initialize Sentry/GlitchTip error tracking when SENTRY_DSN is set."""
    dsn = app.config.get("SENTRY_DSN") or os.getenv("SENTRY_DSN", "")
    if not dsn:
        return

    try:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration
    except ImportError:
        app.logger.warning("sentry-sdk not installed; error tracking disabled")
        return

    traces_sample_rate = float(
        app.config.get("SENTRY_TRACES_SAMPLE_RATE")
        or os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1")
    )
    environment = os.getenv("FLASK_ENV", "production")

    sentry_sdk.init(
        dsn=dsn,
        integrations=[FlaskIntegration()],
        environment=environment,
        traces_sample_rate=traces_sample_rate,
        send_default_pii=False,
    )
    app.logger.info("Sentry/GlitchTip error tracking enabled")
