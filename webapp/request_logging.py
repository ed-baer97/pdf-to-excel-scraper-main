"""
HTTP request correlation and timing middleware.
"""
from __future__ import annotations

import time
import uuid

from flask import Flask, g, jsonify, request
from werkzeug.exceptions import HTTPException


def register_request_logging(app: Flask) -> None:
    """Register before/after request hooks for request_id and duration logging."""

    @app.before_request
    def _start_request_timer():
        g.request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        g.request_start = time.perf_counter()

    @app.after_request
    def _log_request(response):
        duration_ms = None
        if hasattr(g, "request_start"):
            duration_ms = round((time.perf_counter() - g.request_start) * 1000, 1)

        user_id = None
        school_id = None
        try:
            from flask_login import current_user

            if current_user.is_authenticated:
                user_id = getattr(current_user, "id", None)
                school_id = getattr(current_user, "school_id", None)
        except Exception:
            pass

        # Skip noisy health/metrics probes unless slow or error
        path = request.path or ""
        is_probe = path.startswith("/health") or path == "/metrics"
        is_error = response.status_code >= 400
        is_slow = duration_ms is not None and duration_ms >= float(
            app.config.get("SLOW_REQUEST_MS", 1000)
        )

        if not is_probe or is_error or is_slow:
            app.logger.info(
                "http_request",
                extra={
                    "request_id": getattr(g, "request_id", None),
                    "method": request.method,
                    "path": path,
                    "status": response.status_code,
                    "duration_ms": duration_ms,
                    "user_id": user_id,
                    "school_id": school_id,
                    "remote_addr": request.remote_addr,
                },
            )

        response.headers["X-Request-ID"] = getattr(g, "request_id", "")
        return response


def register_error_handlers(app: Flask) -> None:
    """Log unhandled exceptions and return a safe 500 response."""

    @app.errorhandler(Exception)
    def _handle_unhandled_exception(exc):
        if isinstance(exc, HTTPException):
            return exc

        app.logger.exception(
            "unhandled_exception",
            extra={
                "request_id": getattr(g, "request_id", None),
                "method": request.method,
                "path": request.path,
            },
        )

        if app.debug or app.config.get("TESTING"):
            raise exc

        return jsonify({"error": "Internal server error"}), 500
