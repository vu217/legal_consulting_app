"""PDF ingestion endpoints with size/type validation and case-file upload."""

from __future__ import annotations

from pathlib import Path
import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile

from app import settings
from app.core.ingestion import ingest_pdf
from app.core.sync_incremental import (
    _file_sha256,
    _manifest_read_body,
    _manifest_write_body,
    _manifest_lock,
    sync_pdfs_incremental,
)
from app.debug_session_log import debug_log

router = APIRouter(tags=["ingest"])

_PDF_MAGIC = b"%PDF"
_MAX_BYTES = settings.MAX_UPLOAD_MB * 1024 * 1024


def _validate_pdf_bytes(content: bytes, filename: str) -> None:
    if len(content) > _MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({len(content) / 1024 / 1024:.1f} MB). Max is {settings.MAX_UPLOAD_MB} MB.",
        )
    if not content[:4].startswith(_PDF_MAGIC):
        raise HTTPException(
            status_code=400,
            detail=f"'{filename}' is not a valid PDF (bad file header).",
        )


@router.post("/ingest/sync")
def ingest_sync() -> dict:
    try:
        out = sync_pdfs_incremental()
        debug_log(
            "H5", "ingest.py:ingest_sync", "http_sync_ok",
            {
                "ingested_or_attempted": out.get("ingested_or_attempted"),
                "skipped_unchanged": out.get("skipped_unchanged"),
            },
        )
        return out
    except Exception as e:
        debug_log("H5", "ingest.py:ingest_sync", "http_sync_error", {"exc_type": type(e).__name__})
        raise HTTPException(status_code=500, detail=f"Sync failed: {e!s}") from e


@router.post("/ingest/upload")
async def ingest_upload(file: UploadFile = File(...)) -> dict:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Expected a .pdf file")
    settings.PDF_DIR.mkdir(parents=True, exist_ok=True)

    content = await file.read()
    _validate_pdf_bytes(content, file.filename or "upload")

    safe_name = Path(file.filename).name
    dest = settings.PDF_DIR / f"{uuid.uuid4().hex}_{safe_name}"
    try:
        dest.write_bytes(content)
        n = ingest_pdf(str(dest))
        key = str(dest.resolve())
        with _manifest_lock:
            manifest = _manifest_read_body()
            manifest[key] = {
                "sha256": _file_sha256(dest),
                "chunks": n,
                "mtime": dest.stat().st_mtime,
            }
            _manifest_write_body(manifest)
        return {"file": str(dest), "chunks": n, "status": "ok"}
    except Exception as e:
        if dest.exists():
            dest.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Ingest failed: {e!s}") from e


@router.post("/ingest/case-upload")
async def ingest_case_files(files: list[UploadFile] = File(...)) -> dict:
    """
    Upload case-specific PDFs. These are ingested with source_type='case_file' metadata
    and can be referenced in analysis requests via their file_ids.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    settings.CASE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    results = []

    for file in files:
        if not file.filename or not file.filename.lower().endswith(".pdf"):
            results.append({"filename": file.filename or "unknown", "status": "error", "detail": "Not a PDF"})
            continue

        content = await file.read()
        try:
            _validate_pdf_bytes(content, file.filename or "upload")
        except HTTPException as e:
            results.append({"filename": file.filename, "status": "error", "detail": e.detail})
            continue

        file_id = uuid.uuid4().hex
        safe_name = Path(file.filename).name
        dest = settings.CASE_UPLOAD_DIR / f"{file_id}_{safe_name}"

        try:
            dest.write_bytes(content)
            n = ingest_pdf(str(dest))
            results.append({
                "filename": safe_name,
                "file_id": file_id,
                "chunks": n,
                "status": "ok",
            })
        except Exception as e:
            if dest.exists():
                dest.unlink(missing_ok=True)
            results.append({"filename": safe_name, "status": "error", "detail": str(e)})

    ok_count = sum(1 for r in results if r.get("status") == "ok")
    return {"uploaded": ok_count, "total": len(files), "results": results}
