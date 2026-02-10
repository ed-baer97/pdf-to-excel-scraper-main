"""
Celery configuration for async task processing.

This module sets up Celery for background job processing,
enabling scalable scraping operations.

Usage:
    # Start worker:
    celery -A webapp.celery_app worker --loglevel=info --pool=solo
    
    # On Windows (solo pool required):
    celery -A webapp.celery_app worker --loglevel=info --pool=solo
    
    # With multiple workers (Linux/Mac):
    celery -A webapp.celery_app worker --loglevel=info --concurrency=4
"""
from __future__ import annotations

import os
from celery import Celery

# Redis URL from environment (default: localhost)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", REDIS_URL)


def make_celery(app_name: str = "mektep_scraper") -> Celery:
    """Create Celery instance with configuration."""
    celery = Celery(
        app_name,
        broker=CELERY_BROKER_URL,
        backend=CELERY_RESULT_BACKEND,
        include=["webapp.tasks"]  # Auto-discover tasks
    )
    
    celery.conf.update(
        # Task settings
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        
        # Task execution
        task_acks_late=True,  # Acknowledge after task completes
        task_reject_on_worker_lost=True,  # Retry if worker dies
        worker_prefetch_multiplier=1,  # One task at a time per worker
        
        # Result expiration (24 hours)
        result_expires=86400,
        
        # Task time limits
        task_soft_time_limit=1800,  # 30 min soft limit
        task_time_limit=2100,  # 35 min hard limit
        
        # Retry settings
        task_default_retry_delay=60,  # 1 min between retries
        task_max_retries=3,
        
        # Rate limiting (per worker)
        worker_concurrency=int(os.getenv("CELERY_CONCURRENCY", "2")),
        
        # Task routes (optional - for separate queues)
        task_routes={
            "webapp.tasks.run_scrape_task": {"queue": "scraping"},
            "webapp.tasks.generate_ai_text": {"queue": "ai"},
        },
        
        # Default queue
        task_default_queue="default",
    )
    
    return celery


# Create global Celery instance
celery_app = make_celery()


def init_celery(flask_app):
    """
    Initialize Celery with Flask app context.
    
    This allows tasks to access Flask config and database.
    """
    celery_app.conf.update(flask_app.config)
    
    class ContextTask(celery_app.Task):
        """Task that runs within Flask app context."""
        
        def __call__(self, *args, **kwargs):
            with flask_app.app_context():
                return self.run(*args, **kwargs)
    
    celery_app.Task = ContextTask
    return celery_app
