"""Фоновый экспорт Excel: POST /admin/exports, статус, скачивание."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta

from flask import current_app, jsonify, request, send_file, session, url_for
from flask_login import current_user

from ...extensions import db
from ...models import ExportJob, ExportJobStatus
from ...services.auth_guards import admin_or_superadmin_required as admin_required
from ...services.export_runner import run_export_job
from . import bp


def enqueue_export_job(job: ExportJob) -> None:
    """Celery при USE_CELERY=1, иначе поток (как teacher scrape)."""
    use_celery = current_app.config.get("USE_CELERY", False)
    app_obj = current_app._get_current_object()

    if use_celery:
        try:
            from ...tasks import run_export_task

            task = run_export_task.delay(job_id=job.id)
            job.celery_task_id = task.id
            db.session.commit()
            return
        except Exception as exc:
            current_app.logger.error("Celery export failed, using thread: %s", exc)

    thread = threading.Thread(
        target=_run_export_in_app,
        kwargs={"app": app_obj, "job_id": job.id},
        daemon=True,
    )
    thread.start()


def _run_export_in_app(app, job_id: int) -> None:
    with app.app_context():
        run_export_job(job_id)


@bp.post("/exports")
@admin_required
def create_export():
    """Создать задачу экспорта (JSON body или form)."""
    data = request.get_json(silent=True) or request.form
    export_kind = (data.get("export_kind") or "").strip()
    if not export_kind:
        return jsonify({"success": False, "error": "export_kind required"}), 400

    allowed = {
        "analytics",
        "criteria_zip",
        "grades_class",
        "class_teacher",
        "metrics_charts",
    }
    if export_kind not in allowed:
        return jsonify({"success": False, "error": f"invalid export_kind: {export_kind}"}), 400

    params = dict(data) if hasattr(data, "items") else {}
    params.pop("export_kind", None)
    params["lang"] = session.get("language", "ru")

    job = ExportJob(
        school_id=current_user.school_id,
        user_id=current_user.id,
        export_kind=export_kind,
        params_json=json.dumps(params, ensure_ascii=False),
        status=ExportJobStatus.PENDING.value,
        expires_at=datetime.utcnow() + timedelta(hours=24),
    )
    db.session.add(job)
    db.session.commit()

    enqueue_export_job(job)

    return jsonify(
        {
            "success": True,
            "job_id": job.id,
            "status_url": url_for("admin.export_status", job_id=job.id),
        }
    )


@bp.get("/exports/<int:job_id>/status")
@admin_required
def export_status(job_id: int):
    job = ExportJob.query.filter_by(
        id=job_id, school_id=current_user.school_id, user_id=current_user.id
    ).first()
    if not job:
        return jsonify({"success": False, "error": "not found"}), 404

    payload = {
        "success": True,
        "status": job.status,
        "error": job.error,
    }
    if job.status == ExportJobStatus.DONE.value and job.file_path:
        payload["download_url"] = url_for("admin.export_download", job_id=job.id)
    return jsonify(payload)


@bp.get("/exports/<int:job_id>/download")
@admin_required
def export_download(job_id: int):
    job = ExportJob.query.filter_by(
        id=job_id, school_id=current_user.school_id, user_id=current_user.id
    ).first()
    if not job or job.status != ExportJobStatus.DONE.value or not job.file_path:
        return jsonify({"success": False, "error": "not ready"}), 404

    path = job.file_path
    return send_file(
        path,
        as_attachment=True,
        download_name=path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1],
    )
