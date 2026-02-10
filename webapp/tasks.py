"""
Celery tasks for background job processing.

These tasks run asynchronously via Celery workers,
enabling scalable scraping and AI text generation.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from celery import shared_task
from celery.utils.log import get_task_logger

from .extensions import db
from .models import ReportFile, ScrapeJob, ScrapeJobStatus, TeacherQuotaUsage

logger = get_task_logger(__name__)


def _parse_class_subject(stem: str) -> tuple[str, str]:
    """Parse class and subject from filename stem."""
    s = (stem or "").strip()
    if "»" in s and "«" in s:
        i = s.find("»")
        if i != -1:
            class_name = s[: i + 1].strip()
            subject = s[i + 1 :].strip()
            return class_name, subject
    parts = s.split()
    if len(parts) <= 1:
        return s, ""
    return parts[0], " ".join(parts[1:]).strip()


def _collect_reports(reports_dir: Path) -> list[tuple[str, str, Path | None, Path | None]]:
    """Collect report files from directory."""
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


@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def run_scrape_task(
    self,
    job_id: int,
    login: str,
    password: str,
    output_dir: str,
    period_code: str | None = None,
    lang: str = "ru",
    school_index: str = "",
) -> dict[str, Any]:
    """
    Run scraping job as Celery task.
    
    This task:
    1. Launches the scraper subprocess
    2. Monitors progress via progress.json
    3. Updates job status in database
    4. Collects and saves report files
    
    Args:
        job_id: Database job ID
        login: Mektep login
        password: Mektep password
        output_dir: Directory for output files
        period_code: Period code (e.g., "2024_Q1")
        lang: Language code (ru/kk/en)
        school_index: School index for teachers working at multiple schools
    
    Returns:
        dict with success status and report count
    """
    from flask import current_app
    
    job: ScrapeJob | None = db.session.get(ScrapeJob, job_id)
    if not job:
        logger.error(f"Job {job_id} not found")
        return {"success": False, "error": "Job not found"}
    
    try:
        # Mark as running
        job.status = ScrapeJobStatus.RUNNING.value
        job.started_at = datetime.utcnow()
        job.celery_task_id = self.request.id
        db.session.commit()
        
        logger.info(f"Starting scrape job {job_id} (task {self.request.id})")
        
        # Build command
        project_root = Path(__file__).parent.parent
        scraper_path = project_root / "scrape_mektep.py"
        
        env = os.environ.copy()
        env["MEKTEP_LOGIN"] = login
        env["MEKTEP_PASSWORD"] = password
        env["MEKTEP_OUTPUT_DIR"] = output_dir
        env["MEKTEP_LANG"] = lang
        env["PYTHONUNBUFFERED"] = "1"
        
        if period_code:
            env["MEKTEP_PERIOD"] = period_code
        
        if school_index:
            env["MEKTEP_SCHOOL_INDEX"] = school_index
        
        # Run scraper
        cmd = [sys.executable, str(scraper_path)]
        
        process = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(project_root),
        )
        
        # Monitor progress
        progress_file = Path(output_dir) / "progress.json"
        last_progress = 0
        
        while process.poll() is None:
            time.sleep(1)
            
            # Read progress
            if progress_file.exists():
                try:
                    data = json.loads(progress_file.read_text(encoding="utf-8"))
                    pct = data.get("percent", 0)
                    msg = data.get("message", "")
                    
                    if pct != last_progress:
                        job.progress_percent = pct
                        job.progress_message = msg
                        db.session.commit()
                        last_progress = pct
                        
                        # Update Celery task state
                        self.update_state(
                            state="PROGRESS",
                            meta={"percent": pct, "message": msg}
                        )
                except Exception:
                    pass
        
        # Get return code
        return_code = process.returncode
        logger.info(f"Scraper finished with code {return_code}")
        
        if return_code != 0:
            # Read stderr for error message
            stdout, _ = process.communicate()
            error_msg = stdout[-500:] if stdout else f"Exit code: {return_code}"
            
            job.status = ScrapeJobStatus.FAILED.value
            job.finished_at = datetime.utcnow()
            job.progress_message = f"Ошибка: {error_msg}"
            db.session.commit()
            
            return {"success": False, "error": error_msg}
        
        # Collect reports
        reports_dir = Path(output_dir) / "reports"
        if not reports_dir.exists():
            job.status = ScrapeJobStatus.FAILED.value
            job.finished_at = datetime.utcnow()
            job.progress_message = "Папка отчётов не создана"
            db.session.commit()
            return {"success": False, "error": "No reports directory"}
        
        reports = _collect_reports(reports_dir)
        created_count = 0
        
        for class_name, subject, xlsx, docx in reports:
            excel_abs = str(xlsx.resolve()) if xlsx and xlsx.exists() else None
            word_abs = str(docx.resolve()) if docx and docx.exists() else None
            
            if not excel_abs and not word_abs:
                continue
            
            # Check for existing report
            existing = ReportFile.query.filter_by(
                teacher_id=job.teacher_id,
                class_name=class_name,
                subject=subject,
                period_code=job.period_code,
            ).first()
            
            if existing:
                if excel_abs:
                    existing.excel_path = excel_abs
                if word_abs:
                    existing.word_path = word_abs
            else:
                rf = ReportFile(
                    school_id=job.school_id,
                    teacher_id=job.teacher_id,
                    period_code=job.period_code,
                    class_name=class_name,
                    subject=subject,
                    excel_path=excel_abs,
                    word_path=word_abs,
                )
                db.session.add(rf)
                created_count += 1
        
        # Update quota: one successful scrape = +1 (при любом успешном завершении)
        usage = (
            TeacherQuotaUsage.query.filter_by(
                teacher_id=job.teacher_id,
                period_code=job.period_code
            ).first()
            or TeacherQuotaUsage(
                teacher_id=job.teacher_id,
                period_code=job.period_code,
                used_reports=0
            )
        )
        usage.used_reports += 1
        db.session.add(usage)
        
        # Mark success
        job.status = ScrapeJobStatus.SUCCEEDED.value
        job.finished_at = datetime.utcnow()
        job.progress_percent = 100
        job.progress_message = f"Создано {len(reports)} отчётов"
        db.session.commit()
        
        logger.info(f"Job {job_id} completed: {len(reports)} reports")
        
        return {"success": True, "reports_count": len(reports)}
        
    except Exception as e:
        logger.exception(f"Job {job_id} failed with exception")
        
        job.status = ScrapeJobStatus.FAILED.value
        job.finished_at = datetime.utcnow()
        job.progress_message = f"Ошибка: {str(e)}"
        db.session.commit()
        
        # Retry on transient errors
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e)
        
        return {"success": False, "error": str(e)}


@shared_task(bind=True, max_retries=3, default_retry_delay=5)
def generate_ai_text(
    self,
    achieved: str,
    difficulties: str,
    model: str = "qwen-flash-character",
) -> dict[str, Any]:
    """
    Generate AI analysis text using Qwen API.
    Модель по умолчанию или из настроек школы (если вызывают с model=...).
    
    Args:
        achieved: Achieved goals text
        difficulties: Difficulties text
        model: Модель AI (qwen-flash-character, qwen-plus и т.д.)
    
    Returns:
        dict with difficulties_list, reasons, correction
    """
    from openai import OpenAI
    
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        return {"success": False, "error": "API key not configured"}
    
    client = OpenAI(
        api_key=api_key,
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    )
    
    system_prompt = """Ты помощник учителя в Казахстане. Генерируй анализ суммативного оценивания (15-30 слов на поле).

