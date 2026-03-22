"""Ingest only PDFs that are new or changed (SHA-256 vs manifest)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app import settings
from app.core.ingestion import ingest_single_pdf
from app.debug_session_log import debug_log


def _load_manifest() -> dict:
    if not settings.MANIFEST_PATH.exists():
        return {}
    try:
        return json.loads(settings.MANIFEST_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_manifest(data: dict) -> None:
    settings.MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    settings.MANIFEST_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sync_pdfs_incremental() -> dict:
    """
    Ingest PDFs under PDF_DIR when file is missing from manifest or content hash changed.
    """
    settings.PDF_DIR.mkdir(parents=True, exist_ok=True)
    manifest = _load_manifest()
    pdf_files = sorted(settings.PDF_DIR.glob("*.pdf"))
    # region agent log
    debug_log(
        "H5",
        "sync_incremental.py:sync_pdfs_incremental",
        "sync_start",
        {"pdf_count": len(pdf_files), "manifest_keys": len(manifest)},
    )
    # endregion
    results: list[dict] = []
    to_run: list[tuple[Path, str, str]] = []

    for pdf in pdf_files:
        key = str(pdf.resolve())
        digest = _file_sha256(pdf)
        prev = manifest.get(key, {})
        if isinstance(prev, dict) and prev.get("sha256") == digest:
            reason = "unchanged_error" if "last_error" in prev else "unchanged"
            results.append(
                {
                    "file": key,
                    "status": "skipped",
                    "chunks": prev.get("chunks", 0),
                    "reason": reason,
                }
            )
            continue
        to_run.append((pdf, digest, key))

    # Sequential ingest avoids Qdrant / manifest races.
    # Manifest is written after EACH pdf so a mid-run crash (e.g. CUDA OOM) does not
    # discard progress already completed.
    for pdf, digest, key in to_run:
        r = ingest_single_pdf(str(pdf), replace_existing=True)
        results.append(r)
        if r.get("status") == "ok":
            manifest[key] = {
                "sha256": digest,
                "chunks": r.get("chunks", 0),
                "mtime": pdf.stat().st_mtime,
            }
        elif r.get("status") == "skipped":
            manifest[key] = {"sha256": digest, "chunks": 0, "mtime": pdf.stat().st_mtime}
        else:
            # Record the error so the same unchanged file is not retried every startup.
            # The entry is cleared and retried if the file content changes.
            manifest[key] = {
                "sha256": digest,
                "chunks": 0,
                "mtime": pdf.stat().st_mtime,
                "last_error": r.get("reason", "unknown"),
            }
        _save_manifest(manifest)
    skipped_count = sum(1 for r in results if r.get("status") == "skipped" and r.get("reason") == "unchanged")
    err_statuses = [r.get("status") for r in results if r.get("status") == "error"]
    # region agent log
    debug_log(
        "H5",
        "sync_incremental.py:sync_pdfs_incremental",
        "sync_end",
        {
            "ingested_or_attempted": len(to_run),
            "skipped_unchanged": skipped_count,
            "error_count": len(err_statuses),
        },
    )
    # endregion
    return {
        "pdf_dir": str(settings.PDF_DIR),
        "ingested_or_attempted": len(to_run),
        "skipped_unchanged": skipped_count,
        "results": results,
    }


if __name__ == "__main__":
    import json

    print(json.dumps(sync_pdfs_incremental(), indent=2))
