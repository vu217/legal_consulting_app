"""Index / manifest statistics endpoint."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from qdrant_client import QdrantClient

from app import settings
from app.core.sync_incremental import _load_manifest

router = APIRouter(tags=["stats"])


@router.get("/index/stats")
async def index_stats() -> dict:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, compute_index_stats)


def compute_index_stats() -> dict[str, Any]:
    manifest = _load_manifest()
    pdfs: list[dict[str, Any]] = []
    total_chunks = 0

    for path_str, meta in manifest.items():
        if not isinstance(meta, dict):
            continue
        name = Path(path_str).name
        chunks = int(meta.get("chunks") or 0)
        err = meta.get("last_error")
        ok = err is None
        total_chunks += max(0, chunks)
        pdfs.append(
            {
                "path": path_str,
                "display_name": name,
                "chunks": chunks,
                "ok": ok,
                "last_error": str(err) if err else None,
            }
        )

    pdfs.sort(key=lambda x: x["display_name"].lower())

    out: dict[str, Any] = {
        "pdf_count": len(pdfs),
        "total_chunks": total_chunks,
        "pdfs": pdfs,
        "qdrant_vector_count": None,
    }

    try:
        client = QdrantClient(url=settings.QDRANT_URL, timeout=3)
        cols = [c.name for c in client.get_collections().collections]
        if settings.COLLECTION in cols:
            info = client.count(collection_name=settings.COLLECTION, exact=True)
            out["qdrant_vector_count"] = int(info.count)
    except Exception as e:
        out["qdrant_error"] = str(e)

    return out
