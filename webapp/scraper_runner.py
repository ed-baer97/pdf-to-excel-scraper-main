from __future__ import annotations

import re
import subprocess
import sys
import threading
import time
import json
import shutil
from datetime import datetime
from pathlib import Path
import os
import stat

from flask import Flask

from .extensions import db
from .models import ReportFile, Role, School, ScrapeJob, ScrapeJobStatus, User

# Store running processes by job_id for cancellation
_running_processes: dict[int, subprocess.Popen] = {}
_processes_lock = threading.Lock()

# Semaphore for limiting concurrent jobs (initialized lazily)
_jobs_semaphore: threading.Semaphore | None = None
_semaphore_lock = threading.Lock()
_max_concurrent_jobs: int = 3  # Default, overridden by config


def _get_jobs_semaphore(app: Flask) -> threading.Semaphore:
    """Get or create the jobs semaphore with config-based limit."""
    global _jobs_semaphore, _max_concurrent_jobs
    with _semaphore_lock:
        max_jobs = app.config.get("MAX_CONCURRENT_JOBS", 3)
        if _jobs_semaphore is None or _max_concurrent_jobs != max_jobs:
            _max_concurrent_jobs = max_jobs
            _jobs_semaphore = threading.Semaphore(max_jobs)
            app.logger.info(f"Initialized jobs semaphore with max_concurrent_jobs={max_jobs}")
        return _jobs_semaphore


def get_active_jobs_count() -> int:
    """Get the number of currently active (running) jobs."""
    with _processes_lock:
        # Count processes that are still running
        return sum(1 for p in _running_processes.values() if p.poll() is None)


def get_max_concurrent_jobs() -> int:
    """Get the configured maximum concurrent jobs."""
    return _max_concurrent_jobs


def get_running_process(job_id: int) -> subprocess.Popen | None:
    """Get running process for a job_id, if any."""
    with _processes_lock:
        return _running_processes.get(job_id)


def _terminate_process(process: subprocess.Popen, timeout: float = 2.0) -> None:
    """Helper function to terminate a process with timeout."""
    try:
        if sys.platform == "win32":
            process.terminate()
        else:
            process.terminate()
        time.sleep(timeout)
        if process.poll() is None:
            process.kill()
    except Exception:
        pass  # Best effort termination


def _resolve_upload_root(app: Flask) -> Path:
    """
    Resolve UPLOAD_ROOT to an absolute path.
    If configured as relative (default: 'out/platform_uploads'), resolve from project root.
    Project root is one directory above app.root_path (webapp/).
    """
    configured = Path(app.config["UPLOAD_ROOT"])
    if configured.is_absolute():
        return configured
    project_root = Path(app.root_path).resolve().parent
    return (project_root / configured).resolve()


def _safe_rmtree(app: Flask, path: Path, *, job_id: int, reason: str) -> None:
    """
    Best-effort deletion with verification (Windows-safe).
    We DO NOT log success unless the directory is actually gone.
    """
    try:
        if not path.exists():
            return

        def _on_rm_error(func, p, exc_info):
            # Try to remove read-only flag and retry (common on Windows)
            try:
                os.chmod(p, stat.S_IWRITE)
                func(p)
            except Exception:
                # If it's locked, we can't fix it here; retry loop below may succeed later.
                pass

        last_err: Exception | None = None
        for attempt in range(1, 6):  # ~2 seconds total
            try:
                shutil.rmtree(path, onerror=_on_rm_error)
            except Exception as e:
                last_err = e

            if not path.exists():
                app.logger.info(f"Deleted output directory for {reason} job {job_id}: {path}")
                return

            time.sleep(0.4)

        if last_err:
            app.logger.error(
                f"Failed to delete output directory for {reason} job {job_id}: {path} (still exists). "
                f"Last error: {last_err}"
            )
        else:
            app.logger.error(
                f"Failed to delete output directory for {reason} job {job_id}: {path} (still exists)."
            )
    except Exception as e:
        app.logger.warning(f"Unexpected error during output directory deletion for job {job_id}: {e}")


