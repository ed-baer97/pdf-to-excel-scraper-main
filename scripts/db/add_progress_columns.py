"""Скрипт добавления колонок прогресса в таблицу scrape_jobs (SQLite ALTER TABLE)."""
from sqlalchemy import text

from webapp import create_app
from webapp.extensions import db


def main() -> None:
    """Проверяет PRAGMA table_info и добавляет недостающие колонки прогресса в scrape_jobs."""
    app = create_app()

    with app.app_context():
        print("Checking and adding progress tracking columns to scrape_jobs table...")

        columns_to_add = [
            ("progress_percent", "INTEGER DEFAULT 0"),
            ("progress_message", "VARCHAR(255)"),
            ("total_reports", "INTEGER"),
            ("processed_reports", "INTEGER DEFAULT 0"),
        ]

        for col_name, col_type in columns_to_add:
            try:
                result = db.session.execute(text("PRAGMA table_info(scrape_jobs)")).fetchall()
                existing_columns = [row[1] for row in result]

                if col_name in existing_columns:
                    print(f"  ✓ Column '{col_name}' already exists")
                else:
                    db.session.execute(
                        text(f"ALTER TABLE scrape_jobs ADD COLUMN {col_name} {col_type}")
                    )
                    print(f"  ✓ Added column '{col_name}'")
            except Exception:
                try:
                    db.session.execute(
                        text(f"ALTER TABLE scrape_jobs ADD COLUMN {col_name} {col_type}")
                    )
                    db.session.commit()
                    print(f"  ✓ Added column '{col_name}'")
                except Exception as e2:
                    print(f"  ✗ Failed to add '{col_name}': {e2}")

        try:
            db.session.commit()
            print("\n✓ Database update completed!")
            print("You can now use the application with progress tracking.")
        except Exception as e:
            print(f"\n✗ Error committing changes: {e}")
            db.session.rollback()


if __name__ == "__main__":
    main()

