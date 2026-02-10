import argparse
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description="Reset local SQLite platform DB (instance/mektep_platform.db).")
    p.add_argument("--yes", action="store_true", help="Do not ask for confirmation")
    p.add_argument("--path", default="instance/mektep_platform.db", help="DB path to delete")
    args = p.parse_args()

    db_path = Path(args.path)
    if not db_path.exists():
        print(f"DB not found: {db_path}")
        return 0

    if not args.yes:
        ans = input(f"Delete DB file '{db_path}'? [y/N]: ").strip().lower()
        if ans not in {"y", "yes"}:
            print("Cancelled.")
            return 1

    db_path.unlink(missing_ok=True)
    # Also remove any migration versions if present
    migrations_dir = Path("migrations")
    if migrations_dir.exists():
        versions_dir = migrations_dir / "versions"
        if versions_dir.exists():
            for f in versions_dir.glob("*.py"):
                f.unlink(missing_ok=True)
            print(f"Cleaned: {versions_dir}")
    print(f"Deleted: {db_path}")
    print("Restart the app to recreate DB with default superadmin (admin/admin123)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

