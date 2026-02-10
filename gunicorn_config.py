"""
Gunicorn configuration for production deployment.

Usage:
    gunicorn -c gunicorn_config.py wsgi:app

Environment variables:
    GUNICORN_BIND: Address to bind (default: 0.0.0.0:5000)
    GUNICORN_WORKERS: Number of worker processes (default: 4)
    GUNICORN_THREADS: Threads per worker (default: 2)
    GUNICORN_TIMEOUT: Worker timeout in seconds (default: 120)
    GUNICORN_LOG_LEVEL: Logging level (default: info)
"""
import os
import multiprocessing

# Bind address
bind = os.getenv("GUNICORN_BIND", "0.0.0.0:5000")

# Worker processes
# Recommended: 2-4 x CPU cores for CPU-bound, 4-12 for I/O-bound
workers = int(os.getenv("GUNICORN_WORKERS", multiprocessing.cpu_count() * 2 + 1))

# Threads per worker (for concurrent requests within a worker)
threads = int(os.getenv("GUNICORN_THREADS", 2))

# Worker class (sync is fine for most Flask apps)
worker_class = "sync"

# Request timeout (seconds)
timeout = int(os.getenv("GUNICORN_TIMEOUT", 120))

# Graceful timeout for worker restart
graceful_timeout = 30

# Keep-alive timeout
keepalive = 5

# Maximum requests per worker before restart (prevents memory leaks)
max_requests = 1000
max_requests_jitter = 50

# Logging
loglevel = os.getenv("GUNICORN_LOG_LEVEL", "info")
accesslog = "-"  # stdout
errorlog = "-"   # stderr
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = "mektep_scraper"

# Preload app (shares memory between workers, faster startup)
preload_app = True

# Daemon mode (set to True for background service)
daemon = False

# PID file
pidfile = None

# Umask
umask = 0o022


def on_starting(server):
    """Called just before the master process is initialized."""
    print(f"[Gunicorn] Starting with {workers} workers, {threads} threads each")


def on_reload(server):
    """Called when workers are being reloaded."""
    print("[Gunicorn] Reloading workers...")


def worker_int(worker):
    """Called when worker receives INT or QUIT signal."""
    print(f"[Gunicorn] Worker {worker.pid} interrupted")


def worker_exit(server, worker):
    """Called when a worker exits."""
    print(f"[Gunicorn] Worker {worker.pid} exited")
