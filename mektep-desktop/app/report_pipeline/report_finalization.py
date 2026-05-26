"""
Финализация отчётов после скрапера: перемещение файлов, JSON → grades/analytics, загрузка на сервер.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from ..debug_log import dbg_log
from .period_map import PERIOD_MAP
from .report_utils import (
    can_upload_period_grades,
    has_grade_summary_columns,
    move_file,
    parse_class_liter,
    parse_number,
    resolve_period,
    sanitize_filename,
    visible_soch_column,
)

if TYPE_CHECKING:
    from ..api_client import MektepAPIClient


class ReportFinalizer:
    """Состояние и шаги финализации (раньше методы ScraperThread)."""

    def __init__(
        self,
        period_code: str,
        lang: str,
        output_dir: Path,
        temp_dir: Path,
        api_client: Optional["MektepAPIClient"],
    ):
        """Сохраняет параметры периода, языка, путей и API-клиента для последующей финализации."""
        self.period_code = period_code
        self.lang = lang
        self.output_dir = Path(output_dir)
        self.temp_dir = Path(temp_dir)
        self.api_client = api_client
        self._scraped_org_name: Optional[str] = None
        self._org_upload_allowed = True
        self._server_school_name: Optional[str] = None

    def finalize_reports(self) -> List[Dict[str, Any]]:
        """
        Финализация отчетов: перемещение из временной папки в финальную структуру.

        Формирует grades_json + analytics_json напрямую из JSON скрапера
        (без обхода через Excel) и загружает на сервер.
        """
        reports: List[Dict[str, Any]] = []

        period_name = PERIOD_MAP.get(self.period_code, f"Четверть {self.period_code}")

        if not self.temp_dir.exists():
            return reports

        teacher_name = None
        profile_file = self.temp_dir / "profile_name.txt"
        if profile_file.exists():
            try:
                teacher_name = profile_file.read_text(encoding="utf-8").strip()
                print(f"[DEBUG] ФИО учителя из скрапера: '{teacher_name}'")
            except Exception as e:
                print(f"[DEBUG] Ошибка чтения profile_name.txt: {e}")

        if teacher_name:
            safe_teacher_name = re.sub(r'[\\/*?:"<>|]', "_", teacher_name).strip()
        else:
            safe_teacher_name = "Неизвестный учитель"

        final_reports_dir = self.output_dir / safe_teacher_name / period_name
        final_reports_dir.mkdir(parents=True, exist_ok=True)

        self._scraped_org_name = None
        org_name_file = self.temp_dir / "org_name.txt"
        org_name_ru_file = self.temp_dir / "org_name_ru.txt"
        if org_name_ru_file.exists():
            try:
                _ru = org_name_ru_file.read_text(encoding="utf-8").strip()
                if _ru:
                    self._scraped_org_name = _ru
            except Exception:
                pass
        if self._scraped_org_name is None and org_name_file.exists():
            try:
                self._scraped_org_name = org_name_file.read_text(encoding="utf-8").strip()
            except Exception:
                pass

        self._org_upload_allowed = True
        self._server_school_name = None

        dbg_log(
            "report_finalization:finalize_reports",
            "pre-refresh",
            {
                "has_org": bool(self._scraped_org_name),
                "has_api": self.api_client is not None,
                "is_auth": self.api_client.is_authenticated() if self.api_client else False,
            },
            "H1",
        )

        if self._scraped_org_name and self.api_client:
            if not self.api_client.is_authenticated():
                refresh_result = self.api_client.refresh_token()
                if refresh_result.get("success"):
                    print("[DEBUG] Токен успешно обновлён перед загрузкой.")
                else:
                    print(
                        f"[DEBUG] Не удалось обновить токен перед загрузкой: {refresh_result.get('error', '?')}. "
                        "Отчёты будут сохранены только локально."
                    )

        if self._scraped_org_name and self.api_client and self.api_client.is_authenticated():
            lookup_result = self.api_client.lookup_school(self._scraped_org_name)
            dbg_log(
                "report_finalization:finalize_reports",
                "lookup_school",
                {
                    "success": lookup_result.get("success"),
                    "needs_auth": lookup_result.get("needs_auth"),
                    "org_not_found": lookup_result.get("org_not_found"),
                    "error": lookup_result.get("error"),
                },
                "H2",
            )
            if lookup_result.get("success"):
                self._server_school_name = lookup_result.get("school_name")
                print(
                    f"[DEBUG] Организация найдена на сервере: '{self._server_school_name}' "
                    f"(ID: {lookup_result.get('school_id')})"
                )
            else:
                self._org_upload_allowed = False
                print(
                    f"[DEBUG] Организация '{self._scraped_org_name}' НЕ найдена на сервере. "
                    f"Отчёты будут сохранены только локально (Excel/Word)."
                )

        batch_dir = self.temp_dir / "batch"
        reports_dir = self.temp_dir / "reports"

        batch_subdirs: List[Path] = []
        if batch_dir.exists():
            batch_subdirs = sorted(
                [d for d in batch_dir.iterdir() if d.is_dir()],
                key=lambda d: d.name,
            )

        if batch_subdirs:
            for subdir in batch_subdirs:
                try:
                    report_data = self._process_batch_subdir(
                        subdir, reports_dir, final_reports_dir, period_name
                    )
                    if report_data:
                        reports.append(report_data)
                except Exception as e:
                    print(f"[DEBUG] Ошибка обработки {subdir.name}: {e}")
                    continue
        else:
            reports = self._finalize_from_excel_files(final_reports_dir, period_name)

        return reports

    def _process_batch_subdir(
        self,
        subdir: Path,
        reports_dir: Path,
        final_reports_dir: Path,
        period_name: str,
    ) -> Optional[Dict[str, Any]]:
        """Обработка одного batch-подкаталога с JSON данными скрапера."""
        students_file = subdir / "criteria_students.json"
        context_file = subdir / "criteria_context.json"

        if not students_file.exists():
            return None

        ctx: Dict[str, Any] = {}
        if context_file.exists():
            with open(context_file, "r", encoding="utf-8") as f:
                ctx = json.load(f)

        class_name_raw = str(ctx.get("class", "")).strip()
        subject_name = str(ctx.get("subject", "")).strip()
        class_name = parse_class_liter(class_name_raw)

        if not class_name or not subject_name:
            return None

        final_excel = None
        final_word = None

        if reports_dir.exists():
            expected_name = sanitize_filename(f"{class_name_raw} {subject_name}".strip())
            excel_candidate = reports_dir / f"{expected_name}.xlsx"

            if not excel_candidate.exists():
                alt_name = sanitize_filename(f"{class_name} {subject_name}".strip())
                excel_candidate = reports_dir / f"{alt_name}.xlsx"

            if excel_candidate.exists():
                final_excel = move_file(
                    excel_candidate, final_reports_dir / excel_candidate.name
                )

                word_candidate = excel_candidate.with_suffix(".docx")
                if word_candidate.exists():
                    final_word = move_file(
                        word_candidate, final_reports_dir / word_candidate.name
                    )

        report_data: Dict[str, Any] = {
            "class_name": class_name,
            "subject": subject_name,
            "period_code": self.period_code,
            "lang": self.lang,
            "org_name": self._scraped_org_name,
            "excel_path": str(final_excel.absolute()) if final_excel else None,
            "word_path": str(final_word.absolute()) if final_word else None,
            "metadata": {
                "created_by": "desktop",
                "output_dir": str(final_reports_dir),
                "period_name": period_name,
                "org_name": self._scraped_org_name,
                "server_school_name": self._server_school_name,
            },
        }

        org_upload_allowed = self._org_upload_allowed

        dbg_log(
            "report_finalization:_process_batch_subdir",
            "upload_check",
            {
                "class": class_name,
                "subject": subject_name,
                "org_upload_allowed": org_upload_allowed,
                "has_api": self.api_client is not None,
                "is_auth": self.api_client.is_authenticated() if self.api_client else False,
            },
            "H3",
        )
        if not org_upload_allowed:
            print(
                f"[DEBUG] Пропуск загрузки на сервер: организация "
                f"'{self._scraped_org_name}' не найдена в БД. "
                f"Отчёт сохранён только локально: {class_name} {subject_name}"
            )
            report_data["upload_skipped"] = True
            report_data["upload_skip_reason"] = "org_not_found"
            return report_data

        if not self.api_client or not self.api_client.is_authenticated():
            print(
                f"[DEBUG] Пропуск загрузки на сервер: отсутствует авторизация. "
                f"Отчёт сохранён только локально: {class_name} {subject_name}"
            )
            report_data["upload_skipped"] = True
            report_data["upload_skip_reason"] = "auth_required"
            return report_data

        try:
            grades_data, analytics_data, can_upload = self._build_grades_and_analytics(subdir)
            dbg_log(
                "report_finalization:_process_batch_subdir",
                "grades_built",
                {"class": class_name, "subject": subject_name, "has_grades": bool(grades_data)},
                "H5",
            )
            if grades_data:
                period_type, period_number, skip = resolve_period(self.period_code, subdir)
                dbg_log(
                    "report_finalization:_process_batch_subdir",
                    "period_resolved",
                    {
                        "class": class_name,
                        "subject": subject_name,
                        "skip": skip,
                        "period_type": period_type,
                        "period_number": period_number,
                    },
                    "H5",
                )
                if skip:
                    print(
                        f"[DEBUG] Пропуск полугодового предмета для четверти {self.period_code}: "
                        f"{class_name} {subject_name}"
                    )
                    return report_data

                if not can_upload:
                    print(
                        f"[DEBUG] Пропуск загрузки: нет СОЧ и нет колонок итога: "
                        f"{class_name} {subject_name}"
                    )
                    report_data["upload_skipped"] = True
                    report_data["upload_skip_reason"] = "no_grade_table"
                    return report_data

                upload_result = self.api_client.upload_report(
                    class_name=class_name,
                    subject_name=subject_name,
                    period_type=period_type,
                    period_number=period_number,
                    grades_data=grades_data,
                    analytics_data=analytics_data,
                    org_name=self._scraped_org_name,
                    has_grade_summary_columns=has_grade_summary_columns(subdir),
                    visible_soch_column=visible_soch_column(subdir),
                )
                dbg_log(
                    "report_finalization:_process_batch_subdir",
                    "upload_result",
                    {
                        "class": class_name,
                        "subject": subject_name,
                        "success": upload_result.get("success"),
                        "needs_auth": upload_result.get("needs_auth"),
                        "report_id": upload_result.get("report_id"),
                        "action": upload_result.get("action"),
                    },
                    "H4",
                )
                if upload_result.get("needs_auth"):
                    refresh_result = self.api_client.refresh_token()
                    if refresh_result.get("success"):
                        upload_result = self.api_client.upload_report(
                            class_name=class_name,
                            subject_name=subject_name,
                            period_type=period_type,
                            period_number=period_number,
                            grades_data=grades_data,
                            analytics_data=analytics_data,
                            org_name=self._scraped_org_name,
                            has_grade_summary_columns=has_grade_summary_columns(subdir),
                            visible_soch_column=visible_soch_column(subdir),
                        )
                        dbg_log(
                            "report_finalization:_process_batch_subdir",
                            "upload_retry",
                            {
                                "class": class_name,
                                "subject": subject_name,
                                "success": upload_result.get("success"),
                                "report_id": upload_result.get("report_id"),
                                "action": upload_result.get("action"),
                            },
                            "H4",
                        )
                if upload_result.get("success"):
                    report_data["server_report_id"] = upload_result.get("report_id")
                    if final_excel:
                        self._save_report_metadata(
                            final_excel,
                            upload_result.get("report_id"),
                            class_name,
                            subject_name,
                            period_type,
                            period_number,
                        )
                    print(
                        f"[DEBUG] Отчёт загружен: {class_name} {subject_name} "
                        f"-> ID {upload_result.get('report_id')} ({upload_result.get('action')})"
                    )
                elif upload_result.get("org_not_found"):
                    print(
                        f"[DEBUG] Сервер: организация не найдена. "
                        f"Отчёт сохранён только локально: {class_name} {subject_name}"
                    )
                    report_data["upload_skipped"] = True
                    report_data["upload_skip_reason"] = "org_not_found_server"
                elif upload_result.get("org_mismatch"):
                    print(
                        f"[DEBUG] Сервер: создание отчётов для других школ запрещено. "
                        f"Включите «Отчёты для других школ» в настройках: {class_name} {subject_name}"
                    )
                    report_data["upload_skipped"] = True
                    report_data["upload_skip_reason"] = "org_mismatch"
                else:
                    print(f"[DEBUG] Ошибка загрузки: {upload_result.get('error')}")
        except Exception as e:
            print(f"[DEBUG] Ошибка при загрузке на сервер: {e}")

        return report_data

    def _finalize_from_excel_files(
        self, final_reports_dir: Path, period_name: str
    ) -> List[Dict[str, Any]]:
        """Fallback: финализация из Excel файлов (когда batch-подпапок нет)."""
        reports: List[Dict[str, Any]] = []

        possible_dirs = [
            self.temp_dir / "reports",
            self.temp_dir / "batch",
            self.temp_dir,
        ]

        reports_dir: Optional[Path] = None
        for dir_path in possible_dirs:
            if dir_path.exists() and list(dir_path.glob("*.xlsx")):
                reports_dir = dir_path
                break

        if reports_dir is None:
            reports_dir = self.temp_dir

        excel_files = [
            f
            for f in reports_dir.glob("**/*.xlsx")
            if not f.stem.startswith("Шаблон") and "templates" not in str(f)
        ]

        for excel_file in excel_files:
            stem = excel_file.stem
            if "_" in stem or " " in stem:
                parts = stem.replace("_", " ").split(" ", 1)
                class_name = parts[0] if parts else "Unknown"
                subject = parts[1] if len(parts) > 1 else "Unknown"
            else:
                class_name = "Unknown"
                subject = stem

            final_excel = move_file(excel_file, final_reports_dir / excel_file.name)

            final_word = None
            word_file = excel_file.with_suffix(".docx")
            if word_file.exists():
                final_word = move_file(word_file, final_reports_dir / word_file.name)

            reports.append(
                {
                    "class_name": class_name,
                    "subject": subject,
                    "period_code": self.period_code,
                    "lang": self.lang,
                    "excel_path": str(final_excel.absolute()) if final_excel else None,
                    "word_path": str(final_word.absolute()) if final_word else None,
                    "metadata": {
                        "created_by": "desktop",
                        "output_dir": str(final_reports_dir),
                        "period_name": period_name,
                    },
                }
            )

        return reports

    def _build_grades_and_analytics(
        self, batch_subdir: Path
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], bool]:
        """
        Формирование grades_json и analytics_json из сырых JSON скрапера.

        Третий элемент кортежа — можно ли загружать оценки на сервер
        (есть секция СОЧ или колонки «Сумма%»/«Оценка» в criteria_context).

        Пороги оценок (как в build_report.py):
          ≥85% → 5,  65–84% → 4,  40–64% → 3,  <40% → 2
        """
        try:
            students_file = batch_subdir / "criteria_students.json"
            max_points_file = batch_subdir / "criteria_max_points.json"

            if not students_file.exists():
                return None, None, False

            with open(students_file, "r", encoding="utf-8") as f:
                students = json.load(f)

            if not students:
                return None, None, False

            max_points: Dict[int, int] = {}
            if max_points_file.exists():
                try:
                    with open(max_points_file, "r", encoding="utf-8") as f:
                        mp = json.load(f)
                    if isinstance(mp, dict):
                        max_points = {int(k): int(v) for k, v in mp.items()}
                except Exception:
                    pass

            quarter_num = int(students[0].get("quarter_num", 0)) if students else 0
            students_sorted = sorted(students, key=lambda s: int(s.get("num") or 0))

            grades_students: List[Dict[str, Any]] = []
            g5 = g4 = g3 = g2 = 0

            for s in students_sorted:
                name = (s.get("fio") or "").strip()
                if not name:
                    continue

                percent = parse_number(s.get("total_pct"))

                grade_int = None
                grade_raw = s.get("grade")
                if grade_raw is not None:
                    try:
                        grade_int = int(float(str(grade_raw).strip()))
                    except (ValueError, TypeError):
                        pass

                if grade_int:
                    if grade_int >= 5:
                        g5 += 1
                    elif grade_int >= 4:
                        g4 += 1
                    elif grade_int >= 3:
                        g3 += 1
                    else:
                        g2 += 1

                grades_students.append(
                    {
                        "name": name,
                        "percent": percent,
                        "grade": grade_int,
                    }
                )

            total = len(grades_students)
            grades_data = {
                "students": grades_students,
                "quality_percent": round((g5 + g4) / total * 100, 1) if total > 0 else 0,
                "success_percent": round((g5 + g4 + g3) / total * 100, 1) if total > 0 else 0,
                "total_students": total,
            }

            sections_present: set = set()
            prefix_base = f"chetvert_{quarter_num}_razdel_"

            for s in students_sorted:
                for pid in (s.get("points") or {}):
                    if isinstance(pid, str) and pid.startswith(prefix_base):
                        parts = pid.split("_")
                        if len(parts) >= 5:
                            try:
                                sections_present.add(int(parts[3]))
                            except ValueError:
                                pass

            sor_list: List[Dict[str, Any]] = []
            soch_data = None

            for sec in sorted(sections_present):
                if sec == 0 and not visible_soch_column(batch_subdir):
                    continue
                max_val = max_points.get(sec)
                if not max_val or max_val <= 0:
                    continue

                c5 = c4 = c3 = c2 = 0
                sec_prefix = f"chetvert_{quarter_num}_razdel_{sec}_"

                for s in students_sorted:
                    if not (s.get("fio") or "").strip():
                        continue

                    point_val = None
                    for pid, val in (s.get("points") or {}).items():
                        if isinstance(pid, str) and pid.startswith(sec_prefix):
                            try:
                                point_val = float(str(val).strip())
                            except (ValueError, TypeError):
                                pass

                    if point_val is not None:
                        pct = point_val / max_val * 100
                        if pct >= 85:
                            c5 += 1
                        elif pct >= 65:
                            c4 += 1
                        elif pct >= 40:
                            c3 += 1
                        else:
                            c2 += 1

                entry = {"count_5": c5, "count_4": c4, "count_3": c3, "count_2": c2}

                if sec == 0:
                    soch_data = entry
                else:
                    entry["name"] = f"СОр {sec}"
                    sor_list.append(entry)

            can_upload = can_upload_period_grades(batch_subdir)
            analytics_data = None
            if sor_list or soch_data:
                analytics_data = {}
                if sor_list:
                    analytics_data["sor"] = sor_list
                if soch_data:
                    analytics_data["soch"] = soch_data

            return grades_data, analytics_data, can_upload

        except Exception as e:
            print(f"[DEBUG] Ошибка формирования данных из JSON: {e}")
            return None, None, False

    def _save_report_metadata(
        self,
        excel_path: Path,
        server_report_id: int,
        class_name: str,
        subject_name: str,
        period_type: str,
        period_number: int,
    ) -> None:
        """Сохранение метаданных отчёта для синхронизации с сервером (.meta.json)."""
        try:
            meta_file = excel_path.with_suffix(".meta.json")
            meta_data = {
                "server_report_id": server_report_id,
                "class_name": class_name,
                "subject_name": subject_name,
                "period_type": period_type,
                "period_number": period_number,
                "org_name": self._scraped_org_name,
                "server_school_name": self._server_school_name,
                "uploaded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            with open(meta_file, "w", encoding="utf-8") as f:
                json.dump(meta_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[DEBUG] Ошибка сохранения метаданных: {e}")
