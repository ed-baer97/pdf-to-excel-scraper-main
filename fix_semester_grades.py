"""
Миграционный скрипт: удаление некорректных записей quarter 1/3
для полугодовых предметов.

Проблема:
    Некоторые пользователи запустили скрапинг до того, как была добавлена
    логика определения полугодовых предметов. В результате в БД попали
    записи GradeReport с period_type="quarter", period_number=1 или 3
    для предметов, которые на самом деле оцениваются за полугодие.
    Это приводит к заниженным/некорректным оценкам.

Логика:
    1. Находим все (school_id, subject_name), которые имеют записи
       с period_type="semester" — эти предметы полугодовые.
    2. Удаляем записи с period_type="quarter", period_number in (1, 3)
       для этих предметов.

Использование:
    python fix_semester_grades.py          # просмотр (dry-run)
    python fix_semester_grades.py --apply  # применить удаление
"""
import sys
from webapp import create_app
from webapp.extensions import db
from webapp.models import GradeReport
from webapp.constants import normalize_subject_name


def main():
    """Находит и при необходимости удаляет четвертные GradeReport для полугодовых предметов (dry-run или --apply)."""
    apply = "--apply" in sys.argv

    app = create_app()
    with app.app_context():
        semester_rows = (
            db.session.query(GradeReport.school_id, GradeReport.subject_name)
            .filter_by(period_type="semester")
            .distinct()
            .all()
        )
        semester_pairs = {
            (r.school_id, normalize_subject_name(r.subject_name))
            for r in semester_rows
        }

        if not semester_pairs:
            print("Нет полугодовых предметов в БД. Нечего исправлять.")
            return

        print(f"Найдено {len(semester_pairs)} полугодовых предметов:")
        for school_id, subj in sorted(semester_pairs):
            print(f"  school_id={school_id}, предмет='{subj}'")

        bad_reports = GradeReport.query.filter(
            GradeReport.period_type == "quarter",
            GradeReport.period_number.in_([1, 3]),
        ).all()

        to_delete = [
            r for r in bad_reports
            if (r.school_id, normalize_subject_name(r.subject_name)) in semester_pairs
        ]

        if not to_delete:
            print("\nНекорректных записей не найдено. БД в порядке.")
            return

        print(f"\nНайдено {len(to_delete)} некорректных записей для удаления:")
        for r in to_delete:
            print(
                f"  id={r.id}, school={r.school_id}, class={r.class_name}, "
                f"subject='{r.subject_name}', period=quarter/{r.period_number}, "
                f"teacher_id={r.teacher_id}"
            )

        if apply:
            for r in to_delete:
                db.session.delete(r)
            db.session.commit()
            print(f"\nУдалено {len(to_delete)} записей.")
        else:
            print("\nЭто dry-run. Для применения запустите:")
            print("  python fix_semester_grades.py --apply")


if __name__ == "__main__":
    main()
