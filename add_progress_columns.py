"""Script to add progress tracking columns to ScrapeJob table."""
from webapp import create_app
from webapp.extensions import db
from sqlalchemy import text

app = create_app()

with app.app_context():
    print("Checking and adding progress tracking columns to scrape_jobs table...")
    
    # SQLite compatible ALTER TABLE statements
    columns_to_add = [
        ("progress_percent", "INTEGER DEFAULT 0"),
        ("progress_message", "VARCHAR(255)"),
        ("total_reports", "INTEGER"),
        ("processed_reports", "INTEGER DEFAULT 0"),
    ]
    
    for col_name, col_type in columns_to_add:
        try:
            # Check if column exists by querying table info
            result = db.session.execute(
                text(f"PRAGMA table_info(scrape_jobs)")
            ).fetchall()
            existing_columns = [row[1] for row in result]
            
            if col_name in existing_columns:
                print(f"  ✓ Column '{col_name}' already exists")
            else:
                # Add column
                db.session.execute(
                    text(f"ALTER TABLE scrape_jobs ADD COLUMN {col_name} {col_type}")
                )
                print(f"  ✓ Added column '{col_name}'")
        except Exception as e:
            # Try alternative method for other databases
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
