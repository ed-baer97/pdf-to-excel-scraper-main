"""
Gunicorn configuration for production deployment.

Usage:
    gunicorn -c gunicorn_config.py wsgi:app

Environment variables:
    GUNICORN_BIND, GUNICORN_WORKERS, GUNICORN_THREADS, GUNICORN_TIMEOUT,
    GUNICORN_LOG_LEVEL, GUNICORN_WORKER_CLASS, GUNICORN_PRELOAD,
    GUNICORN_ACCESS_LOG, GUNICORN_ERROR_LOG, GUNICORN_GRACEFUL_TIMEOUT,
    GUNICORN_KEEPALIVE, GUNICORN_MAX_REQUESTS, GUNICORN_MAX_REQUESTS_JITTER
"""
import os
import multiprocessing

# Bind address
bind = os.getenv("GUNICORN_BIND", "0.0.0.0:5000")

# Worker processes (default: conservative cap for I/O-heavy app)
_default_workers = min(4, max(1, multiprocessing.cpu_count() * 2))
workers = int(os.getenv("GUNICORN_WORKERS", str(_default_workers)))

# Threads per worker
threads = int(os.getenv("GUNICORN_THREADS", 2))

# Worker class
worker_class = os.getenv("GUNICORN_WORKER_CLASS", "sync")

# Request timeout (seconds)
timeout = int(os.getenv("GUNICORN_TIMEOUT", 120))

graceful_timeout = int(os.getenv("GUNICORN_GRACEFUL_TIMEOUT", 30))

keepalive = int(os.getenv("GUNICORN_KEEPALIVE", 5))

max_requests = int(os.getenv("GUNICORN_MAX_REQUESTS", 1000))
max_requests_jitter = int(os.getenv("GUNICORN_MAX_REQUESTS_JITTER", 50))

# Logging
loglevel = os.getenv("GUNICORN_LOG_LEVEL", "info")
accesslog = os.getenv("GUNICORN_ACCESS_LOG", "-")
errorlog = os.getenv("GUNICORN_ERROR_LOG", "-")
access_log_format = (
    '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'
)

# Process naming
proc_name = "mektep_scraper"

# Preload (disable with GUNICORN_PRELOAD=false for dev --reload)
preload_app = os.getenv("GUNICORN_PRELOAD", "true").lower() == "true"

daemon = False
pidfile = None
umask = 0o022

# Security: limit request sizes
limit_request_line = 4094
limit_request_fields = 100
limit_request_field_size = 8190


def on_starting(server):
    """Вызывается Gunicorn до инициализации master-процесса; печатает число воркеров."""
    print(f"[Gunicorn] Starting with {workers} workers, {threads} threads each")


def on_reload(server):
    """Вызывается при перезагрузке воркеров (SIGHUP и т.п.)."""
    print("[Gunicorn] Reloading workers...")


def worker_int(worker):
    """Вызывается, когда воркер получает SIGINT/SIGQUIT."""
    print(f"[Gunicorn] Worker {worker.pid} interrupted")


def worker_exit(server, worker):
    """Вызывается при завершении воркера."""
    print(f"[Gunicorn] Worker {worker.pid} exited")


def worker_abort(worker):
    """Вызывается при таймауте воркера; пишет предупреждение и стек в лог."""
    import traceback

    worker.log.warning(f"Worker {worker.pid} was aborted. Stack trace:")
    for line in traceback.format_stack():
        worker.log.warning(line.strip())
