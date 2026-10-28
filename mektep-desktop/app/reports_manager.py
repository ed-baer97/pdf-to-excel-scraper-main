"""
Reports Manager - управление локальными отчетами

Использует SQLite для хранения метаданных отчетов.
"""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from typing import Dict, Iterator, List, Optional

from .academic_year import current_academic_year

_REPORTS_DDL = """
CREATE TABLE reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL DEFAULT '',
    class_name TEXT NOT NULL,
    subject TEXT NOT NULL,
    period_code TEXT NOT NULL,
    academic_year INTEGER NOT NULL DEFAULT 0,
    lang TEXT DEFAULT 'ru',
    excel_path TEXT,
    word_path TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    synced_to_server BOOLEAN DEFAULT 0,
    metadata TEXT,
    UNIQUE(username, class_name, subject, period_code, academic_year)
)
"""


class ReportsManager:
    """Менеджер локальных отчетов"""

    def __init__(self, storage_path: Path, username: str = ""):
        """
        Инициализация менеджера

        Args:
            storage_path: Путь к папке для хранения БД и отчетов
            username: Имя пользователя (логин на сервере) для разделения отчётов
        """
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.username = username or ""

        self.db_path = self.storage_path / "reports.db"
        self._init_database()

    @contextmanager
    def _connect(self, *, row_factory: bool = False) -> Iterator[sqlite3.Connection]:
        """Контекстный менеджер SQLite-соединения с гарантированным закрытием."""
        conn = sqlite3.connect(self.db_path)
        if row_factory:
            conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_database(self):
        """Инициализация SQLite базы данных с миграцией"""
        with self._connect() as conn:
            cursor = conn.cursor()

            cursor.execute("PRAGMA table_info(reports)")
            columns = [col[1] for col in cursor.fetchall()]

            if "username" not in columns and len(columns) > 0:
                cursor.execute("ALTER TABLE reports ADD COLUMN username TEXT NOT NULL DEFAULT ''")
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS reports_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username TEXT NOT NULL DEFAULT '',
                        class_name TEXT NOT NULL,
                        subject TEXT NOT NULL,
                        period_code TEXT NOT NULL,
                        lang TEXT DEFAULT 'ru',
                        excel_path TEXT,
                        word_path TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        synced_to_server BOOLEAN DEFAULT 0,
                        metadata TEXT,
                        UNIQUE(username, class_name, subject, period_code)
                    )
                ''')
                cursor.execute('''
                    INSERT INTO reports_new 
                        (id, username, class_name, subject, period_code, lang, 
                         excel_path, word_path, created_at, synced_to_server, metadata)
                    SELECT id, username, class_name, subject, period_code, lang,
                           excel_path, word_path, created_at, synced_to_server, metadata
                    FROM reports
                ''')
                cursor.execute("DROP TABLE reports")
                cursor.execute("ALTER TABLE reports_new RENAME TO reports")
            elif len(columns) == 0:
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS reports (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username TEXT NOT NULL DEFAULT '',
                        class_name TEXT NOT NULL,
                        subject TEXT NOT NULL,
                        period_code TEXT NOT NULL,
                        lang TEXT DEFAULT 'ru',
                        excel_path TEXT,
                        word_path TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        synced_to_server BOOLEAN DEFAULT 0,
                        metadata TEXT,
                        UNIQUE(username, class_name, subject, period_code)
                    )
                ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_period 
                ON reports(period_code)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_created 
                ON reports(created_at DESC)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_username 
                ON reports(username)
            ''')

            self._ensure_academic_year(cursor)

    def _ensure_academic_year(self, cursor):
        """Добавляет учебный год и включает его в уникальность отчёта."""
        cursor.execute("PRAGMA table_info(reports)")
        columns = [col[1] for col in cursor.fetchall()]
        if columns and "academic_year" not in columns:
            cursor.execute("ALTER TABLE reports ADD COLUMN academic_year INTEGER")
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='reports'")
        row = cursor.fetchone()
        ddl = (row[0] if row else "") or ""
        normalized = "".join(ddl.upper().split())
        if "UNIQUE(USERNAME,CLASS_NAME,SUBJECT,PERIOD_CODE,ACADEMIC_YEAR)" not in normalized:
            cursor.execute("DROP TABLE IF EXISTS reports_prev")
            cursor.execute("ALTER TABLE reports RENAME TO reports_prev")
            cursor.execute(_REPORTS_DDL)
            cursor.execute("PRAGMA table_info(reports_prev)")
            prev_cols = [col[1] for col in cursor.fetchall()]
            year_expr = "COALESCE(academic_year, 0)" if "academic_year" in prev_cols else "0"
            user_expr = "COALESCE(username, '')" if "username" in prev_cols else "''"
            cursor.execute(
                f"""
                INSERT INTO reports (
                    id, username, class_name, subject, period_code, academic_year,
                    lang, excel_path, word_path, created_at, synced_to_server, metadata
                )
                SELECT id, {user_expr}, class_name, subject, period_code, {year_expr},
                       lang, excel_path, word_path, created_at, synced_to_server, metadata
                FROM reports_prev
                """
            )
            cursor.execute("DROP TABLE reports_prev")
        cursor.execute(
            "UPDATE reports SET academic_year = ? WHERE academic_year IS NULL OR academic_year = 0",
            (current_academic_year(),),
        )

    def save_report(self, report: Dict) -> int:
        """
        Сохранить метаданные отчета

        Returns:
            int: ID созданной/обновленной записи
        """
        academic_year = int(report.get("academic_year") or current_academic_year())
        metadata_json = json.dumps(report.get("metadata", {}), ensure_ascii=False)

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                SELECT id FROM reports 
                WHERE username = ? AND class_name = ? AND subject = ? AND period_code = ? AND academic_year = ?
                ''',
                (
                    self.username,
                    report["class_name"],
                    report["subject"],
                    report["period_code"],
                    academic_year,
                ),
            )
            existing = cursor.fetchone()

            if existing:
                cursor.execute(
                    '''
                    UPDATE reports 
                    SET excel_path = ?, word_path = ?, lang = ?, 
                        created_at = CURRENT_TIMESTAMP, metadata = ?
                    WHERE id = ?
                    ''',
                    (
                        report.get("excel_path"),
                        report.get("word_path"),
                        report.get("lang", "ru"),
                        metadata_json,
                        existing[0],
                    ),
                )
                return existing[0]

            cursor.execute(
                '''
                INSERT INTO reports 
                (username, class_name, subject, period_code, academic_year, lang, excel_path, word_path, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    self.username,
                    report["class_name"],
                    report["subject"],
                    report["period_code"],
                    academic_year,
                    report.get("lang", "ru"),
                    report.get("excel_path"),
                    report.get("word_path"),
                    metadata_json,
                ),
            )
            return cursor.lastrowid

    def get_reports(self, filters: Optional[Dict] = None, include_all_users: bool = False) -> List[Dict]:
        """
        Получить список отчетов с фильтрацией.
        """
        if include_all_users:
            query = "SELECT * FROM reports WHERE 1=1"
            params: list = []
        else:
            query = "SELECT * FROM reports WHERE username = ?"
            params = [self.username]

        if filters:
            if "period_code" in filters:
                query += " AND period_code = ?"
                params.append(filters["period_code"])

            if filters.get("academic_year") is not None:
                query += " AND academic_year = ?"
                params.append(int(filters["academic_year"]))

            if "class_name" in filters:
                query += " AND class_name = ?"
                params.append(filters["class_name"])

            if "subject" in filters:
                query += " AND subject LIKE ?"
                params.append(f"%{filters['subject']}%")

            if "synced" in filters:
                query += " AND synced_to_server = ?"
                params.append(1 if filters["synced"] else 0)

        query += " ORDER BY created_at DESC"

        with self._connect(row_factory=True) as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()

        reports = []
        for row in rows:
            report = dict(row)
            if report.get("metadata"):
                try:
                    report["metadata"] = json.loads(report["metadata"])
                except (TypeError, ValueError):
                    report["metadata"] = {}
            else:
                report["metadata"] = {}
            reports.append(report)

        return reports

    def get_report(self, report_id: int) -> Optional[Dict]:
        """
        Получить отчет по ID
        """
        with self._connect(row_factory=True) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM reports WHERE id = ?", (report_id,))
            row = cursor.fetchone()

        if not row:
            return None

        report = dict(row)
        if report.get("metadata"):
            try:
                report["metadata"] = json.loads(report["metadata"])
            except (TypeError, ValueError):
                report["metadata"] = {}
        return report

    def delete_report(self, report_id: int, delete_files: bool = True) -> bool:
        """
        Удалить отчет
        """
        if delete_files:
            report = self.get_report(report_id)
            if report:
                if report.get("excel_path"):
                    excel_path = Path(report["excel_path"])
                    if excel_path.exists():
                        try:
                            excel_path.unlink()
                        except OSError:
                            pass
                    meta_path = excel_path.with_suffix(".meta.json")
                    if meta_path.exists():
                        try:
                            meta_path.unlink()
                        except OSError:
                            pass

                if report.get("word_path"):
                    word_path = Path(report["word_path"])
                    if word_path.exists():
                        try:
                            word_path.unlink()
                        except OSError:
                            pass

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM reports WHERE id = ?", (report_id,))
            return cursor.rowcount > 0

    def mark_as_synced(self, report_id: int):
        """Отметить отчет как синхронизированный с сервером"""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE reports SET synced_to_server = 1 WHERE id = ?", (report_id,))

    def get_statistics(self) -> Dict:
        """
        Получить статистику по отчетам текущего пользователя
        """
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM reports WHERE username = ?", (self.username,))
            total = cursor.fetchone()[0]

            cursor.execute(
                '''
                SELECT period_code, COUNT(*) as count 
                FROM reports 
                WHERE username = ?
                GROUP BY period_code
                ''',
                (self.username,),
            )
            by_period = {row[0]: row[1] for row in cursor.fetchall()}

            cursor.execute(
                "SELECT COUNT(*) FROM reports WHERE username = ? AND synced_to_server = 1",
                (self.username,),
            )
            synced = cursor.fetchone()[0]

        return {
            "total": total,
            "by_period": by_period,
            "synced": synced,
            "not_synced": total - synced,
        }

    def cleanup_old_reports(self, days: int = 90):
        """
        Удалить старые отчеты текущего пользователя
        """
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                DELETE FROM reports 
                WHERE username = ? AND created_at < datetime('now', '-' || ? || ' days')
                ''',
                (self.username, days),
            )
            return cursor.rowcount
