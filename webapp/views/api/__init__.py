"""REST API для Mektep Desktop (JWT-авторизация, отчёты, кабинет учителя).

HTTP-слой разбит на тематические модули; бизнес-логика живёт в webapp/services
(report_upload, teacher_cabinet, api_helpers).
"""

from flask import Blueprint

bp = Blueprint("api", __name__, url_prefix="/api")

# Импорт модулей регистрирует маршруты на blueprint.
from . import auth, grades, reports, schools, teacher  # noqa: E402,F401
