"""
Скрипт для просмотра и очистки тестовых данных из БД.
Запуск: python clear_test_data.py [--delete]
"""
import sys
import argparse

sys.path.insert(0, '.')

from webapp import create_app
from webapp.extensions import db
from webapp.models import GradeReport, ReportFile, Class, TeacherQuotaUsage, User


def main():
    parser = argparse.ArgumentParser(description="Clear test data")
    parser.add_argument("--delete", action="store_true", help="Delete all data")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        reports = GradeReport.query.all()
        print("=== GradeReport: %d ===" % len(reports))
        for r in reports:
            teacher = db.session.get(User, r.teacher_id)
            tname = teacher.username if teacher else "?"
            print("  ID=%d | %s - %s | %s/%d | teacher=%s" % (
                r.id, r.class_name, r.subject_name, r.period_type, r.period_number, tname
            ))

        rfiles = ReportFile.query.all()
        print("")
        print("=== ReportFile: %d ===" % len(rfiles))
        for rf in rfiles:
            print("  ID=%d | %s - %s | period=%s | teacher_id=%s" % (
                rf.id, rf.class_name, rf.subject, rf.period_code, rf.teacher_id
            ))

        classes = Class.query.all()
        print("")
        print("=== Class: %d ===" % len(classes))
        for c in classes:
            print("  ID=%d | %s | class_teacher_id=%s" % (c.id, c.name, c.class_teacher_id))

        quotas = TeacherQuotaUsage.query.all()
        print("")
        print("=== TeacherQuotaUsage: %d ===" % len(quotas))
        for q in quotas:
            print("  teacher_id=%d | period=%s | used=%d" % (q.teacher_id, q.period_code, q.used_reports))

        if not args.delete:
            print("")
            print("--- Run with --delete to clear all data ---")
            return

        print("")
        print("=" * 50)
        print("DELETING...")

        gr_count = GradeReport.query.delete()
        print("  GradeReport: deleted %d" % gr_count)

        rf_count = ReportFile.query.delete()
        print("  ReportFile: deleted %d" % rf_count)

        q_count = TeacherQuotaUsage.query.delete()
        print("  TeacherQuotaUsage: deleted %d" % q_count)

        test_classes = ["5A", "5B", "7A", "7B", "9A", "9B", "11A"]
        for c in classes:
            if c.name in test_classes:
                c.class_teacher_id = None

        db.session.commit()
        print("")
        print("Done! Test data cleared.")


if __name__ == "__main__":
    main()