СТРОГО РАЗЛИЧАЙ три поля:

"difficulties_list" = ЧТО НЕ ПОЛУЧИЛОСЬ (какие темы/задания вызвали трудности)
Пример: "Учащиеся допускали ошибки при решении уравнений с дробями и построении графиков линейных функций."

"reasons" = ПОЧЕМУ НЕ ПОЛУЧИЛОСЬ (причины затруднений)
Пример: "Слабо усвоены правила работы с дробями, недостаточно практики в построении координатных систем."

"correction" = ЧТО ДЕЛАТЬ (план коррекционной работы)
Пример: "Провести повторение темы 'Дроби', выполнить тренировочные упражнения по построению графиков."

JSON формат: {"difficulties_list": "...", "reasons": "...", "correction": "..."}"""

    user_prompt = f"""Цели обучения:

Достигнутые: {achieved or 'Не указаны'}

С затруднениями: {difficulties}

Заполни JSON:
- difficulties_list: перечисли ЧТО не получилось
- reasons: объясни ПОЧЕМУ не получилось  
- correction: напиши ЧТО ДЕЛАТЬ для исправления"""

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=500,
        )
        
        content = response.choices[0].message.content.strip()
        
        # Parse JSON from response
        import re
        json_match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            return {
                "success": True,
                "difficulties_list": result.get("difficulties_list", ""),
                "reasons": result.get("reasons", ""),
                "correction": result.get("correction", ""),
            }
        else:
            return {"success": False, "error": "Invalid JSON response"}
            
    except Exception as e:
        logger.exception("AI generation failed")
        
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e)
        
        return {"success": False, "error": str(e)}


@shared_task
def cleanup_old_jobs(days: int = 30) -> dict[str, Any]:
    """
    Cleanup old completed/failed jobs.
    
    This task can be scheduled to run periodically.
    """
    from datetime import timedelta
    import shutil
    
    cutoff = datetime.utcnow() - timedelta(days=days)
    
    old_jobs = ScrapeJob.query.filter(
        ScrapeJob.finished_at < cutoff,
        ScrapeJob.status.in_([
            ScrapeJobStatus.SUCCEEDED.value,
            ScrapeJobStatus.FAILED.value,
            ScrapeJobStatus.CANCELLED.value,
        ])
    ).all()
    
    deleted_count = 0
    for job in old_jobs:
        try:
            if job.output_dir:
                output_dir = Path(job.output_dir)
                if output_dir.exists():
                    shutil.rmtree(output_dir)
            
            db.session.delete(job)
            deleted_count += 1
        except Exception as e:
            logger.warning(f"Failed to delete job {job.id}: {e}")
    
    db.session.commit()
    logger.info(f"Cleaned up {deleted_count} old jobs")
    
    return {"deleted": deleted_count}
