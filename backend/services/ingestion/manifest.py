import hashlib
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

MANIFEST_PATH = Path("backend/data/manifest.json")


def _load_manifest() -> dict[str, str]:
    if MANIFEST_PATH.exists():
        try:
            with open(MANIFEST_PATH, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not read manifest: {e}. Starting fresh.")
    return {}


def _save_manifest(manifest: dict[str, str]) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)


def compute_hash(pdf_path: Path) -> str:
    h = hashlib.sha256()
    with open(pdf_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def get_new_pdfs(pdf_dir: Path) -> list[Path]:
    """
    Return list of PDF paths that are new or have changed since last ingest.
    """
    manifest = _load_manifest()
    new_pdfs = []

    for pdf_path in sorted(pdf_dir.glob("*.pdf")):
        current_hash = compute_hash(pdf_path)
        if manifest.get(str(pdf_path)) != current_hash:
            new_pdfs.append(pdf_path)

    logger.info(f"Found {len(new_pdfs)} new/changed PDFs out of {len(list(pdf_dir.glob('*.pdf')))} total.")
    return new_pdfs


def mark_ingested(pdf_path: Path) -> None:
    manifest = _load_manifest()
    manifest[str(pdf_path)] = compute_hash(pdf_path)
    _save_manifest(manifest)
