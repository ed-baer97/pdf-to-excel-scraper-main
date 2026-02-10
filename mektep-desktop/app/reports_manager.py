"""
Reports Manager - управление локальными отчетами

Использует SQLite для хранения метаданных отчетов.
"""
import sqlite3
from pathlib import Path
from typing import Optional, List, Dict
from datetime import datetime
import json


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
    
    def _init_database(self):
        """Инициализация SQLite базы данных с миграцией"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Проверяем, есть ли уже колонка username
        cursor.execute("PRAGMA table_info(reports)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if "username" not in columns and len(columns) > 0:
            # Миграция: таблица существует, но без username — добавляем колонку
            cursor.execute("ALTER TABLE reports ADD COLUMN username TEXT NOT NULL DEFAULT ''")
            # Удаляем старый UNIQUE constraint, создаём новый через пересоздание
            # SQLite не поддерживает DROP CONSTRAINT, поэтому пересоздаём таблицу
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
            conn.commit()
        elif len(columns) == 0:
            # Таблица не существует — создаём с username
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
        
        # Индексы для быстрого поиска
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
        
        conn.commit()
        conn.close()
    
    def save_report(self, report: Dict) -> int:
        """
        Сохранить метаданные отчета
        
        Args:
            report: Словарь с данными:
                {
                    "class_name": "9А",
                    "subject": "Математика",
                    "period_code": "2",
                    "lang": "ru",
                    "excel_path": "/path/to/file.xlsx",
                    "word_path": "/path/to/file.docx",
                    "metadata": {...}  # Дополнительные данные
                }
        
        Returns:
            int: ID созданной/обновленной записи
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Проверяем, существует ли уже такой отчет для этого пользователя
        cursor.execute('''
            SELECT id FROM reports 
            WHERE username = ? AND class_name = ? AND subject = ? AND period_code = ?
        ''', (self.username, report['class_name'], report['subject'], report['period_code']))
        
        existing = cursor.fetchone()
        metadata_json = json.dumps(report.get('metadata', {}), ensure_ascii=False)
        
        if existing:
            # Обновляем существующий
            cursor.execute('''
                UPDATE reports 
                SET excel_path = ?, word_path = ?, lang = ?, 
                    created_at = CURRENT_TIMESTAMP, metadata = ?
                WHERE id = ?
            ''', (
                report.get('excel_path'),
                report.get('word_path'),
                report.get('lang', 'ru'),
                metadata_json,
                existing[0]
            ))
            report_id = existing[0]
        else:
            # Создаем новый
            cursor.execute('''
                INSERT INTO reports 
                (username, class_name, subject, period_code, lang, excel_path, word_path, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                self.username,
                report['class_name'],
                report['subject'],
                report['period_code'],
                report.get('lang', 'ru'),
                report.get('excel_path'),
                report.get('word_path'),
                metadata_json
            ))
            report_id = cursor.lastrowid
        
        conn.commit()
        conn.close()
        
        return report_id
    
    def get_reports(self, filters: Optional[Dict] = None) -> List[Dict]:
        """
        Получить список отчетов с фильтрацией (только для текущего пользователя)
        
        Args:
            filters: Фильтры (опционально):
                {
                    "period_code": "2",
                    "class_name": "9А",
                    "subject": "Математика",
                    "synced": True/False
                }
        
        Returns:
            List[Dict]: Список отчетов
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Для доступа по именам колонок
        cursor = conn.cursor()
        
        query = "SELECT * FROM reports WHERE username = ?"
        params = [self.username]
        
        if filters:
            if 'period_code' in filters:
                query += " AND period_code = ?"
                params.append(filters['period_code'])
            
            if 'class_name' in filters:
                query += " AND class_name = ?"
                params.append(filters['class_name'])
            
            if 'subject' in filters:
                query += " AND subject LIKE ?"
                params.append(f"%{filters['subject']}%")
            
            if 'synced' in filters:
                query += " AND synced_to_server = ?"
                params.append(1 if filters['synced'] else 0)
        
        query += " ORDER BY created_at DESC"
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        reports = []
        for row in rows:
            report = dict(row)
            # Парсим JSON метаданных
            if report.get('metadata'):
                try:
                    report['metadata'] = json.loads(report['metadata'])
                except:
                    report['metadata'] = {}
            else:
                report['metadata'] = {}
            reports.append(report)
        
        conn.close()
        return reports
    
    def get_report(self, report_id: int) -> Optional[Dict]:
        """
        Получить отчет по ID
        
        Args:
            report_id: ID отчета
        
        Returns:
            Dict или None если не найден
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM reports WHERE id = ?", (report_id,))
        row = cursor.fetchone()
        
        if row:
            report = dict(row)
            if report.get('metadata'):
                try:
                    report['metadata'] = json.loads(report['metadata'])
                except:
                    report['metadata'] = {}
            conn.close()
            return report
        
        conn.close()
        return None
    
    def delete_report(self, report_id: int, delete_files: bool = True) -> bool:
        """
        Удалить отчет
        
        Args:
            report_id: ID отчета
            delete_files: Удалить физические файлы (Excel/Word)
        
        Returns:
            bool: True если успешно удалено
        """
        if delete_files:
            report = self.get_report(report_id)
            if report:
                # Удаляем физические файлы
                if report.get('excel_path'):
                    excel_path = Path(report['excel_path'])
                    if excel_path.exists():
                        try:
                            excel_path.unlink()
                        except Exception:
                            pass
                    
                    # Удаляем метафайл с server_report_id
                    meta_path = excel_path.with_suffix(".meta.json")
                    if meta_path.exists():
                        try:
                            meta_path.unlink()
                        except Exception:
                            pass
                
                if report.get('word_path'):
                    word_path = Path(report['word_path'])
                    if word_path.exists():
                        try:
                            word_path.unlink()
                        except Exception:
                            pass
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM reports WHERE id = ?", (report_id,))
        deleted = cursor.rowcount > 0
        
        conn.commit()
        conn.close()
        
        return deleted
    
    def mark_as_synced(self, report_id: int):
        """Отметить отчет как синхронизированный с сервером"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE reports SET synced_to_server = 1 WHERE id = ?
        ''', (report_id,))
        
        conn.commit()
        conn.close()
    
    def get_statistics(self) -> Dict:
        """
        Получить статистику по отчетам текущего пользователя
        
        Returns:
            Dict: {
                "total": int,
                "by_period": {"1": 5, "2": 8, ...},
                "synced": int,
                "not_synced": int
            }
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Общее количество (только для текущего пользователя)
        cursor.execute("SELECT COUNT(*) FROM reports WHERE username = ?", (self.username,))
        total = cursor.fetchone()[0]
        
        # По периодам
        cursor.execute('''
            SELECT period_code, COUNT(*) as count 
            FROM reports 
            WHERE username = ?
            GROUP BY period_code
        ''', (self.username,))
        by_period = {row[0]: row[1] for row in cursor.fetchall()}
        
        # Синхронизированные
        cursor.execute(
            "SELECT COUNT(*) FROM reports WHERE username = ? AND synced_to_server = 1",
            (self.username,)
        )
        synced = cursor.fetchone()[0]
        
        conn.close()
        
        return {
            "total": total,
            "by_period": by_period,
            "synced": synced,
            "not_synced": total - synced
        }
    
    def cleanup_old_reports(self, days: int = 90):
        """
        Удалить старые отчеты текущего пользователя
        
        Args:
            days: Удалить отчеты старше N дней
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            DELETE FROM reports 
            WHERE username = ? AND created_at < datetime('now', '-' || ? || ' days')
        ''', (self.username, days))
        
        deleted_count = cursor.rowcount
        conn.commit()
        conn.close()
        
        return deleted_count
