"""Бэкфилл агрегатных колонок GradeReport из grades_json.

Колонки (quality_percent, success_percent, total_students, count_5..count_2)
добавляются автоматически при старте приложения; этот скрипт заполняет их
для уже существующих строк. Повторный запуск безопасен (идемпотентен).

Запуск из корня репозитория:
    python -m scripts.db.backfill_grade_aggregates            # только пустые
    python -m scripts.db.backfill_grade_aggregates --force    # пересчитать все
"""
from __future__ import annotations

import argparse

from webapp import create_app
from webapp.extensions import db
from webapp.models import GradeReport
from webapp.services.grade_reports.aggregates import apply_grade_aggregates

BATCH_SIZE = 500


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Пересчитать агрегаты для всех строк, а не только для пустых",
    )
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        id_query = db.session.query(GradeReport.id)
        if not args.force:
            id_query = id_query.filter(GradeReport.total_students.is_(None))
        report_ids = [row[0] for row in id_query.order_by(GradeReport.id).all()]
        total = len(report_ids)
        print(f"Rows to backfill: {total}")

        processed = 0
        for start in range(0, total, BATCH_SIZE):
            chunk_ids = report_ids[start : start + BATCH_SIZE]
            reports = (
                GradeReport.query.filter(GradeReport.id.in_(chunk_ids)).all()
            )
            for report in reports:
                apply_grade_aggregates(report)
            db.session.commit()
            processed += len(reports)
            print(f"  processed {processed}/{total}")

        print("Done.")


if __name__ == "__main__":
    main()
