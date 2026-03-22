"""Health and dependency checks."""

from __future__ import annotations

import subprocess
from typing import Any

from fastapi import APIRouter
from qdrant_client import QdrantClient

from app import settings

router = APIRouter(tags=["health"])


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
        "ollama_models": [],
        "expected_models": {
            "llm": settings.LLM_MODEL,
            "fast_llm": settings.FAST_LLM_MODEL,
            "embed": settings.EMBED_MODEL,
        },
        "models_present": {},
    }

    try:
        client = QdrantClient(url=settings.QDRANT_URL)
        cols = [c.name for c in client.get_collections().collections]
        out["qdrant_ok"] = True
        out["collection_exists"] = settings.COLLECTION in cols
        out["collections"] = cols
    except Exception as e:
        out["qdrant_error"] = str(e)

    try:
        r = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=8)
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

    return out


@router.get("/config")
def public_config() -> dict[str, str]:
    return {
        "qdrant_url": settings.QDRANT_URL,
        "collection": settings.COLLECTION,
        "llm_model": settings.LLM_MODEL,
        "fast_llm_model": settings.FAST_LLM_MODEL,
        "embed_model": settings.EMBED_MODEL,
    }
