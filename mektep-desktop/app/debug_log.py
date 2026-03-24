"""
Единый JSON-лог для отладки десктопа (гипотезы, UI, API, финализация отчётов).

Файл в корне репозитория: mektep-debug.log
"""
import json
import time
from pathlib import Path
from uuid import uuid4

# mektep-desktop/app/debug_log.py -> parents[2] = repo root
_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOG_PATH = _REPO_ROOT / "mektep-debug.log"
_SESSION_ID = "mektep-desktop"


def debug_log(
    hypothesis_id: str,
    location: str,
    message: str,
    data: dict,
    run_id: str = "initial",
) -> None:
    """Развёрнутая запись (id, runId) — для main_window, goals_dialog, reports_manager."""
    try:
        payload = {
            "sessionId": _SESSION_ID,
            "id": f"log_{int(time.time() * 1000)}_{uuid4().hex[:8]}",
            "timestamp": int(time.time() * 1000),
            "location": location,
            "message": message,
            "data": data,
            "runId": run_id,
            "hypothesisId": hypothesis_id,
        }
        with _LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass


def dbg_log(loc: str, msg: str, data: dict, hid: str) -> None:
    """Короткая запись для report_finalization и api_client (совместимость с прежним agent_log)."""
    try:
        payload = {
            "sessionId": _SESSION_ID,
            "location": loc,
            "message": msg,
            "data": data,
            "timestamp": int(time.time() * 1000),
            "hypothesisId": hid,
        }
        with _LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass
