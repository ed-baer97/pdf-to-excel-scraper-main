"""Учитель в нескольких школах: членство, fs_teacher_seq, проверки доступа."""

from __future__ import annotations

from sqlalchemy import func

from ..extensions import db
from ..models import Role, School, Subject, TeacherSchool, User


def org_names_match(scraped_name: str, school_name: str) -> bool:
    """Нечёткое сравнение названий организаций (регистр, пробелы, вхождение)."""
    a = " ".join((scraped_name or "").lower().split()).strip()
    b = " ".join((school_name or "").lower().split()).strip()
    if not a or not b:
        return False
    if a == b:
        return True
    return a in b or b in a


def teachers_for_school(school_id: int) -> list[User]:
    """Все учителя, привязанные к школе (включая добавленных по ИИН)."""
    return (
        User.query.join(TeacherSchool, TeacherSchool.teacher_id == User.id)
        .filter(
            TeacherSchool.school_id == school_id,
            User.role == Role.TEACHER.value,
        )
        .all()
    )


def teachers_count_for_school(school_id: int) -> int:
    return (
        db.session.query(func.count(TeacherSchool.id))
        .join(User, User.id == TeacherSchool.teacher_id)
        .filter(
            TeacherSchool.school_id == school_id,
            User.role == Role.TEACHER.value,
        )
        .scalar()
        or 0
    )


def teacher_in_school(teacher_id: int, school_id: int) -> bool:
    return (
        TeacherSchool.query.filter_by(
            teacher_id=teacher_id,
            school_id=school_id,
        ).first()
        is not None
    )


def find_teacher_by_iin(iin_norm: str) -> User | None:
    if not iin_norm:
        return None
    return User.query.filter_by(role=Role.TEACHER.value, iin=iin_norm).first()


def iin_taken_in_school(
    school_id: int,
    iin_norm: str,
    exclude_teacher_id: int | None = None,
) -> bool:
    q = (
        db.session.query(TeacherSchool)
        .join(User, User.id == TeacherSchool.teacher_id)
        .filter(
            TeacherSchool.school_id == school_id,
            User.role == Role.TEACHER.value,
            User.iin == iin_norm,
        )
    )
    if exclude_teacher_id is not None:
        q = q.filter(User.id != exclude_teacher_id)
    return q.first() is not None


def next_fs_teacher_seq(school_id: int) -> int:
    max_seq = (
        db.session.query(func.max(TeacherSchool.fs_teacher_seq))
        .filter(TeacherSchool.school_id == school_id)
        .scalar()
    )
    return int(max_seq or 0) + 1


def ensure_membership(teacher: User, school_id: int) -> TeacherSchool:
    """Создаёт связь учитель–школа, если её ещё нет."""
    existing = TeacherSchool.query.filter_by(
        teacher_id=teacher.id,
        school_id=school_id,
    ).first()
    if existing:
        return existing

    membership = TeacherSchool(
        teacher_id=teacher.id,
        school_id=school_id,
        fs_teacher_seq=next_fs_teacher_seq(school_id),
    )
    db.session.add(membership)

    if teacher.fs_teacher_seq is None and teacher.school_id == school_id:
        teacher.fs_teacher_seq = membership.fs_teacher_seq

    return membership


def get_fs_teacher_seq(teacher_id: int, school_id: int) -> int | None:
    row = TeacherSchool.query.filter_by(
        teacher_id=teacher_id,
        school_id=school_id,
    ).first()
    return row.fs_teacher_seq if row else None


def get_teacher_schools(teacher_id: int) -> list[School]:
    return (
        School.query.join(TeacherSchool, TeacherSchool.school_id == School.id)
        .filter(TeacherSchool.teacher_id == teacher_id)
        .order_by(School.id.asc())
        .all()
    )


def get_allowed_school_names(teacher_id: int) -> list[str]:
    return [s.name for s in get_teacher_schools(teacher_id) if s.name]


def teacher_has_cross_school_allowed(teacher_id: int) -> bool:
    return any(s.allow_cross_school_reports for s in get_teacher_schools(teacher_id))


def teacher_can_report_for_org(teacher_id: int, scraped_org_name: str) -> bool:
    """Можно ли загружать отчёт с данной организации mektep.edu.kz."""
    if not scraped_org_name:
        return False
    if teacher_has_cross_school_allowed(teacher_id):
        return True
    for school in get_teacher_schools(teacher_id):
        if org_names_match(scraped_org_name, school.name):
            return True
    return False


def teacher_can_report_for_school_id(teacher_id: int, target_school_id: int) -> bool:
    if teacher_in_school(teacher_id, target_school_id):
        return True
    return teacher_has_cross_school_allowed(teacher_id)


def backfill_memberships_from_users() -> int:
    """Переносит существующих учителей (users.school_id) в teacher_schools."""
    created = 0
    teachers = (
        User.query.filter_by(role=Role.TEACHER.value)
        .filter(User.school_id.isnot(None))
        .order_by(User.id.asc())
        .all()
    )
    for teacher in teachers:
        before = TeacherSchool.query.filter_by(
            teacher_id=teacher.id,
            school_id=teacher.school_id,
        ).count()
        if before:
            continue
        seq = teacher.fs_teacher_seq or next_fs_teacher_seq(teacher.school_id)
        db.session.add(
            TeacherSchool(
                teacher_id=teacher.id,
                school_id=teacher.school_id,
                fs_teacher_seq=seq,
            )
        )
        if teacher.fs_teacher_seq is None:
            teacher.fs_teacher_seq = seq
        created += 1
    if created:
        db.session.commit()
    return created


def remove_teacher_from_school(teacher_id: int, school_id: int) -> None:
    """Удаляет учителя из школы: членство и данные, привязанные к этой школе."""
    from ..models import (
        Class,
        GradeReport,
        ReportFile,
        TeacherClass,
        TeacherSubject,
    )

    school_subject_ids = [
        sid
        for (sid,) in Subject.query.filter_by(school_id=school_id)
        .with_entities(Subject.id)
        .all()
    ]

    teacher_subjects = TeacherSubject.query.filter(
        TeacherSubject.teacher_id == teacher_id,
        TeacherSubject.subject_id.in_(school_subject_ids),
    ).all()
    for ts in teacher_subjects:
        TeacherClass.query.filter_by(teacher_subject_id=ts.id).delete()
    TeacherSubject.query.filter(
        TeacherSubject.teacher_id == teacher_id,
        TeacherSubject.subject_id.in_(school_subject_ids),
    ).delete(synchronize_session=False)

    Class.query.filter_by(
        school_id=school_id,
        class_teacher_id=teacher_id,
    ).update({"class_teacher_id": None})

    GradeReport.query.filter_by(teacher_id=teacher_id, school_id=school_id).delete()
    ReportFile.query.filter_by(teacher_id=teacher_id, school_id=school_id).delete()

    TeacherSchool.query.filter_by(
        teacher_id=teacher_id,
        school_id=school_id,
    ).delete()
