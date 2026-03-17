import json
import time
from pathlib import Path
from uuid import uuid4


_DEBUG_LOG_PATH = Path(__file__).resolve().parents[2] / "debug-91cc02.log"
_SESSION_ID = "91cc02"


def debug_log(hypothesis_id: str, location: str, message: str, data: dict, run_id: str = "initial") -> None:
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
        with _DEBUG_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass
