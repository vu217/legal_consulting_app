"""Health and dependency checks."""

from __future__ import annotations

import subprocess
import urllib.error
import urllib.request
from typing import Any

from fastapi import APIRouter
from qdrant_client import QdrantClient

from app import settings
from app.debug_session_log import debug_log
from app.routes.stats import compute_index_stats

router = APIRouter(tags=["health"])

OLLAMA_TAGS_URL = "http://127.0.0.1:11434/api/tags"


def _probe_ollama_api() -> bool:
    try:
        with urllib.request.urlopen(OLLAMA_TAGS_URL, timeout=2) as resp:
            return 200 <= int(resp.status) < 300
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/dependencies")
def health_dependencies() -> dict[str, Any]:
    out: dict[str, Any] = {
        "qdrant_url": settings.QDRANT_URL,
        "collection": settings.COLLECTION,
        "qdrant_ok": False,
        "collection_exists": False,
        "ollama_ok": False,
        "ollama_api_ok": False,
        "ollama_models": [],
        "expected_models": {
            "llm": settings.LLM_MODEL,
            "fast_llm": settings.FAST_LLM_MODEL,
            "embed": settings.EMBED_MODEL,
        },
        "models_present": {},
    }

    out["ollama_api_ok"] = _probe_ollama_api()

    try:
        client = QdrantClient(url=settings.QDRANT_URL, timeout=3)
        cols = [c.name for c in client.get_collections().collections]
        out["qdrant_ok"] = True
        out["collection_exists"] = settings.COLLECTION in cols
        out["collections"] = cols
    except Exception as e:
        out["qdrant_error"] = str(e)

    try:
        r = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=3)
        out["ollama_ok"] = r.returncode == 0
        lines = [ln.strip() for ln in r.stdout.splitlines() if ln.strip()][1:]
        names = [ln.split()[0] for ln in lines if ln]
        out["ollama_models"] = names
        base_llm = settings.LLM_MODEL.split(":")[0]
        base_fast = settings.FAST_LLM_MODEL.split(":")[0]
        base_emb = settings.EMBED_MODEL.split(":")[0]
        out["models_present"] = {
            "llm": any(base_llm == m.split(":")[0] for m in names),
            "fast_llm": any(base_fast == m.split(":")[0] for m in names),
            "embed": any(base_emb == m.split(":")[0] for m in names),
        }
    except Exception as e:
        out["ollama_error"] = str(e)

    # region agent log
    debug_log(
        "H2",
        "health.py:health_dependencies",
        "deps_snapshot",
        {
            "qdrant_ok": out.get("qdrant_ok"),
            "collection_exists": out.get("collection_exists"),
            "ollama_ok": out.get("ollama_ok"),
            "ollama_api_ok": out.get("ollama_api_ok"),
            "models_present": out.get("models_present"),
            "has_qdrant_error": "qdrant_error" in out,
            "has_ollama_error": "ollama_error" in out,
        },
    )
    # endregion
    return out


@router.get("/config")
def public_config() -> dict[str, str]:
    cfg = {
        "qdrant_url": settings.QDRANT_URL,
        "collection": settings.COLLECTION,
        "llm_model": settings.LLM_MODEL,
        "fast_llm_model": settings.FAST_LLM_MODEL,
        "embed_model": settings.EMBED_MODEL,
    }
    # region agent log
    debug_log(
        "H4",
        "health.py:public_config",
        "config_served",
        {"collection": settings.COLLECTION, "llm_model": settings.LLM_MODEL},
    )
    # endregion
    return cfg


@router.get("/index/stats", tags=["stats"])
def index_stats() -> dict[str, Any]:
    return compute_index_stats()
