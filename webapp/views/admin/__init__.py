from flask import Blueprint

bp = Blueprint("admin", __name__, url_prefix="/admin")

from . import exports, final_report, management, reports  # noqa: E402, F401
