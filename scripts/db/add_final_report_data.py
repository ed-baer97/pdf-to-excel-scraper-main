"""Создание таблицы final_report_data для ручных данных итогового отчёта."""

from sqlalchemy import inspect, text

from webapp import create_app
from webapp.extensions import db


def main() -> None:
    app = create_app()
    with app.app_context():
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        if "final_report_data" in tables:
            print("  ✓ Table final_report_data already exists")
            return

        db.create_all()
        print("  ✓ Created final_report_data table (via create_all)")
        print("\n✓ final_report_data migration completed.")


if __name__ == "__main__":
    main()
