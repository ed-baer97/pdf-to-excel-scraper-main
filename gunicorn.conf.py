"""
Gunicorn configuration file.

Usage:
    gunicorn -c gunicorn.conf.py wsgi:app

Or with environment override:
    GUNICORN_WORKERS=8 gunicorn -c gunicorn.conf.py wsgi:app
"""
import os
import multiprocessing

# Bind to address
bind = os.getenv("GUNICORN_BIND", "0.0.0.0:5000")

# Number of worker processes
# Rule of thumb: 2-4 x CPU cores for I/O bound apps
# For scraping app with heavy background tasks, keep it lower
workers = int(os.getenv("GUNICORN_WORKERS", min(4, multiprocessing.cpu_count() * 2)))

# Worker class - sync is fine for Flask with background threads
worker_class = os.getenv("GUNICORN_WORKER_CLASS", "sync")

# Threads per worker (for handling concurrent requests within a worker)
threads = int(os.getenv("GUNICORN_THREADS", 2))

# Request timeout (seconds) - important for long-running requests
timeout = int(os.getenv("GUNICORN_TIMEOUT", 120))

# Graceful timeout for worker restart
graceful_timeout = int(os.getenv("GUNICORN_GRACEFUL_TIMEOUT", 30))

# Keep-alive connections
keepalive = int(os.getenv("GUNICORN_KEEPALIVE", 5))

# Maximum requests before worker restart (prevents memory leaks)
max_requests = int(os.getenv("GUNICORN_MAX_REQUESTS", 1000))
max_requests_jitter = int(os.getenv("GUNICORN_MAX_REQUESTS_JITTER", 50))

# Logging
accesslog = os.getenv("GUNICORN_ACCESS_LOG", "-")  # "-" = stdout
errorlog = os.getenv("GUNICORN_ERROR_LOG", "-")
loglevel = os.getenv("GUNICORN_LOG_LEVEL", "info")

# Process naming
proc_name = "mektep-scraper"

# Preload app for faster worker startup and shared memory
# BUT: disable if using --reload for development
preload_app = os.getenv("GUNICORN_PRELOAD", "false").lower() == "true"

# Security: limit request sizes
limit_request_line = 4094
limit_request_fields = 100
limit_request_field_size = 8190


def on_starting(server):
    """Called just before the master process is initialized."""
    pass


def on_exit(server):
    """Called just before exiting Gunicorn."""
    pass


def worker_abort(worker):
    """Called when a worker times out."""
    import traceback
    worker.log.warning(f"Worker {worker.pid} was aborted. Stack trace:")
    for line in traceback.format_stack():
        worker.log.warning(line.strip())
