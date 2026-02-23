from flask import Flask, request, session
from pathlib import Path

from .config import get_config
from .extensions import db, login_manager, migrate
from .models import ReportFile, Role, School, ScrapeJob, ScrapeJobStatus, User
from .translator import gettext as custom_gettext

# Celery app (initialized lazily)
celery_app = None


def create_app(config_object=None) -> Flask:
    """
    Application factory.
    
    Args:
        config_object: Configuration class. If None, auto-detect from FLASK_ENV.
    """
    if config_object is None:
        config_object = get_config()
    
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_object(config_object)

    # Prometheus metrics (internal /metrics endpoint)
    try:
        from prometheus_flask_exporter import PrometheusMetrics
        PrometheusMetrics(app)
    except ImportError:
        pass  # prometheus-flask-exporter not installed

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    
    # Функция выбора локали
    def get_locale():
        # Проверяем сохраненный язык в сессии
        return session.get('language', 'ru')
    
    # Добавляем get_locale и gettext в контекст шаблонов
    @app.context_processor
    def inject_locale():
        current_lang = get_locale()
        return dict(
            get_locale=lambda: current_lang,
            _=lambda key: custom_gettext(key, current_lang)
        )

    @login_manager.user_loader
    def load_user(user_id: str):
        return db.session.get(User, int(user_id))

    # Blueprints
    from .views.main import bp as main_bp
    from .views.auth import bp as auth_bp
    from .views.superadmin import bp as superadmin_bp
    from .views.admin import bp as admin_bp
    from .views.teacher import bp as teacher_bp
    from .views.health import bp as health_bp
    from .views.api import bp as api_bp  # Desktop API

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(superadmin_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(teacher_bp)
    app.register_blueprint(health_bp)
    app.register_blueprint(api_bp)  # Register Desktop API

    # CLI
    from .cli import create_superadmin
    app.cli.add_command(create_superadmin)

    # Lightweight “no-terminal” bootstrap for dev: create tables if missing.
    with app.app_context():
        db.create_all()

        # ---- Lightweight runtime schema upgrades (SQLite + PostgreSQL compatible) ----
        # This repo historically used db.create_all() without proper migrations.
        # We keep it robust by adding new columns/indexes when missing.
        try:
            from sqlalchemy import text, inspect
            
            inspector = inspect(db.engine)
            
            def _has_column(table: str, col: str) -> bool:
                """Check if column exists in table (works with SQLite and PostgreSQL)."""
                try:
                    columns = [c["name"] for c in inspector.get_columns(table)]
                    return col in columns
                except Exception:
                    return False

            # users.fs_teacher_seq
            if not _has_column("users", "fs_teacher_seq"):
                db.session.execute(text("ALTER TABLE users ADD COLUMN fs_teacher_seq INTEGER"))
                # Index creation syntax works for both SQLite and PostgreSQL
                try:
                    db.session.execute(text("CREATE INDEX ix_users_fs_teacher_seq ON users (fs_teacher_seq)"))
                except Exception:
                    pass  # Index might already exist
                db.session.commit()

            # scrape_jobs.fs_job_seq
            if not _has_column("scrape_jobs", "fs_job_seq"):
                db.session.execute(text("ALTER TABLE scrape_jobs ADD COLUMN fs_job_seq INTEGER"))
                try:
                    db.session.execute(text("CREATE INDEX ix_scrape_jobs_fs_job_seq ON scrape_jobs (fs_job_seq)"))
                except Exception:
                    pass  # Index might already exist
                db.session.commit()

            # scrape_jobs.celery_task_id (for Celery integration)
            if not _has_column("scrape_jobs", "celery_task_id"):
                db.session.execute(text("ALTER TABLE scrape_jobs ADD COLUMN celery_task_id VARCHAR(64)"))
                try:
                    db.session.execute(text("CREATE INDEX ix_scrape_jobs_celery_task_id ON scrape_jobs (celery_task_id)"))
                except Exception:
                    pass  # Index might already exist
                db.session.commit()

            # schools.ai_model (модель AI для школы, выбирает супер-админ)
            if not _has_column("schools", "ai_model"):
                db.session.execute(text("ALTER TABLE schools ADD COLUMN ai_model VARCHAR(128)"))
                db.session.commit()

            # schools.allow_cross_school_reports (разрешение на создание отчётов для других школ)
            if not _has_column("schools", "allow_cross_school_reports"):
                db.session.execute(text("ALTER TABLE schools ADD COLUMN allow_cross_school_reports BOOLEAN NOT NULL DEFAULT 0"))
                db.session.commit()

            # ---- Backfill local sequences (best-effort) ----
            # Teacher sequence: per school, sequential 1..N (only fills NULLs).
            for school in School.query.order_by(School.id.asc()).all():
                teachers = (
                    User.query.filter_by(role=Role.TEACHER.value, school_id=school.id)
                    .order_by(User.id.asc())
                    .all()
                )
                existing = [t.fs_teacher_seq for t in teachers if t.fs_teacher_seq is not None]
                next_seq = (max(existing) if existing else 0) + 1
                changed = False
                for t in teachers:
                    if t.fs_teacher_seq is None:
                        t.fs_teacher_seq = next_seq
                        next_seq += 1
                        changed = True
                if changed:
                    db.session.commit()

            # Job sequence: per (school_id, teacher_id), sequential 1..N (only fills NULLs).
            for school in School.query.order_by(School.id.asc()).all():
                teachers = (
                    User.query.filter_by(role=Role.TEACHER.value, school_id=school.id)
                    .order_by(User.id.asc())
                    .all()
                )
                for t in teachers:
                    jobs = (
                        ScrapeJob.query.filter_by(school_id=school.id, teacher_id=t.id)
                        .order_by(ScrapeJob.id.asc())
                        .all()
                    )
                    existing = [j.fs_job_seq for j in jobs if j.fs_job_seq is not None]
                    next_seq = (max(existing) if existing else 0) + 1
                    changed = False
                    for j in jobs:
                        if j.fs_job_seq is None:
                            j.fs_job_seq = next_seq
                            next_seq += 1
                            changed = True
                    if changed:
                        db.session.commit()

        except Exception as e:
            # Don't break app startup for best-effort migration/backfill.
            try:
                app.logger.warning(f"Schema upgrade/backfill skipped due to error: {e}")
            except Exception:
                pass

        # Auto-create superadmin on first run (if none exists).
        existing = User.query.filter_by(role=Role.SUPERADMIN.value).first()
        if not existing:
            # Try env first, fallback to defaults.
            su = app.config.get("BOOTSTRAP_SUPERADMIN_USER") or "admin"
            sp = app.config.get("BOOTSTRAP_SUPERADMIN_PASS") or "admin123"
            u = User(username=su, full_name=su, role=Role.SUPERADMIN.value, school_id=None, is_active=True)
            u.set_password(sp)
            db.session.add(u)
            db.session.commit()
            print(f"[Bootstrap] SuperAdmin created: username={su}, password={sp} (change it after first login)")

        # ---- Auto-recover reports for interrupted jobs ----
        # Flask watchdog can restart the app mid-job, killing the background thread.
        # This recovers reports from jobs that have output_dir with files but status=running.
        _recover_interrupted_jobs(app)

    # Initialize Celery (if configured)
    global celery_app
    if app.config.get("USE_CELERY"):
        try:
            from .celery_app import init_celery
            celery_app = init_celery(app)
            app.logger.info("Celery initialized for async tasks")
        except Exception as e:
            app.logger.warning(f"Celery initialization failed: {e}. Using thread-based jobs.")

    return app


def _parse_class_subject(stem: str) -> tuple[str, str]:
    """Parse class and subject from filename stem."""
    s = (stem or "").strip()
    if "»" in s and "«" in s:
        i = s.find("»")
        if i != -1:
            class_name = s[: i + 1].strip()
            subject = s[i + 1 :].strip()
            return class_name, subject
    parts = s.split()
    if len(parts) <= 1:
        return s, ""
    return parts[0], " ".join(parts[1:]).strip()


def _recover_interrupted_jobs(app):
    """Recover reports from jobs interrupted by app restart."""
    try:
        # Find jobs that are still "running" but have output directories with reports
        running_jobs = ScrapeJob.query.filter_by(status=ScrapeJobStatus.RUNNING.value).all()
        
        for job in running_jobs:
            if not job.output_dir:
                continue
            
            output_dir = Path(job.output_dir)
            reports_dir = output_dir / "reports"
            
            if not reports_dir.exists():
                continue
            
            # Check if there are any report files
            report_files = list(reports_dir.glob("*.xlsx")) + list(reports_dir.glob("*.docx"))
            if not report_files:
                continue
            
            app.logger.info(f"[Recovery] Found interrupted job {job.id} with {len(report_files)} files in {reports_dir}")
            
            # Collect and save reports
            by_stem: dict[str, dict[str, Path]] = {}
            for p in reports_dir.glob("*"):
                if p.suffix.lower() not in {".xlsx", ".docx"}:
                    continue
                by_stem.setdefault(p.stem, {})[p.suffix.lower()] = p
            
            created = 0
            updated = 0
            
            for stem, d in sorted(by_stem.items()):
                class_name, subject = _parse_class_subject(stem)
                xlsx = d.get(".xlsx")
                docx = d.get(".docx")
                
                excel_abs = str(xlsx.resolve()) if xlsx and xlsx.exists() else None
                word_abs = str(docx.resolve()) if docx and docx.exists() else None
                
                # Check if report already exists
                existing = ReportFile.query.filter_by(
                    teacher_id=job.teacher_id,
                    class_name=class_name,
                    subject=subject,
                    period_code=job.period_code
                ).first()
                
                if existing:
                    if excel_abs:
                        existing.excel_path = excel_abs
                    if word_abs:
                        existing.word_path = word_abs
                    updated += 1
                else:
                    rf = ReportFile(
                        school_id=job.school_id,
                        teacher_id=job.teacher_id,
                        period_code=job.period_code,
                        class_name=class_name,
                        subject=subject,
                        excel_path=excel_abs,
                        word_path=word_abs,
                    )
                    db.session.add(rf)
                    created += 1
            
            # Mark job as succeeded
            from datetime import datetime
            job.status = ScrapeJobStatus.SUCCEEDED.value
            job.finished_at = datetime.utcnow()
            job.progress_percent = 100
            job.progress_message = f"[Восстановлено] Создано: {created}, обновлено: {updated}"
            
            db.session.commit()
            app.logger.info(f"[Recovery] Job {job.id} recovered: created={created}, updated={updated}")
            
    except Exception as e:
        app.logger.warning(f"[Recovery] Error during job recovery: {e}")

