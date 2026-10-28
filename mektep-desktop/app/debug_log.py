"""
Единый JSON-лог для отладки десктопа (гипотезы, UI, API, финализация отчётов).

По умолчанию отключён, чтобы не создавать mektep-debug.log в рабочей директории.
Для включения задайте переменную окружения MEKTEP_DEBUG_LOG=1.
"""
import json
import os
import time
from pathlib import Path
from uuid import uuid4

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOG_PATH = _REPO_ROOT / "mektep-debug.log"
_SESSION_ID = "mektep-desktop"


def _is_enabled() -> bool:
    return os.getenv("MEKTEP_DEBUG_LOG", "").strip().lower() in ("1", "true", "yes")


def debug_log(
    hypothesis_id: str,
    location: str,
    message: str,
    data: dict,
    run_id: str = "initial",
) -> None:
    """Развёрнутая запись (id, runId) — активна только при MEKTEP_DEBUG_LOG=1."""
    if not _is_enabled():
        return
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
    """Короткая запись — активна только при MEKTEP_DEBUG_LOG=1."""
    if not _is_enabled():
        return
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
