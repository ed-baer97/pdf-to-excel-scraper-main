"""Скрипт добавления колонки academic_year в grade_reports и report_files."""

from sqlalchemy import inspect, text

from webapp import create_app
from webapp.extensions import db
from webapp.services.academic_year import DEFAULT_BACKFILL_ACADEMIC_YEAR


def _has_column(inspector, table: str, col: str) -> bool:
    try:
        columns = [c["name"] for c in inspector.get_columns(table)]
        return col in columns
    except Exception:
        return False


def _migrate_table(table: str, inspector) -> None:
    if _has_column(inspector, table, "academic_year"):
        print(f"  ✓ Column academic_year already exists on {table}")
        return
    db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN academic_year SMALLINT"))
    db.session.commit()
    db.session.execute(
        text(f"UPDATE {table} SET academic_year = :yr WHERE academic_year IS NULL"),
        {"yr": DEFAULT_BACKFILL_ACADEMIC_YEAR},
    )
    db.session.commit()
    print(f"  ✓ Added academic_year to {table} (backfill={DEFAULT_BACKFILL_ACADEMIC_YEAR})")


def main() -> None:
    app = create_app()
    with app.app_context():
        print("Migrating academic_year column...")
        inspector = inspect(db.engine)
        for table in ("grade_reports", "report_files"):
            try:
                _migrate_table(table, inspector)
            except Exception as exc:
                print(f"  ✗ {table}: {exc}")
                db.session.rollback()

        try:
            db.session.execute(
                text("DROP INDEX IF EXISTS uq_grade_report_teacher_class_subject_period")
            )
            db.session.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_grade_report_teacher_class_subject_period "
                    "ON grade_reports (teacher_id, school_id, class_name, subject_name, "
                    "period_type, period_number, academic_year)"
                )
            )
            db.session.execute(text("DROP INDEX IF EXISTS ix_grade_report_school_period"))
            db.session.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_grade_report_school_period "
                    "ON grade_reports (school_id, period_type, period_number, academic_year)"
                )
            )
            db.session.commit()
            print("  ✓ Recreated grade_reports indexes with academic_year")
        except Exception as exc:
            print(f"  ✗ Index migration: {exc}")
            db.session.rollback()

        print("\n✓ academic_year migration completed.")


if __name__ == "__main__":
    main()
