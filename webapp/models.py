from __future__ import annotations

from datetime import datetime
from enum import Enum

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


class Role(str, Enum):
    SUPERADMIN = "superadmin"
    SCHOOL_ADMIN = "school_admin"
    TEACHER = "teacher"


class School(db.Model):
    __tablename__ = "schools"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False, unique=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    # AI API ключ для генерации анализа (Qwen/DashScope)
    ai_api_key = db.Column(db.String(512), nullable=True)
    # Модель AI для генерации (выбирает супер-админ, напр. qwen-flash-character, qwen-plus)
    ai_model = db.Column(db.String(128), nullable=True)
    # Разрешить создание отчётов для других школ (защита от распространения аккаунта)
    # False = только своя организация, True = любая организация
    allow_cross_school_reports = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    users = db.relationship("User", back_populates="school")


class User(db.Model, UserMixin):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=True)
    # Local, per-school sequential number used ONLY for filesystem paths:
    # out/platform_uploads/school_{school_id}/teacher_{fs_teacher_seq}/...
    # This is intentionally NOT the same as global user.id.
    fs_teacher_seq = db.Column(db.Integer, nullable=True, index=True)
    role = db.Column(db.String(32), nullable=False, default=Role.TEACHER.value)
    username = db.Column(db.String(120), nullable=False, unique=True)
    # Some older DBs in this repo already have full_name as NOT NULL.
    # Keep it required in the model, but we auto-fill it when creating users.
    full_name = db.Column(db.String(255), nullable=False, default="")
    password_hash = db.Column(db.String(255), nullable=False)
    # For “admin can see password” requirement: store encrypted initial password.
    password_enc = db.Column(db.LargeBinary, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    school = db.relationship("School", back_populates="users")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class ReportFile(db.Model):
    __tablename__ = "report_files"
    
    # Composite indexes for common queries
    __table_args__ = (
        # For finding reports by teacher and period (dashboard query)
        db.Index("ix_report_files_teacher_period", "teacher_id", "period_code"),
        # For checking duplicates when saving reports
        db.Index("ix_report_files_teacher_class_subject_period", 
                 "teacher_id", "class_name", "subject", "period_code"),
    )

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    period_code = db.Column(db.String(16), nullable=False, index=True)
    class_name = db.Column(db.String(64), nullable=False)
    subject = db.Column(db.String(255), nullable=False)
    excel_path = db.Column(db.String(1024), nullable=True)
    word_path = db.Column(db.String(1024), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class ScrapeJobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ScrapeJob(db.Model):
    __tablename__ = "scrape_jobs"
    
    # Composite indexes for common queries
    __table_args__ = (
        # For getting jobs by teacher (dashboard query)
        db.Index("ix_scrape_jobs_teacher_created", "teacher_id", "created_at"),
        # For finding running jobs (recovery, stats)
        db.Index("ix_scrape_jobs_status", "status"),
        # For fs_job_seq generation
        db.Index("ix_scrape_jobs_school_teacher", "school_id", "teacher_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    # Local, per-(school_id, teacher_id) sequential number for filesystem paths:
    # out/platform_uploads/school_{school_id}/teacher_{fs_teacher_seq}/job_{fs_job_seq}/...
    # This is intentionally NOT the same as global job.id.
    fs_job_seq = db.Column(db.Integer, nullable=True, index=True)
    period_code = db.Column(db.String(16), nullable=False)
    lang = db.Column(db.String(8), nullable=False, default="ru")
    status = db.Column(db.String(16), nullable=False, default=ScrapeJobStatus.QUEUED.value)
    output_dir = db.Column(db.String(1024), nullable=True)
    error = db.Column(db.Text, nullable=True)
    progress_percent = db.Column(db.Integer, nullable=True, default=0)  # 0-100
    progress_message = db.Column(db.String(255), nullable=True)  # Текущее сообщение о прогрессе
    total_reports = db.Column(db.Integer, nullable=True)  # Общее количество отчетов для обработки
    processed_reports = db.Column(db.Integer, nullable=True, default=0)  # Обработано отчетов
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    started_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)
    
    # Celery task ID (for async job tracking)
    celery_task_id = db.Column(db.String(64), nullable=True, index=True)


# =============================================================================
# Модели для веб-панели админа и сводных таблиц
# =============================================================================

class Class(db.Model):
    """Модель класса школы"""
    __tablename__ = "classes"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    name = db.Column(db.String(50), nullable=False)  # Например: "5Е", "8Б"
    # Классный руководитель
    class_teacher_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # Уникальность: имя класса в пределах школы
    __table_args__ = (
        db.UniqueConstraint("school_id", "name", name="uq_class_school_name"),
    )

    # Связи
    school = db.relationship("School", backref="classes")
    class_teacher = db.relationship("User", foreign_keys=[class_teacher_id], backref="managed_classes")

    def __repr__(self):
        return f"<Class {self.name}>"


class Subject(db.Model):
    """Модель предмета школы"""
    __tablename__ = "subjects"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)  # Например: "Математика", "Физика"
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # Уникальность: имя предмета в пределах школы
    __table_args__ = (
        db.UniqueConstraint("school_id", "name", name="uq_subject_school_name"),
    )

    # Связи
    school = db.relationship("School", backref="subjects")

    def __repr__(self):
        return f"<Subject {self.name}>"


class TeacherSubject(db.Model):
    """Связь учитель-предмет"""
    __tablename__ = "teacher_subjects"

    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # Уникальность: учитель-предмет
    __table_args__ = (
        db.UniqueConstraint("teacher_id", "subject_id", name="uq_teacher_subject"),
    )

    # Связи
    teacher = db.relationship("User", backref="teacher_subjects")
    subject = db.relationship("Subject", backref="teacher_subjects")

    def __repr__(self):
        return f"<TeacherSubject {self.teacher_id}-{self.subject_id}>"


class TeacherClass(db.Model):
    """Связь учитель-предмет-класс (для подгрупп)"""
    __tablename__ = "teacher_classes"

    id = db.Column(db.Integer, primary_key=True)
    teacher_subject_id = db.Column(db.Integer, db.ForeignKey("teacher_subjects.id"), nullable=False, index=True)
    class_id = db.Column(db.Integer, db.ForeignKey("classes.id"), nullable=False, index=True)
    # Номер подгруппы (1 или 2), если класс разделен на подгруппы; NULL = весь класс
    subgroup = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # Связи
    teacher_subject = db.relationship("TeacherSubject", backref="teacher_classes")
    class_obj = db.relationship("Class", backref="teacher_classes")

    def __repr__(self):
        return f"<TeacherClass {self.teacher_subject_id}-{self.class_id}>"


class GradeReport(db.Model):
    """
    Хранение JSON данных оценок.
    
    Учитель загружает данные после скрапинга:
    - grades_json: список учеников с оценками
    - analytics_json: статистика СОР/СОЧ
    
    При повторной загрузке того же класса/предмета/периода - перезаписывается.
    При объединении подгрупп - данные агрегируются по class_name + subject_name + period.
    """
    __tablename__ = "grade_reports"

    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    class_name = db.Column(db.String(64), nullable=False)  # "7А"
    subject_name = db.Column(db.String(255), nullable=False)  # "Математика"
    period_type = db.Column(db.String(20), nullable=False)  # "quarter" или "semester"
    period_number = db.Column(db.Integer, nullable=False)  # 1-4 для четверти, 1-2 для полугодия
    
    # JSON данные оценок
    # Формат grades_json:
    # {
    #   "students": [{"name": "ФИО", "percent": 85.5, "grade": 4}, ...],
    #   "quality_percent": 66.7,
    #   "success_percent": 100.0,
    #   "total_students": 25
    # }
    grades_json = db.Column(db.Text, nullable=True)
    
    # JSON данные аналитики СОР/СОЧ
    # Формат analytics_json:
    # {
    #   "sor": [{"name": "СОр 1", "count_5": 5, "count_4": 8, ...}, ...],
    #   "soch": {"count_5": 6, "count_4": 9, ...}
    # }
    analytics_json = db.Column(db.Text, nullable=True)
    
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Уникальность: один отчёт на учителя/класс/предмет/период
    __table_args__ = (
        db.UniqueConstraint(
            "teacher_id", "school_id", "class_name", "subject_name", "period_type", "period_number",
            name="uq_grade_report_teacher_class_subject_period"
        ),
        db.Index("ix_grade_report_school_class_subject", "school_id", "class_name", "subject_name"),
    )

    # Связи
    teacher = db.relationship("User", backref="grade_reports")
    school = db.relationship("School", backref="grade_reports")

    def __repr__(self):
        return f"<GradeReport {self.class_name} {self.subject_name} {self.period_type}/{self.period_number}>"

