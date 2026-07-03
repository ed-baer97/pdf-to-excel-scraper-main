import sys
from pathlib import Path

# Корень репозитория в sys.path — для импорта iin_utils из корня.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from flask import Flask, g, request, session

from .config import get_config
from .extensions import db, login_manager, migrate
from .models import ReportFile, Role, School, ScrapeJob, ScrapeJobStatus, User
from .services.academic_year import (
    DEFAULT_BACKFILL_ACADEMIC_YEAR,
    available_academic_years,
    current_academic_year,
    format_academic_year,
    resolve_academic_year,
)
from .translator import gettext as custom_gettext

# Celery app (initialized lazily)
celery_app = None


def create_app(config_object=None) -> Flask:
    """
    Фабрика Flask-приложения: конфигурация, БД, логин, blueprints, лёгкие миграции, восстановление задач.

    Args:
        config_object: класс конфигурации; если None — выбирается по FLASK_ENV.
    """
    if config_object is None:
        config_object = get_config()

    from .config import ProductionConfig

    if config_object is ProductionConfig:
        ProductionConfig.validate()
    
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_object(config_object)

    from .logging_config import configure_logging, init_sentry
    from .request_logging import register_error_handlers, register_request_logging
    from .slow_sql import register_slow_sql_logging

    configure_logging(app)
    init_sentry(app)

    # Prometheus metrics (internal /metrics endpoint)
    try:
        from prometheus_flask_exporter import PrometheusMetrics
        PrometheusMetrics(app)
    except ImportError:
        pass  # prometheus-flask-exporter not installed

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    # SQLite (dev): WAL позволяет читать во время записи — убирает
    # "database is locked" при параллельных фоновых потоках/задачах.
    if (app.config.get("SQLALCHEMY_DATABASE_URI") or "").startswith("sqlite"):
        from sqlalchemy import event

        with app.app_context():
            engine = db.engine

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA busy_timeout=5000")
            finally:
                cursor.close()

    register_request_logging(app)
    register_error_handlers(app)
    register_slow_sql_logging(app)

    def get_locale():
        """Возвращает код текущей локали из сессии (по умолчанию ru)."""
        return session.get('language', 'ru')
    
    # Добавляем get_locale и gettext в контекст шаблонов
    @app.context_processor
    def inject_locale():
        """Прокидывает в шаблоны get_locale и функцию перевода _()."""
        current_lang = get_locale()
        school_id = None
        try:
            from flask_login import current_user

            if current_user.is_authenticated and getattr(current_user, "school_id", None):
                school_id = current_user.school_id
        except Exception:
            pass
        active_year = resolve_academic_year()
        return dict(
            get_locale=lambda: current_lang,
            _=lambda key: custom_gettext(key, current_lang),
            active_academic_year=active_year,
            current_academic_year_value=current_academic_year(),
            format_academic_year=format_academic_year,
            available_academic_years=available_academic_years(school_id),
            is_archive_academic_year=active_year != current_academic_year(),
        )

    @app.before_request
    def _set_academic_year_context():
        """Сохраняет выбранный учебный год в session и g."""
        explicit = request.args.get("academic_year")
        if explicit is not None and str(explicit).strip() != "":
            try:
                year = int(explicit)
                session["academic_year"] = year
                g.active_academic_year = year
                return
            except (TypeError, ValueError):
                pass
        if "academic_year" in session:
            g.active_academic_year = int(session["academic_year"])
        else:
            g.active_academic_year = current_academic_year()

    @login_manager.user_loader
    def load_user(user_id: str):
        """Загружает пользователя по id для Flask-Login."""
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
    from .cli import clear_cache, create_superadmin

    app.cli.add_command(create_superadmin)
    app.cli.add_command(clear_cache)

    # Lightweight “no-terminal” bootstrap for dev: create tables if missing.
    with app.app_context():
        db.create_all()

        try:
            from .services.year_grades import purge_legacy_year_reports

            removed = purge_legacy_year_reports()
            if removed:
                app.logger.info(
                    "Removed %s legacy year period grade/report file rows", removed
                )
        except Exception as e:
            try:
                db.session.rollback()
            except Exception:
                pass
            app.logger.warning("purge_legacy_year_reports skipped: %s", e)

        # ---- Lightweight runtime schema upgrades (SQLite + PostgreSQL compatible) ----
        # This repo historically used db.create_all() without proper migrations.
        # We keep it robust by adding new columns/indexes when missing.
        try:
            from sqlalchemy import text, inspect
            
            inspector = inspect(db.engine)
            
            def _has_column(table: str, col: str) -> bool:
                """Проверяет наличие колонки в таблице (SQLite и PostgreSQL)."""
                try:
                    columns = [c["name"] for c in inspector.get_columns(table)]
                    return col in columns
                except Exception:
                    return False

            def _create_index_if_missing(index_name: str, ddl: str) -> None:
                """Create an index without leaving the main session in aborted state."""
                try:
                    db.session.execute(text(ddl))
                    db.session.commit()
                except Exception:
                    db.session.rollback()

            # users.iin (ИИН для mektep.edu.kz)
            if not _has_column("users", "iin"):
                db.session.execute(text("ALTER TABLE users ADD COLUMN iin VARCHAR(12)"))
                db.session.commit()
                _create_index_if_missing("ix_users_iin", "CREATE INDEX ix_users_iin ON users (iin)")

            # users.fs_teacher_seq
            if not _has_column("users", "fs_teacher_seq"):
                db.session.execute(text("ALTER TABLE users ADD COLUMN fs_teacher_seq INTEGER"))
                db.session.commit()
                _create_index_if_missing(
                    "ix_users_fs_teacher_seq",
                    "CREATE INDEX ix_users_fs_teacher_seq ON users (fs_teacher_seq)",
                )

            # scrape_jobs.fs_job_seq
            if not _has_column("scrape_jobs", "fs_job_seq"):
                db.session.execute(text("ALTER TABLE scrape_jobs ADD COLUMN fs_job_seq INTEGER"))
                db.session.commit()
                _create_index_if_missing(
                    "ix_scrape_jobs_fs_job_seq",
                    "CREATE INDEX ix_scrape_jobs_fs_job_seq ON scrape_jobs (fs_job_seq)",
                )

            # scrape_jobs.celery_task_id (for Celery integration)
            if not _has_column("scrape_jobs", "celery_task_id"):
                db.session.execute(text("ALTER TABLE scrape_jobs ADD COLUMN celery_task_id VARCHAR(64)"))
                db.session.commit()
                _create_index_if_missing(
                    "ix_scrape_jobs_celery_task_id",
                    "CREATE INDEX ix_scrape_jobs_celery_task_id ON scrape_jobs (celery_task_id)",
                )

            # scrape_jobs.worker_pid (PID подпроцесса скрапера, виден всем воркерам)
            if not _has_column("scrape_jobs", "worker_pid"):
                db.session.execute(text("ALTER TABLE scrape_jobs ADD COLUMN worker_pid INTEGER"))
                db.session.commit()

            # scrape_jobs.cancel_requested (кооперативная отмена через БД)
            if not _has_column("scrape_jobs", "cancel_requested"):
                db.session.execute(
                    text("ALTER TABLE scrape_jobs ADD COLUMN cancel_requested BOOLEAN NOT NULL DEFAULT FALSE")
                )
                db.session.commit()

            # grade_reports.*: предрассчитанные агрегаты (denormalized из grades_json).
            # Бэкфилл существующих строк: python -m scripts.db.backfill_grade_aggregates
            for _agg_col, _agg_type in (
                ("quality_percent", "FLOAT"),
                ("success_percent", "FLOAT"),
                ("total_students", "INTEGER"),
                ("count_5", "INTEGER"),
                ("count_4", "INTEGER"),
                ("count_3", "INTEGER"),
                ("count_2", "INTEGER"),
            ):
                if not _has_column("grade_reports", _agg_col):
                    db.session.execute(
                        text(f"ALTER TABLE grade_reports ADD COLUMN {_agg_col} {_agg_type}")
                    )
                    db.session.commit()

            _create_index_if_missing(
                "ix_grade_report_school_period",
                "CREATE INDEX ix_grade_report_school_period ON grade_reports (school_id, period_type, period_number, academic_year)",
            )

            def _migrate_academic_year_column(table: str) -> None:
                if not _has_column(table, "academic_year"):
                    db.session.execute(
                        text(f"ALTER TABLE {table} ADD COLUMN academic_year SMALLINT")
                    )
                    db.session.commit()
                    db.session.execute(
                        text(
                            f"UPDATE {table} SET academic_year = :yr "
                            "WHERE academic_year IS NULL"
                        ),
                        {"yr": DEFAULT_BACKFILL_ACADEMIC_YEAR},
                    )
                    db.session.commit()
                    _create_index_if_missing(
                        f"ix_{table}_academic_year",
                        f"CREATE INDEX ix_{table}_academic_year ON {table} (academic_year)",
                    )

            _migrate_academic_year_column("grade_reports")
            _migrate_academic_year_column("report_files")

            # Пересоздать уникальный индекс grade_reports с academic_year (SQLite).
            try:
                db.session.execute(
                    text(
                        "DROP INDEX IF EXISTS uq_grade_report_teacher_class_subject_period"
                    )
                )
                db.session.commit()
            except Exception:
                db.session.rollback()
            _create_index_if_missing(
                "uq_grade_report_teacher_class_subject_period",
                "CREATE UNIQUE INDEX uq_grade_report_teacher_class_subject_period "
                "ON grade_reports (teacher_id, school_id, class_name, subject_name, "
                "period_type, period_number, academic_year)",
            )
            try:
                db.session.execute(text("DROP INDEX IF EXISTS ix_grade_report_school_period"))
                db.session.commit()
            except Exception:
                db.session.rollback()
            _create_index_if_missing(
                "ix_grade_report_school_period",
                "CREATE INDEX ix_grade_report_school_period ON grade_reports "
                "(school_id, period_type, period_number, academic_year)",
            )

            # schools.ai_model (модель AI для школы, выбирает супер-админ)
            if not _has_column("schools", "ai_model"):
                db.session.execute(text("ALTER TABLE schools ADD COLUMN ai_model VARCHAR(128)"))
                db.session.commit()

            # schools.allow_cross_school_reports (разрешение на создание отчётов для других школ)
            if not _has_column("schools", "allow_cross_school_reports"):
                db.session.execute(text("ALTER TABLE schools ADD COLUMN allow_cross_school_reports BOOLEAN NOT NULL DEFAULT 0"))
                db.session.commit()

            # schools.reports_quota_per_period (лимит отчётов на период)
            if not _has_column("schools", "reports_quota_per_period"):
                db.session.execute(
                    text("ALTER TABLE schools ADD COLUMN reports_quota_per_period INTEGER NOT NULL DEFAULT 0")
                )
                db.session.commit()

            # teacher_schools: членство учителя в нескольких школах
            try:
                tables = set(inspector.get_table_names())
            except Exception:
                tables = set()
            if "teacher_schools" not in tables:
                db.create_all()

            from .services.teacher_schools import backfill_memberships_from_users

            backfill_memberships_from_users()

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
                db.session.rollback()
            except Exception:
                pass
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
    """Разбирает имя файла без расширения на класс и предмет (по «» или по пробелам)."""
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
    """Восстанавливает ReportFile и статус задач для прерванных скрапингов после перезапуска приложения."""
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
                    period_code=job.period_code,
                    academic_year=getattr(job, "academic_year", None)
                    or current_academic_year(),
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
                        academic_year=getattr(job, "academic_year", None)
                        or current_academic_year(),
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

