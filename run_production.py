#!/usr/bin/env python3
"""
Production server launcher.

This script automatically selects the best production server:
- Gunicorn on Linux/Mac
- Waitress on Windows

Usage:
    python run_production.py
    
Environment variables:
    See env.example for full list.
"""
import os
import sys

from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()


def run_gunicorn():
    """Run with Gunicorn (Unix only)."""
    import subprocess
    
    bind = os.getenv("GUNICORN_BIND", "0.0.0.0:5000")
    workers = os.getenv("GUNICORN_WORKERS", "4")
    threads = os.getenv("GUNICORN_THREADS", "2")
    timeout = os.getenv("GUNICORN_TIMEOUT", "120")
    loglevel = os.getenv("GUNICORN_LOG_LEVEL", "info")
    
    cmd = [
        sys.executable, "-m", "gunicorn",
        "-c", "gunicorn_config.py",
        "wsgi:app"
    ]
    
    print(f"[Production] Starting Gunicorn on {bind}")
    print(f"[Production] Workers: {workers}, Threads: {threads}")
    
    subprocess.run(cmd)


def run_waitress():
    """Run with Waitress (Windows compatible)."""
    from waitress import serve
    from webapp import create_app
    
    host = os.getenv("WAITRESS_HOST", "0.0.0.0")
    port = int(os.getenv("WAITRESS_PORT", 5000))
    threads = int(os.getenv("WAITRESS_THREADS", 4))
    
    app = create_app()
    
    print(f"[Production] Starting Waitress on {host}:{port}")
    print(f"[Production] Threads: {threads}")
    
    serve(
        app,
        host=host,
        port=port,
        threads=threads,
        url_scheme="http",
        ident="Mektep Scraper",
    )


def main():
    """Select and run production server."""
    # Check environment
    flask_env = os.getenv("FLASK_ENV", "production")
    if flask_env == "development":
        print("[Warning] FLASK_ENV=development. Set FLASK_ENV=production for production!")
        print("[Warning] Continuing anyway...")
    
    # Select server based on platform
    if sys.platform == "win32":
        print("[Production] Windows detected, using Waitress")
        run_waitress()
    else:
        print("[Production] Unix detected, using Gunicorn")
        run_gunicorn()


if __name__ == "__main__":
    main()