def kill_job_process(job_id: int) -> bool:
    """Kill the process for a job. Returns True if process was found and killed."""
    with _processes_lock:
        process = _running_processes.get(job_id)
        if process and process.poll() is None:
            _terminate_process(process, timeout=1.0)
            _running_processes.pop(job_id, None)
            return True
        elif process:
            # Process already finished, remove from dict
            _running_processes.pop(job_id, None)
    return False


def _parse_class_subject(stem: str) -> tuple[str, str]:
    # Example stems: "5 «В» Математика"
    s = (stem or "").strip()
    if "»" in s and "«" in s:
        i = s.find("»")
        if i != -1:
            class_name = s[: i + 1].strip()
            subject = s[i + 1 :].strip()
            return class_name, subject
    # Fallback: split by first space
    parts = s.split()
    if len(parts) <= 1:
        return s, ""
    return parts[0], " ".join(parts[1:]).strip()


def _collect_reports(reports_dir: Path) -> list[tuple[str, str, Path | None, Path | None]]:
    # returns [(class, subject, xlsx, docx)]
    by_stem: dict[str, dict[str, Path]] = {}
    for p in reports_dir.glob("*"):
        if p.suffix.lower() not in {".xlsx", ".docx"}:
            continue
        by_stem.setdefault(p.stem, {})[p.suffix.lower()] = p

    out: list[tuple[str, str, Path | None, Path | None]] = []
    for stem, d in sorted(by_stem.items()):
        class_name, subject = _parse_class_subject(stem)
        out.append((class_name, subject, d.get(".xlsx"), d.get(".docx")))
    return out


def _org_names_match(scraped_name: str, school_name: str) -> bool:
    """
    Нечёткое сравнение названия организации с mektep.edu.kz
    и названия школы в базе данных.
    
    Учитывает разницу в регистре, пробелах и частичное вхождение.
    """
    a = " ".join(scraped_name.lower().split()).strip()
    b = " ".join(school_name.lower().split()).strip()
    if not a or not b:
        return False
    # Точное совпадение
    if a == b:
        return True
    # Частичное вхождение (одно содержится в другом)
    if a in b or b in a:
        return True
    return False


def _check_org_name_allowed(app: Flask, job: ScrapeJob, output_dir: Path) -> str | None:
    """
    Проверка совпадения организации со скрапинга и школы учителя.
    
    Использует файл org_name_ru.txt (название организации на русском,
    прочитанное ДО смены языка) для сравнения с названием школы в БД.
    
    Returns:
        None если всё ок, строка с ошибкой если организация не совпадает.
    """
    school = db.session.get(School, job.school_id)
    if not school:
        return None  # Школа не найдена — пропускаем проверку
    
    # Если разрешены отчёты для других школ — пропускаем проверку
    if school.allow_cross_school_reports:
        app.logger.info(
            f"Job {job.id}: cross-school reports allowed for school '{school.name}', skipping org check"
        )
        return None
    
    # Читаем org_name на русском (всегда сравниваем по русскому)
    org_name_ru_file = output_dir / "org_name_ru.txt"
    if not org_name_ru_file.exists():
        # Fallback: пробуем обычный org_name.txt
        org_name_ru_file = output_dir / "org_name.txt"
    
    if not org_name_ru_file.exists():
        app.logger.warning(
            f"Job {job.id}: org_name file not found in {output_dir}, skipping org check"
        )
        return None
    
    scraped_org_name = org_name_ru_file.read_text(encoding="utf-8").strip()
    if not scraped_org_name:
        app.logger.warning(f"Job {job.id}: org_name file is empty, skipping org check")
        return None
    
    if _org_names_match(scraped_org_name, school.name):
        app.logger.info(
            f"Job {job.id}: org name match OK — "
            f"scraped='{scraped_org_name}', school='{school.name}'"
        )
        return None
    
    # Не совпадает!
    error_msg = (
        f"Организация на mektep.edu.kz «{scraped_org_name}» "
        f"не совпадает с вашей школой «{school.name}». "
        f"Создание отчётов для других школ запрещено администратором."
    )
    app.logger.warning(
        f"Job {job.id}: org name MISMATCH — "
        f"scraped='{scraped_org_name}', school='{school.name}'. "
        f"Cross-school reports disabled for this school."
    )
    return error_msg


