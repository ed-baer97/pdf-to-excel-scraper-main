"""
Health check endpoints for monitoring and load balancers.

Endpoints:
    GET /health         - Basic health check (returns 200 if app is running)
    GET /health/ready   - Readiness check (database connection, etc.)
    GET /health/live    - Liveness check (app is alive)
    GET /health/stats   - Application statistics (requires auth in production)
"""
from flask import Blueprint, jsonify, current_app
from datetime import datetime

from ..extensions import db
from ..models import ScrapeJob, ScrapeJobStatus, School, User

bp = Blueprint("health", __name__, url_prefix="/health")


@bp.get("/")
@bp.get("/live")
def liveness():
    """
    Liveness probe - is the application running?
    Used by Kubernetes/load balancers to determine if app should be restarted.
    """
    return jsonify({
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
    })


@bp.get("/ready")
def readiness():
    """
    Readiness probe - is the application ready to serve traffic?
    Checks database connectivity and other dependencies.
    """
    checks = {
        "database": False,
        "timestamp": datetime.utcnow().isoformat(),
    }
    
    # Check database connection
    try:
        db.session.execute(db.text("SELECT 1"))
        checks["database"] = True
    except Exception as e:
        checks["database_error"] = str(e)
    
    # Overall status
    all_ok = all(v for k, v in checks.items() if k not in ("timestamp", "database_error"))
    checks["status"] = "ok" if all_ok else "degraded"
    
    status_code = 200 if all_ok else 503
    return jsonify(checks), status_code


@bp.get("/stats")
def stats():
    """
    Application statistics.
    In production, this should be protected or return limited info.
    """
    try:
        # Get job statistics
        from ..scraper_runner import get_active_jobs_count, get_max_concurrent_jobs
        
        total_jobs = ScrapeJob.query.count()
        running_jobs = ScrapeJob.query.filter_by(status=ScrapeJobStatus.RUNNING.value).count()
        queued_jobs = ScrapeJob.query.filter_by(status=ScrapeJobStatus.QUEUED.value).count()
        succeeded_jobs = ScrapeJob.query.filter_by(status=ScrapeJobStatus.SUCCEEDED.value).count()
        failed_jobs = ScrapeJob.query.filter_by(status=ScrapeJobStatus.FAILED.value).count()
        
        total_schools = School.query.count()
        active_schools = School.query.filter_by(is_active=True).count()
        total_users = User.query.count()
        
        return jsonify({
            "status": "ok",
            "timestamp": datetime.utcnow().isoformat(),
            "jobs": {
                "total": total_jobs,
                "running": running_jobs,
                "queued": queued_jobs,
                "succeeded": succeeded_jobs,
                "failed": failed_jobs,
                "active_processes": get_active_jobs_count(),
                "max_concurrent": get_max_concurrent_jobs(),
            },
            "schools": {
                "total": total_schools,
                "active": active_schools,
            },
            "users": {
                "total": total_users,
            },
            "config": {
                "debug": current_app.debug,
                "max_concurrent_jobs": current_app.config.get("MAX_CONCURRENT_JOBS", 3),
                "job_timeout_seconds": current_app.config.get("JOB_TIMEOUT_SECONDS", 1800),
            }
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat(),
        }), 500
