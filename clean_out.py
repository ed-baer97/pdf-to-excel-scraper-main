import argparse
import shutil
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description="Clean generated outputs (out/mektep).")
    p.add_argument("--path", default="out/mektep", help="Directory to remove and recreate")
    p.add_argument("--yes", action="store_true", help="Do not ask for confirmation")
    args = p.parse_args()

    target = Path(args.path)
    if target.exists() and not args.yes:
        ans = input(f"Delete '{target}' and all its contents? [y/N]: ").strip().lower()
        if ans not in {"y", "yes"}:
            print("Cancelled.")
            return 1

    if target.exists():
        shutil.rmtree(target, ignore_errors=True)

    (target / "reports").mkdir(parents=True, exist_ok=True)
    (target / "batch").mkdir(parents=True, exist_ok=True)
    print(f"Cleaned and recreated: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

