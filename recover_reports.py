"""Script to recover reports from existing job directories and save them to database."""
from webapp import create_app
from webapp.extensions import db
from webapp.models import ReportFile, ScrapeJob, ScrapeJobStatus
from pathlib import Path
import re

app = create_app()

def _parse_class_subject(stem: str) -> tuple[str, str]:
    """Parse class and subject from filename stem."""
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


def recover_reports_for_job(job_id: int):
    """Recover reports for a specific job."""
    with app.app_context():
        job = db.session.get(ScrapeJob, job_id)
        if not job:
            print(f"Job {job_id} not found")
            return
        
        if not job.output_dir:
            print(f"Job {job_id} has no output directory")
            return
        
        output_dir = Path(job.output_dir)
        reports_dir = output_dir / "reports"
        
        if not reports_dir.exists():
            print(f"Reports directory not found: {reports_dir}")
            return
        
        print(f"Recovering reports for job {job_id} from {reports_dir}")
        
        # Collect reports
        by_stem = {}
        for p in reports_dir.glob("*"):
            if p.suffix.lower() not in {".xlsx", ".docx"}:
                continue
            by_stem.setdefault(p.stem, {})[p.suffix.lower()] = p
        
        created = 0
        updated = 0
        
        for stem, d in sorted(by_stem.items()):
            class_name, subject = _parse_class_subject(stem)
            xlsx = d.get(".xlsx")
            docx = d.get(".docx")
            
            excel_abs = str(xlsx.resolve()) if xlsx and xlsx.exists() else None
            word_abs = str(docx.resolve()) if docx and docx.exists() else None
            
            # Check if report already exists
            existing = ReportFile.query.filter_by(
                teacher_id=job.teacher_id,
                class_name=class_name,
                subject=subject,
                period_code=job.period_code
            ).first()
            
            if existing:
                if excel_abs:
                    existing.excel_path = excel_abs
                if word_abs:
                    existing.word_path = word_abs
                updated += 1
                print(f"  Updated: {class_name} - {subject}")
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
                created += 1
                print(f"  Created: {class_name} - {subject}")
        
        db.session.commit()
        print(f"\nRecovery complete: {created} created, {updated} updated")


def recover_all_jobs():
    """Recover reports for all jobs that have output directories."""
    with app.app_context():
        jobs = ScrapeJob.query.filter(
            ScrapeJob.output_dir.isnot(None),
            ScrapeJob.status.in_([ScrapeJobStatus.SUCCEEDED.value, ScrapeJobStatus.RUNNING.value])
        ).all()
        
        print(f"Found {len(jobs)} jobs to check")
        
        for job in jobs:
            try:
                recover_reports_for_job(job.id)
            except Exception as e:
                print(f"Error recovering job {job.id}: {e}")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        job_id = int(sys.argv[1])
        recover_reports_for_job(job_id)
    else:
        recover_all_jobs()
