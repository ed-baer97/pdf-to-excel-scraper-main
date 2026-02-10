"""Script to create mektep-desktop directory structure"""
import os
from pathlib import Path

# Base directory
base_dir = Path(__file__).parent / "mektep-desktop"

# Create directories
directories = [
    "app",
    "scraper",
    "generators",
    "ai",
    "resources/templates",
    "resources/icons",
]

for dir_path in directories:
    (base_dir / dir_path).mkdir(parents=True, exist_ok=True)
    print(f"Created: {dir_path}")

# Create __init__.py files
init_dirs = ["app", "scraper", "generators", "ai"]
for dir_name in init_dirs:
    init_file = base_dir / dir_name / "__init__.py"
    init_file.write_text("", encoding="utf-8")
    print(f"Created: {dir_name}/__init__.py")

print("\nDirectory structure created successfully!")
