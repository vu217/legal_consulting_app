"""PDF ingestion endpoints."""

from __future__ import annotations

from pathlib import Path
import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile

from app import settings
from app.core.ingestion import ingest_pdf
from app.core.sync_incremental import sync_pdfs_incremental
from app.debug_session_log import debug_log

router = APIRouter(tags=["ingest"])


@router.post("/ingest/sync")
def ingest_sync() -> dict:
    try:
        out = sync_pdfs_incremental()
        # region agent log
        debug_log(
            "H5",
            "ingest.py:ingest_sync",
            "http_sync_ok",
            {
                "ingested_or_attempted": out.get("ingested_or_attempted"),
                "skipped_unchanged": out.get("skipped_unchanged"),
            },
        )
        # endregion
        return out
    except Exception as e:
        # region agent log
        debug_log(
            "H5",
            "ingest.py:ingest_sync",
            "http_sync_error",
            {"exc_type": type(e).__name__},
        )
        # endregion
        raise HTTPException(status_code=500, detail=f"Sync failed: {e!s}") from e


@router.post("/ingest/upload")
async def ingest_upload(file: UploadFile = File(...)) -> dict:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Expected a .pdf file")
    settings.PDF_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename).name
    dest = settings.PDF_DIR / f"{uuid.uuid4().hex}_{safe_name}"
    try:
        content = await file.read()
        dest.write_bytes(content)
        n = ingest_pdf(str(dest))
        return {"file": str(dest), "chunks": n, "status": "ok"}
    except Exception as e:
        if dest.exists():
            dest.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Ingest failed: {e!s}") from e