def _monitor_progress(app: Flask, job_id: int, progress_file: Path):
    """Monitor progress file and update job progress in database."""
    with app.app_context():
        max_monitor_time = 600  # Stop monitoring after 10 minutes (was 40 sec - too short!)
        start_time = time.time()
        
        while True:
            try:
                # Check timeout
                if time.time() - start_time > max_monitor_time:
                    app.logger.warning(f"Progress monitoring timeout for job {job_id}")
                    break
                
                # Check job status directly from database
                job: ScrapeJob | None = db.session.get(ScrapeJob, job_id)
                if not job:
                    break
                
                # If job is finished (succeeded/failed/cancelled), stop monitoring
                if job.status in (ScrapeJobStatus.SUCCEEDED.value, ScrapeJobStatus.FAILED.value, ScrapeJobStatus.CANCELLED.value):
                    # Update progress file to reflect final status
                    if progress_file.exists():
                        try:
                            data = json.loads(progress_file.read_text(encoding="utf-8"))
                            data["finished"] = True
                            data["percent"] = 100 if job.status == ScrapeJobStatus.SUCCEEDED.value else 0
                            if job.error:
                                data["message"] = job.error
                            progress_file.write_text(json.dumps(data), encoding="utf-8")
                        except Exception:
                            pass
                    break
                
                # Update from progress file if it exists
                if progress_file.exists():
                    try:
                        data = json.loads(progress_file.read_text(encoding="utf-8"))
                        if job.status == ScrapeJobStatus.RUNNING.value:
                            job.progress_percent = data.get("percent", 50)
                            job.progress_message = data.get("message", "Выполняется...")
                            job.total_reports = data.get("total_reports")
                            job.processed_reports = data.get("processed_reports", 0)
                            db.session.commit()
                            
                            # Stop monitoring if progress file says finished
                            if data.get("finished", False):
                                # Check if we need to update status from progress file
                                if "ошибка авторизации" in data.get("message", "").lower() or "неверный логин" in data.get("message", "").lower():
                                    job.status = ScrapeJobStatus.FAILED.value
                                    job.error = data.get("message", "Ошибка авторизации: Неверный логин или пароль.")
                                    job.finished_at = datetime.utcnow()
                                    job.progress_percent = 0
                                    db.session.commit()
                                break
                    except Exception:
                        pass  # Continue monitoring even if read fails
                
                time.sleep(0.5)  # Check every 0.5 seconds for faster updates
            except Exception:
                break  # Exit on any error


def run_scrape_job(
    app: Flask,
    *,
    job_id: int,
    mektep_login: str,
    mektep_password: str,
    period_code: str,
    lang: str,
    school_index: str = "",
    limit: int,
    headless: bool = True,
) -> None:
    """
    Run a scraping job with concurrency limiting.
    
    Uses a semaphore to limit the number of concurrent jobs to prevent
    resource exhaustion (each Playwright browser uses ~1-2 GB RAM).
    """
    semaphore = _get_jobs_semaphore(app)
    
    # Try to acquire semaphore (wait for slot)
    app.logger.info(f"Job {job_id}: waiting for available slot (active: {get_active_jobs_count()}/{_max_concurrent_jobs})")
    
    with semaphore:
        app.logger.info(f"Job {job_id}: acquired slot, starting execution")
        _run_scrape_job_internal(app, job_id=job_id, mektep_login=mektep_login,
                                  mektep_password=mektep_password, period_code=period_code,
                                  lang=lang, school_index=school_index, limit=limit, headless=headless)
    
    app.logger.info(f"Job {job_id}: released slot")


