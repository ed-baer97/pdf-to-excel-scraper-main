# AGENTS.md

## Cursor Cloud specific instructions

### Overview

Mektep Platform is a Flask-based educational web application (Russian/Kazakh UI) for managing schools, teachers, and student performance reports from mektep.edu.kz. There is also a PyQt6 desktop app in `mektep-desktop/` (Windows-only, not relevant for web dev).

### Running the web application

```bash
python3 app.py
```

Runs on `http://127.0.0.1:5000` with SQLite (dev default). Auto-creates tables and a superadmin account (`admin`/`admin123`) on first run. No database setup needed — SQLite is used automatically in development.

The app uses `use_reloader=False`, so code changes require a manual restart.

### Key dev notes

- **No automated test suite** exists. Validate changes via manual testing against the running Flask app.
- **Lint**: `flake8 webapp/ app.py --max-line-length=120` (the codebase has pre-existing lint warnings — focus on new code).
- **Database**: SQLite file at `instance/mektep_platform.db`. Delete it to reset to a fresh state.
- **Roles**: SuperAdmin → School Admin → Teacher (hierarchical access control).
- **No Redis/Celery needed** for development — `USE_CELERY=0` by default, thread-based job processing is used.
- **`.env`** file: copy from `env.example`. Only `FLASK_ENV=development` matters for dev; all other defaults work out of the box.
- **Seed test data**: `python3 seed_test_data.py` (requires a school and teachers to exist first).
