"""Append one NDJSON line per call for debug session (repo-root debug-bfe8eb.log)."""

from __future__ import annotations

import json
import time

from app.settings import REPO_ROOT

_LOG = REPO_ROOT / "debug-bfe8eb.log"
_SESSION = "bfe8eb"


def debug_log(
    hypothesis_id: str,
    location: str,
    message: str,
    data: dict | None = None,
    *,
    run_id: str = "pre-fix",
) -> None:
    # region agent log
    payload = {
        "sessionId": _SESSION,
        "runId": run_id,
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data or {},
        "timestamp": int(time.time() * 1000),
    }
    try:
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, default=str) + "\n")
    except OSError:
        pass
    # endregion
