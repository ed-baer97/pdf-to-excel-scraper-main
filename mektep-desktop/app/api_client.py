"""
API Client для связи с сервером Mektep Platform

Минимальный HTTP клиент для проверки квоты и логирования отчетов.
"""
import requests
from typing import Optional, Dict, List
from datetime import datetime, timedelta


class MektepAPIClient:
    """HTTP клиент для API сервера"""
    
    def __init__(self, base_url: str = "http://localhost:5000"):
        """
        Инициализация клиента
        
        Args:
            base_url: Базовый URL сервера (по умолчанию localhost)
        """
        self.base_url = base_url.rstrip("/")
        self.token: Optional[str] = None
        self.token_expires: Optional[datetime] = None
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mektep-Desktop/1.0",
            "Content-Type": "application/json"
        })
    
    def _is_token_valid(self) -> bool:
        """Проверка валидности токена"""
        if not self.token or not self.token_expires:
            return False
        return datetime.now() < self.token_expires
    
    def _set_auth_header(self):
        """Установка заголовка авторизации"""
        if self.token:
            self.session.headers["Authorization"] = f"Bearer {self.token}"
        elif "Authorization" in self.session.headers:
            del self.session.headers["Authorization"]
    
    def login(self, username: str, password: str) -> Dict:
        """
        Авторизация на сервере
        
        Args:
            username: Имя пользователя (логин веб-приложения)
            password: Пароль
        
        Returns:
            dict: {"success": bool, "token": str, "expires_in": int, "user": dict}
        
        Raises:
            requests.RequestException: Ошибка сетевого запроса
        """
        try:
            response = self.session.post(
                f"{self.base_url}/api/auth/login",
                json={"username": username, "password": password},
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                self.token = data.get("token")
                expires_in = data.get("expires_in", 2592000)  # 30 days default
                self.token_expires = datetime.now() + timedelta(seconds=expires_in)
                self._set_auth_header()
                
                return {
                    "success": True,
                    "token": self.token,
                    "expires_in": expires_in,
                    "user": data.get("user", {})
                }
            else:
                return {
                    "success": False,
                    "error": response.json().get("error", "Неизвестная ошибка"),
                    "status_code": response.status_code
                }
        except requests.exceptions.ConnectionError:
            return {
                "success": False,
                "error": "Не удалось подключиться к серверу. Проверьте подключение к интернету.",
                "offline": True
            }
        except requests.exceptions.Timeout:
            return {
                "success": False,
                "error": "Превышено время ожидания ответа от сервера"
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Ошибка: {str(e)}"
            }
    
    def log_reports(self, reports: List[Dict]) -> Dict:
        """
        Отправка метаданных созданных отчетов на сервер
        
        Args:
            reports: Список отчетов с метаданными:
                [
                    {
                        "class": "9А",
                        "subject": "Математика",
                        "period": "2",
                        "timestamp": "2024-01-15T10:30:00",
                        "has_excel": True,
                        "has_word": True
                    },
                    ...
                ]
        
        Returns:
            dict: {"success": bool, "logged_count": int}
        """
        if not self._is_token_valid():
            return {
                "success": False,
                "error": "Токен недействителен. Требуется повторная авторизация."
            }
        
        try:
            self._set_auth_header()
            response = self.session.post(
                f"{self.base_url}/api/reports/log",
                json={"reports": reports},
                timeout=15
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "logged_count": data.get("count", len(reports))
                }
            elif response.status_code == 401:
                self.token = None
                self.token_expires = None
                return {
                    "success": False,
                    "error": "Токен истек. Требуется повторная авторизация.",
                    "needs_auth": True
                }
            else:
                return {
                    "success": False,
                    "error": response.json().get("error", "Ошибка логирования отчетов"),
                    "status_code": response.status_code
                }
        except requests.exceptions.ConnectionError:
            # В автономном режиме просто сохраняем локально
            return {
                "success": True,
                "logged_count": 0,
                "offline": True,
                "message": "Отчеты сохранены локально (нет подключения к серверу)"
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Ошибка: {str(e)}"
            }
    
    def refresh_token(self) -> Dict:
        """
        Обновление токена авторизации
        
        Returns:
            dict: {"success": bool, "token": str}
        """
        if not self.token:
            return {
                "success": False,
                "error": "Нет токена для обновления"
            }
        
        try:
            self._set_auth_header()
            response = self.session.post(
                f"{self.base_url}/api/auth/refresh",
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                self.token = data.get("token")
                expires_in = data.get("expires_in", 2592000)
                self.token_expires = datetime.now() + timedelta(seconds=expires_in)
                self._set_auth_header()
                
                return {
                    "success": True,
                    "token": self.token,
                    "expires_in": expires_in
                }
            else:
                self.token = None
                self.token_expires = None
                return {
                    "success": False,
                    "error": "Не удалось обновить токен",
                    "needs_auth": True
                }
        except Exception as e:
            return {
                "success": False,
                "error": f"Ошибка: {str(e)}"
            }
    
    def logout(self):
        """Выход из системы (очистка токена)"""
        self.token = None
        self.token_expires = None
        self._set_auth_header()
    
    def is_authenticated(self) -> bool:
        """Проверка, авторизован ли пользователь"""
        return self._is_token_valid()
    
    # ==========================================================================
    # School Info API (школа текущего пользователя)
    # ==========================================================================
    
    def get_my_school(self) -> Dict:
        """
        Получение информации о школе текущего пользователя.
        
        Возвращает название школы и флаг allow_cross_school_reports.
        Используется для проверки организации перед скрапингом.
        
        Returns:
            dict: {
                "success": bool,
                "school_name": str | None,
                "allow_cross_school_reports": bool
            }
        """
        if not self._is_token_valid():
            return {
                "success": False,
                "error": "Токен недействителен."
            }
        
        try:
            self._set_auth_header()
            response = self.session.get(
                f"{self.base_url}/api/schools/my",
                timeout=10
            )
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 401:
                self.token = None
                self.token_expires = None
                return {"success": False, "error": "Токен истек.", "needs_auth": True}
            else:
                return {"success": False, "error": response.json().get("error", "Ошибка")}
        except requests.exceptions.ConnectionError:
            return {"success": False, "error": "Нет подключения к серверу", "offline": True}
        except Exception as e:
            return {"success": False, "error": f"Ошибка: {str(e)}"}
    
    # ==========================================================================
    # School Lookup API
    # ==========================================================================
    
    def lookup_school(self, org_name: str) -> Dict:
        """
        Поиск школы по названию организации.
        
        Проверяет, есть ли организация учителя (из mektep.edu.kz) в базе
        данных сервера. Используется перед загрузкой отчётов для определения,
        к какой школе привязать данные.
        
        Args:
            org_name: Название организации (как на mektep.edu.kz)
        
        Returns:
            dict: {"success": bool, "school_id": int, "school_name": str}
                  или {"success": False, "error": str, "org_not_found": True}
        """
        if not self._is_token_valid():
            return {
                "success": False,
                "error": "Токен недействителен. Требуется повторная авторизация."
            }
        
        try:
            self._set_auth_header()
            response = self.session.get(
                f"{self.base_url}/api/schools/lookup",
                params={"org_name": org_name},
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "school_id": data.get("school_id"),
                    "school_name": data.get("school_name")
                }
            elif response.status_code == 404:
                return {
                    "success": False,
                    "error": response.json().get("error", "Организация не найдена"),
                    "org_not_found": True
                }
            elif response.status_code == 401:
                self.token = None
                self.token_expires = None
                return {
                    "success": False,
                    "error": "Токен истек. Требуется повторная авторизация.",
                    "needs_auth": True
                }
            else:
                return {
                    "success": False,
                    "error": response.json().get("error", "Ошибка поиска школы"),
                    "status_code": response.status_code
                }
        except requests.exceptions.ConnectionError:
            return {
                "success": False,
                "error": "Не удалось подключиться к серверу",
                "offline": True
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Ошибка: {str(e)}"
            }
    
    # ==========================================================================
    # Grade Reports API
    # ==========================================================================
    
    def upload_report(
        self,
        class_name: str,
        subject_name: str,
        period_type: str,
        period_number: int,
        grades_data: Optional[Dict] = None,
        analytics_data: Optional[Dict] = None,
        org_name: Optional[str] = None
    ) -> Dict:
        """
        Загрузка/обновление отчёта с оценками на сервер (UPSERT)
        
        Args:
            class_name: Название класса ("7А")
            subject_name: Название предмета ("Математика")
            period_type: Тип периода ("quarter" или "semester")
            period_number: Номер периода (1-4 для четверти, 1-2 для полугодия)
            grades_data: Данные оценок
            analytics_data: Данные аналитики СОР/СОЧ
            org_name: Название организации из mektep.edu.kz (для привязки к школе в БД)
        
        Returns:
            dict: {"success": bool, "report_id": int, "action": "created"|"updated"}
        """
        if not self._is_token_valid():
            return {
                "success": False,
                "error": "Токен недействителен. Требуется повторная авторизация."
            }
        
        try:
            self._set_auth_header()
            
            payload = {
                "class_name": class_name,
                "subject_name": subject_name,
                "period_type": period_type,
                "period_number": period_number,
            }
            
            if grades_data:
                payload["grades_json"] = grades_data
            if analytics_data:
                payload["analytics_json"] = analytics_data
            if org_name:
                payload["org_name"] = org_name
            
            response = self.session.post(
                f"{self.base_url}/api/reports/upload",
                json=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "report_id": data.get("report_id"),
                    "action": data.get("action")
                }
            elif response.status_code == 401:
                self.token = None
                self.token_expires = None
                return {
                    "success": False,
                    "error": "Токен истек. Требуется повторная авторизация.",
                    "needs_auth": True
                }
            elif response.status_code == 404:
                return {
                    "success": False,
                    "error": response.json().get("error", "Организация не найдена"),
                    "org_not_found": response.json().get("org_not_found", False)
                }
            else:
                return {
                    "success": False,
                    "error": response.json().get("error", "Ошибка загрузки отчёта"),
                    "status_code": response.status_code
                }
        except requests.exceptions.ConnectionError:
            return {
                "success": False,
                "error": "Не удалось подключиться к серверу",
                "offline": True
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Ошибка: {str(e)}"
            }
    
    def delete_all_reports(self) -> Dict:
        """
        Удаление ВСЕХ отчётов текущего учителя с сервера
        
        Удаляет все GradeReport и ReportFile.
        
        Returns:
            dict: {"success": bool, "deleted_grade_reports": int, "deleted_report_files": int}
        """
        if not self._is_token_valid():
            return {
                "success": False,
                "error": "Токен недействителен. Требуется повторная авторизация."
            }
        
        try:
            self._set_auth_header()
            response = self.session.delete(
                f"{self.base_url}/api/reports/all",
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "deleted_grade_reports": data.get("deleted_grade_reports", 0),
                    "deleted_report_files": data.get("deleted_report_files", 0),
                }
            elif response.status_code == 401:
                self.token = None
                self.token_expires = None
                return {
                    "success": False,
                    "error": "Токен истек. Требуется повторная авторизация.",
                    "needs_auth": True
                }
            else:
                return {
                    "success": False,
                    "error": response.json().get("error", "Ошибка удаления отчётов"),
                    "status_code": response.status_code
                }
        except requests.exceptions.ConnectionError:
            return {
                "success": False,
                "error": "Не удалось подключиться к серверу",
                "offline": True
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Ошибка: {str(e)}"
            }
    
    def delete_report(self, report_id: int) -> Dict:
        """
        Удаление отчёта с сервера
        
        Args:
            report_id: ID отчёта для удаления
        
        Returns:
            dict: {"success": bool}
        """
        if not self._is_token_valid():
            return {
                "success": False,
                "error": "Токен недействителен. Требуется повторная авторизация."
            }
        
        try:
            self._set_auth_header()
            response = self.session.delete(
                f"{self.base_url}/api/reports/{report_id}",
                timeout=15
            )
            
            if response.status_code == 200:
                return {"success": True}
            elif response.status_code == 401:
                self.token = None
                self.token_expires = None
                return {
                    "success": False,
                    "error": "Токен истек. Требуется повторная авторизация.",
                    "needs_auth": True
                }
            elif response.status_code == 403:
                return {
                    "success": False,
                    "error": "Нет прав для удаления этого отчёта"
                }
            elif response.status_code == 404:
                return {
                    "success": False,
                    "error": "Отчёт не найден"
                }
            else:
                return {
                    "success": False,
                    "error": response.json().get("error", "Ошибка удаления отчёта"),
                    "status_code": response.status_code
                }
        except requests.exceptions.ConnectionError:
            return {
                "success": False,
                "error": "Не удалось подключиться к серверу",
                "offline": True
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Ошибка: {str(e)}"
            }
    
    def get_my_reports(
        self,
        period_type: Optional[str] = None,
        period_number: Optional[int] = None
    ) -> Dict:
        """
        Получение списка своих отчётов
        
        Args:
            period_type: Фильтр по типу периода ("quarter" или "semester")
            period_number: Фильтр по номеру периода
        
        Returns:
            dict: {
                "success": bool,
                "reports": [
                    {
                        "id": 123,
                        "class_name": "7А",
                        "subject_name": "Математика",
                        "period_type": "quarter",
                        "period_number": 2,
                        "created_at": "2024-01-15T10:30:00",
                        "updated_at": "2024-01-16T12:00:00"
                    },
                    ...
                ]
            }
        """
        if not self._is_token_valid():
            return {
                "success": False,
                "error": "Токен недействителен. Требуется повторная авторизация."
            }
        
        try:
            self._set_auth_header()
            
            params = {}
            if period_type:
                params["period_type"] = period_type
            if period_number:
                params["period_number"] = period_number
            
            response = self.session.get(
                f"{self.base_url}/api/reports/my",
                params=params,
                timeout=15
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "reports": data.get("reports", [])
                }
            elif response.status_code == 401:
                self.token = None
                self.token_expires = None
                return {
                    "success": False,
                    "error": "Токен истек. Требуется повторная авторизация.",
                    "needs_auth": True
                }
            else:
                return {
                    "success": False,
                    "error": response.json().get("error", "Ошибка получения отчётов"),
                    "status_code": response.status_code
                }
        except requests.exceptions.ConnectionError:
            return {
                "success": False,
                "error": "Не удалось подключиться к серверу",
                "offline": True
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Ошибка: {str(e)}"
            }
    
    def get_my_classes(self) -> Dict:
        """
        Получение классов и предметов учителя
        
        Returns:
            dict: {
                "success": bool,
                "subjects": [{"subject_name": "...", "classes": [...]}],
                "managed_classes": ["7А", ...]
            }
        """
        if not self._is_token_valid():
            return {"success": False, "error": "Токен недействителен.", "needs_auth": True}
        
        try:
            self._set_auth_header()
            response = self.session.get(
                f"{self.base_url}/api/teacher/my-classes",
                timeout=15
            )
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 401:
                self.token = None
                self.token_expires = None
                return {"success": False, "error": "Токен истек.", "needs_auth": True}
            else:
                return {"success": False, "error": response.json().get("error", "Ошибка")}
        except requests.exceptions.ConnectionError:
            return {"success": False, "error": "Нет подключения к серверу", "offline": True}
        except Exception as e:
            return {"success": False, "error": f"Ошибка: {str(e)}"}
    
    def get_subject_report(
        self,
        period_type: str = "quarter",
        period_number: int = 2
    ) -> Dict:
        """
        Отчёт предметника: статистика оценок по предметам и классам
        
        Returns:
            dict: {"success": bool, "subjects": [...]}
        """
        if not self._is_token_valid():
            return {"success": False, "error": "Токен недействителен.", "needs_auth": True}
        
        try:
            self._set_auth_header()
            response = self.session.get(
                f"{self.base_url}/api/teacher/subject-report",
                params={"period_type": period_type, "period_number": period_number},
                timeout=30
            )
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 401:
                self.token = None
                self.token_expires = None
                return {"success": False, "error": "Токен истек.", "needs_auth": True}
            else:
                return {"success": False, "error": response.json().get("error", "Ошибка")}
        except requests.exceptions.ConnectionError:
            return {"success": False, "error": "Нет подключения к серверу", "offline": True}
        except Exception as e:
            return {"success": False, "error": f"Ошибка: {str(e)}"}
    
    def get_class_teacher_report(
        self,
        period_type: str = "quarter",
        period_number: int = 2
    ) -> Dict:
        """
        Отчёт классного руководителя: категоризация учеников
        
        Returns:
            dict: {"success": bool, "classes": [...]}
        """
        if not self._is_token_valid():
            return {"success": False, "error": "Токен недействителен.", "needs_auth": True}
        
        try:
            self._set_auth_header()
            response = self.session.get(
                f"{self.base_url}/api/teacher/class-teacher-report",
                params={"period_type": period_type, "period_number": period_number},
                timeout=30
            )
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 401:
                self.token = None
                self.token_expires = None
                return {"success": False, "error": "Токен истек.", "needs_auth": True}
            else:
                return {"success": False, "error": response.json().get("error", "Ошибка")}
        except requests.exceptions.ConnectionError:
            return {"success": False, "error": "Нет подключения к серверу", "offline": True}
        except Exception as e:
            return {"success": False, "error": f"Ошибка: {str(e)}"}
    
    def get_class_grades(
        self,
        class_name: str,
        period_type: str = "quarter",
        period_number: int = 2
    ) -> Dict:
        """
        Получение сводной таблицы оценок класса
        
        Args:
            class_name: Название класса ("7А")
            period_type: Тип периода ("quarter" или "semester")
            period_number: Номер периода
        
        Returns:
            dict: {
                "success": bool,
                "class_name": "7А",
                "period_type": "quarter",
                "period_number": 2,
                "subjects": ["Математика", "Физика", ...],
                "students": [
                    {
                        "name": "Иванов Иван",
                        "grades": {
                            "Математика": {"percent": 85.5, "grade": 4},
                            ...
                        }
                    },
                    ...
                ],
                "summary": {
                    "total_students": 25,
                    "quality_percent": 66.7,
                    "success_percent": 100.0
                }
            }
        """
        if not self._is_token_valid():
            return {
                "success": False,
                "error": "Токен недействителен. Требуется повторная авторизация."
            }
        
        try:
            self._set_auth_header()
            
            # URL encode class_name для безопасности
            import urllib.parse
            encoded_class = urllib.parse.quote(class_name, safe='')
            
            response = self.session.get(
                f"{self.base_url}/api/grades/class/{encoded_class}",
                params={
                    "period_type": period_type,
                    "period_number": period_number
                },
                timeout=30
            )
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 401:
                self.token = None
                self.token_expires = None
                return {
                    "success": False,
                    "error": "Токен истек. Требуется повторная авторизация.",
                    "needs_auth": True
                }
            else:
                return {
                    "success": False,
                    "error": response.json().get("error", "Ошибка получения данных класса"),
                    "status_code": response.status_code
                }
        except requests.exceptions.ConnectionError:
            return {
                "success": False,
                "error": "Не удалось подключиться к серверу",
                "offline": True
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Ошибка: {str(e)}"
            }