def _run_scrape_job_internal(
    app: Flask,
    *,
    job_id: int,
    mektep_login: str,
    mektep_password: str,
    period_code: str,
    lang: str,
    school_index: str = "",
    limit: int,
    headless: bool = True,
) -> None:
    """Internal implementation of scrape job (called within semaphore context)."""
    with app.app_context():
        job: ScrapeJob | None = db.session.get(ScrapeJob, job_id)
        if not job:
            return

        job.status = ScrapeJobStatus.RUNNING.value
        job.started_at = datetime.utcnow()
        job.progress_percent = 50  # При запуске сразу показывает 50%
        job.progress_message = "Запуск скрапера..."
        db.session.commit()

        teacher: User | None = db.session.get(User, job.teacher_id)
        if not teacher:
            job.status = ScrapeJobStatus.FAILED.value
            job.error = "Teacher not found"
            job.finished_at = datetime.utcnow()
            db.session.commit()
            return

        # Filesystem layout (user requirement):
        # out/platform_uploads/
        #   school_{school_id}/
        #     teacher_{teacher_seq}/
        #       job_{job_seq}/
        #         reports/
        #
        # Where:
        # - teacher_seq is per-school (User.fs_teacher_seq)
        # - job_seq is per-(school, teacher) (ScrapeJob.fs_job_seq)
        #
        # This keeps paths stable and human-friendly:
        # - Each school starts teachers from 1
        # - Each teacher starts jobs from 1
        base_upload_dir = _resolve_upload_root(app)
        school_dir = base_upload_dir / f"school_{job.school_id}"
        
        # Ensure teacher has fs_teacher_seq (assign if missing)
        if teacher.fs_teacher_seq is None:
            from sqlalchemy import func
            max_seq = (
                db.session.query(func.max(User.fs_teacher_seq))
                .filter(User.school_id == job.school_id, User.role == Role.TEACHER.value)
                .scalar()
            )
            teacher.fs_teacher_seq = int(max_seq or 0) + 1
            db.session.commit()
            app.logger.info(f"Assigned fs_teacher_seq={teacher.fs_teacher_seq} to teacher {teacher.id}")
        
        # Ensure job has fs_job_seq (assign if missing)
        if job.fs_job_seq is None:
            from sqlalchemy import func
            max_job_seq = (
                db.session.query(func.max(ScrapeJob.fs_job_seq))
                .filter(ScrapeJob.school_id == job.school_id, ScrapeJob.teacher_id == job.teacher_id)
                .scalar()
            )
            job.fs_job_seq = int(max_job_seq or 0) + 1
            db.session.commit()
            app.logger.info(f"Assigned fs_job_seq={job.fs_job_seq} to job {job.id}")
        
        teacher_seq = teacher.fs_teacher_seq
        job_seq = job.fs_job_seq
        teacher_dir = school_dir / f"teacher_{teacher_seq}"
        output_dir = teacher_dir / f"job_{job_seq}"
        (output_dir / "reports").mkdir(parents=True, exist_ok=True)
        job.output_dir = str(output_dir)
        db.session.commit()  # Save output_dir to DB
        app.logger.info(
            f"Job {job_id} output directory: {output_dir} "
            f"(school_id={job.school_id}, teacher_id={job.teacher_id}, job_id={job.id}, "
            f"teacher_seq={teacher_seq}, job_seq={job_seq})"
        )
        
        # Create progress file path
        progress_file = output_dir / "progress.json"
        progress_file.write_text(json.dumps({
            "percent": 50,
            "message": "Запуск скрапера...",
            "total_reports": limit if limit > 0 else None,
            "processed_reports": 0,
            "finished": False
        }), encoding="utf-8")
        
        db.session.commit()

        # Start progress monitoring thread
        monitor_thread = threading.Thread(
            target=_monitor_progress,
            args=(app, job_id, progress_file),
            daemon=True
        )
        monitor_thread.start()

        env = dict(os.environ)

        env["MEKTEP_LOGIN"] = mektep_login
        env["MEKTEP_PASSWORD"] = mektep_password
        env["PROGRESS_FILE"] = str(progress_file)  # Pass progress file path to scraper
        env["PYTHONUNBUFFERED"] = "1"  # Отключаем буферизацию для мгновенного вывода логов
        if school_index:
            env["MEKTEP_SCHOOL_INDEX"] = school_index

        # Защита от передачи аккаунта: передаём название школы для проверки
        school_obj = db.session.get(School, job.school_id)
        if school_obj and not school_obj.allow_cross_school_reports:
            env["MEKTEP_EXPECTED_SCHOOL"] = school_obj.name
            app.logger.info(f"Job {job_id}: org check enabled, expected school='{school_obj.name}'")
        else:
            app.logger.info(f"Job {job_id}: cross-school reports allowed, org check disabled")

        cmd = [
            sys.executable,
            "scrape_mektep.py",
            "--headless",
            "1" if headless else "0",
            "--slowmo",
            "0",
            "--lang",
            lang,
            "--period",
            period_code,
            "--all",
            "1",
            "--out",
            str(output_dir),
        ]
        if limit > 0:
            cmd += ["--limit", str(limit)]

        # Use Popen instead of run to allow cancellation
        process = None
        try:
            # Store process for potential cancellation
            # Use unbuffered output to see logs in real-time
            # Set encoding to UTF-8 to handle Unicode characters properly
            process = subprocess.Popen(
                cmd, 
                env=env, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT,  # Combine stderr with stdout
                text=True,
                encoding='utf-8',
                errors='replace',  # Replace invalid characters instead of failing
                bufsize=1,  # Line buffered
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
            )
            
            with _processes_lock:
                _running_processes[job_id] = process
            
            app.logger.info(f"Started subprocess for job {job_id}, PID: {process.pid}")
            
            # Read output in real-time and log it
            stdout_lines = []
            output_lock = threading.Lock()
            output_finished = threading.Event()
            
            def read_output():
                """Read stdout/stderr in real-time."""
                try:
                    # Read line by line with proper encoding handling
                    for line in iter(process.stdout.readline, ''):
                        if not line:
                            break
                        try:
                            line = line.rstrip()
                            with output_lock:
                                stdout_lines.append(line)
                            # Log important lines (skip empty lines and password prompts)
                            if line and "Пароль:" not in line and "Password:" not in line:
                                app.logger.info(f"[Job {job_id}] {line}")
                        except UnicodeDecodeError as decode_err:
                            # If line still has encoding issues, decode with errors='replace'
                            try:
                                line_bytes = line.encode('utf-8', errors='replace') if isinstance(line, str) else line
                                line = line_bytes.decode('utf-8', errors='replace')
                                with output_lock:
                                    stdout_lines.append(line)
                                app.logger.warning(f"[Job {job_id}] Encoding issue in line, using replacement: {line[:100]}")
                            except Exception:
                                # Skip problematic lines
                                app.logger.warning(f"[Job {job_id}] Skipping line with encoding error")
                    output_finished.set()
                except Exception as e:
                    app.logger.error(f"Error reading subprocess output: {e}", exc_info=True)
                    output_finished.set()
            
            # Start output reading thread
            output_thread = threading.Thread(target=read_output, daemon=True)
            output_thread.start()
            
            # Monitor process and check for cancellation
            # Use configurable timeout to prevent infinite hanging
            max_runtime = app.config.get("JOB_TIMEOUT_SECONDS", 30 * 60)
            start_time = time.time()
            
            while process.poll() is None:
                # Check timeout
                elapsed = time.time() - start_time
                if elapsed > max_runtime:
                    app.logger.error(f"Job {job_id} exceeded max runtime ({max_runtime}s), terminating process {process.pid}")
                    try:
                        _terminate_process(process, timeout=2.0)
                    except Exception as kill_err:
                        app.logger.error(f"Error killing process: {kill_err}")
                    # Mark as failed
                    job.status = ScrapeJobStatus.FAILED.value
                    job.error = "Ошибка: Превышено время выполнения"
                    job.finished_at = datetime.utcnow()
                    job.progress_percent = 0
                    job.progress_message = "Превышено время выполнения"
                    db.session.commit()
                    # Delete output directory
                    _safe_rmtree(app, output_dir, job_id=job_id, reason="timeout")
                    return
                
                # Check if job was cancelled
                db.session.refresh(job)
                if job.status == ScrapeJobStatus.CANCELLED.value:
                    app.logger.info(f"Job {job_id} was cancelled, terminating process {process.pid}")
                    try:
                        _terminate_process(process, timeout=2.0)
                    except Exception as kill_err:
                        app.logger.error(f"Error killing process: {kill_err}")
                    break
                
                time.sleep(1)  # Check every second
            
            # Wait for output thread to finish (with timeout)
            output_finished.wait(timeout=10.0)
            
            # Ensure process has finished (with additional timeout)
            max_wait = 30  # Wait up to 30 seconds for process to finish
            wait_start = time.time()
            while process.poll() is None and (time.time() - wait_start) < max_wait:
                time.sleep(0.5)
            
            # If process still running after timeout, force terminate
            if process.poll() is None:
                app.logger.warning(f"Process {process.pid} for job {job_id} did not finish, forcing termination")
                try:
                    _terminate_process(process, timeout=2.0)
                    # Wait a bit more
                    time.sleep(2)
                except Exception:
                    pass
            
            return_code = process.returncode
            with output_lock:
                stdout = "\n".join(stdout_lines)
            stderr = ""  # Combined with stdout
            
            # Remove from running processes
            with _processes_lock:
                _running_processes.pop(job_id, None)
            
            # Check if job was cancelled during execution
            db.session.refresh(job)
            if job.status == ScrapeJobStatus.CANCELLED.value:
                app.logger.info(f"Job {job_id} was cancelled, process return code: {return_code}")
                # DO NOT delete output directory when cancelled - keep it for debugging
                app.logger.info(f"Job {job_id} cancelled - output directory preserved: {output_dir}")
                return
            
            if return_code == 0:
                app.logger.info(f"Scrape subprocess completed successfully for job {job_id}")
                app.logger.info(f"About to collect and save reports for job {job_id}, output_dir={output_dir}")
            else:
                # Log stdout and stderr for debugging
                app.logger.error(f"Scrape subprocess failed for job {job_id} with return code {return_code}")
                if stdout:
                    app.logger.error(f"Stdout: {stdout[:2000]}")  # Limit to first 2000 chars
                if stderr:
                    app.logger.error(f"Stderr: {stderr[:2000]}")  # Limit to first 2000 chars
                raise subprocess.CalledProcessError(return_code, cmd, stdout, stderr)
                
            # Mark as finished in progress file
            if progress_file.exists():
                try:
                    data = json.loads(progress_file.read_text(encoding="utf-8"))
                    data["finished"] = True
                    progress_file.write_text(json.dumps(data), encoding="utf-8")
                except Exception:
                    pass
            
            app.logger.info(f"Progress file updated, proceeding to report collection for job {job_id}")
                    
        except subprocess.CalledProcessError as e:
            with _processes_lock:
                _running_processes.pop(job_id, None)
            
            # Check if job was cancelled (don't mark as failed if cancelled)
            db.session.refresh(job)
            if job.status == ScrapeJobStatus.CANCELLED.value:
                app.logger.info(f"Job {job_id} was cancelled, not marking as failed")
                return
            
            # Check if this is an authorization error (exit code 4 or contains auth error message)
            stdout_lower = (e.stdout or "").lower()
            is_auth_error = (
                e.returncode == 4 or
                "неверный логин или пароль" in stdout_lower or
                "ошибка авторизации" in stdout_lower or
                "login failed" in stdout_lower
            )
            
            # Check if this is an org mismatch error (exit code 5)
            is_org_mismatch = (
                e.returncode == 5 or
                "не совпадает с вашей школой" in (e.stdout or "")
            )
            
            if is_org_mismatch:
                error_msg = "Организация на mektep.edu.kz не совпадает с вашей школой. Создание отчётов для других школ запрещено."
                # Пытаемся извлечь детальное сообщение из вывода
                for line in (e.stdout or "").split('\n'):
                    if "не совпадает с вашей школой" in line:
                        # Убираем префикс лога, оставляем только сообщение
                        clean = line.strip()
                        if "✗" in clean:
                            clean = clean.split("✗", 1)[-1].strip()
                        if clean:
                            error_msg = clean
                        break
                app.logger.warning(f"Scrape job {job_id} failed: Organization mismatch")
            elif is_auth_error:
                # Simple error message for authorization failures
                error_msg = "Ошибка авторизации: Неверный логин или пароль."
                app.logger.error(f"Scrape job {job_id} failed: Authorization error")
            else:
                # For other errors, prepare detailed message (but keep it short for user)
                stdout_preview = (e.stdout[:200] + "...") if e.stdout and len(e.stdout) > 200 else (e.stdout or "")
                error_msg = f"Ошибка выполнения (код {e.returncode})"
                if stdout_preview and "ошибка" in stdout_preview.lower():
                    # Try to extract just the error message
                    lines = stdout_preview.split('\n')
                    for line in lines:
                        if "ошибка" in line.lower() and len(line) < 150:
                            error_msg = line.strip()
                            break
                # Log full details for debugging
                app.logger.error(f"Scrape job {job_id} failed: {e}")
                if e.stdout:
                    app.logger.error(f"Stdout: {e.stdout[:2000]}")
            
            job.status = ScrapeJobStatus.FAILED.value
            job.error = error_msg
            job.finished_at = datetime.utcnow()
            job.progress_percent = 0
            job.progress_message = error_msg
            db.session.commit()

            # Delete output directory on error
            _safe_rmtree(app, output_dir, job_id=job_id, reason="failed")
            
            return
        except Exception as e:
            with _processes_lock:
                _running_processes.pop(job_id, None)
            job.status = ScrapeJobStatus.FAILED.value
            job.error = str(e)
            job.finished_at = datetime.utcnow()
            db.session.commit()
            app.logger.error(f"Scrape job {job_id} failed: {e}", exc_info=True)
            
            # Delete output directory on error
            _safe_rmtree(app, output_dir, job_id=job_id, reason="failed")
            
            return
        
        # Check if job was cancelled before saving reports
        db.session.refresh(job)
        if job.status == ScrapeJobStatus.CANCELLED.value:
            app.logger.info(f"Job {job_id} was cancelled, skipping report collection")
            return

        # ===== Проверка организации (защита от передачи аккаунта) =====
        # Сравнивает org_name с mektep.edu.kz (на русском) с названием школы в БД.
        # Если allow_cross_school_reports=False и названия не совпадают — отклоняем.
        org_error = _check_org_name_allowed(app, job, output_dir)
        if org_error:
            job.status = ScrapeJobStatus.FAILED.value
            job.error = org_error
            job.finished_at = datetime.utcnow()
            job.progress_percent = 0
            job.progress_message = org_error
            db.session.commit()
            # Удаляем файлы — отчёты для чужой школы не сохраняем
            _safe_rmtree(app, output_dir, job_id=job_id, reason="org_mismatch")
            return

        # Collect and save reports - this is critical and must complete!
        # Do this immediately after subprocess completes, before any app reload
        app.logger.info(f"Starting to collect and save reports for job {job_id}, output_dir={output_dir}")
        app.logger.info(f"Output directory exists: {output_dir.exists()}, reports dir: {(output_dir / 'reports').exists()}")
        try:
            # Ensure period_code is taken from job if not provided (for backward compatibility)
            if not period_code and job.period_code:
                period_code = job.period_code
                app.logger.info(f"Using period_code from job: {period_code}")
            
            # Validate period_code
            if not period_code or period_code.strip() == "":
                app.logger.error(f"Job {job_id} has empty period_code! Using job.period_code: '{job.period_code}'")
                period_code = job.period_code or "1"  # Default to "1" if still empty
                app.logger.warning(f"Using default period_code='{period_code}' for job {job_id}")
            
            # Normalize period_code (ensure it's a string, trim whitespace)
            period_code = str(period_code).strip()
            
            reports_dir = output_dir / "reports"
            app.logger.info(f"Collecting reports from {reports_dir} for period_code='{period_code}' (job.period_code='{job.period_code}')")
            reports = _collect_reports(reports_dir)
            app.logger.info(f"Found {len(reports)} reports to save for period_code='{period_code}'")
            
            created = 0
            updated = 0
            app.logger.info(f"Начало сохранения отчетов в базу данных для job {job_id}")
            for class_name, subject, xlsx, docx in reports:
                # Save absolute paths to ensure send_file can find them
                excel_abs = str(xlsx.resolve()) if xlsx and xlsx.exists() else None
                word_abs = str(docx.resolve()) if docx and docx.exists() else None
                
                # Log if Word file is missing
                if excel_abs and not word_abs:
                    app.logger.warning(
                        f"[{class_name} - {subject}] Excel файл существует, но Word файл отсутствует. "
                        f"Excel: {xlsx.name if xlsx else 'N/A'}, Expected Word: {docx.name if docx else 'N/A'}"
                    )
                
                # Check if report already exists to avoid duplicates
                existing = ReportFile.query.filter_by(
                    teacher_id=job.teacher_id,
                    class_name=class_name,
                    subject=subject,
                    period_code=period_code
                ).first()
                
                if existing:
                    # Update existing record
                    if excel_abs:
                        existing.excel_path = excel_abs
                    if word_abs:
                        existing.word_path = word_abs
                    # Also update period_code if it was wrong
                    if existing.period_code != period_code:
                        app.logger.warning(
                            f"[{class_name} - {subject}] Обновление period_code: '{existing.period_code}' -> '{period_code}'"
                        )
                        existing.period_code = period_code
                    updated += 1
                    app.logger.info(
                        f"[{class_name} - {subject}] Обновлен существующий отчет "
                        f"(period_code='{period_code}', Excel={'✓' if excel_abs else '✗'}, Word={'✓' if word_abs else '✗'})"
                    )
                else:
                    # Create new record - save even if Word file is missing
                    rf = ReportFile(
                        school_id=job.school_id,
                        teacher_id=job.teacher_id,
                        period_code=period_code,
                        class_name=class_name,
                        subject=subject,
                        excel_path=excel_abs,
                        word_path=word_abs,
                    )
                    db.session.add(rf)
                    created += 1
                    app.logger.info(
                        f"[{class_name} - {subject}] ✓ Создан новый отчет "
                        f"(period_code='{period_code}', Excel={'✓' if excel_abs else '✗'}, Word={'✓' if word_abs else '✗'})"
                    )

            job.status = ScrapeJobStatus.SUCCEEDED.value
            job.finished_at = datetime.utcnow()
            job.progress_percent = 100
            job.progress_message = f"Завершено. Создано отчетов: {created}, обновлено: {updated}, всего: {len(reports)}"
            
            # CRITICAL: Commit immediately and verify
            app.logger.info(f"Committing {created} new and {updated} updated reports to database for job {job_id}...")
            try:
                db.session.commit()
                app.logger.info("Database commit successful")
            except Exception as commit_err:
                app.logger.error(f"Commit failed: {commit_err}", exc_info=True)
                db.session.rollback()
                raise
            
            # Verify that reports were actually saved
            saved_count = ReportFile.query.filter_by(teacher_id=job.teacher_id, period_code=period_code).count()
            app.logger.info(
                f"Job {job_id} completed successfully. "
                f"Period_code={period_code}, Created {created} new reports, Updated {updated}, Total {len(reports)} reports. "
                f"Verified in DB: {saved_count} reports for this period."
            )
            
            # Double-check: reload job to ensure status was saved
            db.session.refresh(job)
            if job.status != ScrapeJobStatus.SUCCEEDED.value:
                app.logger.warning(f"Job {job_id} status mismatch after commit: {job.status}")
            
            # Update progress file to mark as finished
            if progress_file.exists():
                try:
                    final_data = {
                        "percent": 100,
                        "message": f"Завершено. Создано отчетов: {created}, обновлено: {updated}",
                        "total_reports": len(reports),
                        "processed_reports": len(reports),
                        "finished": True
                    }
                    progress_file.write_text(json.dumps(final_data), encoding="utf-8")
                    app.logger.info(f"Updated progress file for job {job_id} to finished state")
                except Exception as e:
                    app.logger.warning(f"Failed to update progress file: {e}")
            
            # Final flush to ensure everything is written
            db.session.flush()
            
        except Exception as e:
            app.logger.error(f"Error saving reports for job {job_id}: {e}", exc_info=True)
            # Try to save error state even if report saving failed
            try:
                job.status = ScrapeJobStatus.FAILED.value
                job.error = f"Ошибка сохранения отчетов: {str(e)[:100]}"
                job.finished_at = datetime.utcnow()
                db.session.commit()
                app.logger.info(f"Error state saved for job {job_id}")
            except Exception as commit_error:
                app.logger.error(f"Failed to commit error state: {commit_error}", exc_info=True)
            
            # Delete output directory on error
            _safe_rmtree(app, output_dir, job_id=job_id, reason="failed")

