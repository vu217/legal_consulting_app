"""Central settings loaded once from repo-root `.env`."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent

_env = REPO_ROOT / ".env"
if _env.exists():
    load_dotenv(_env)
else:
    load_dotenv()

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
COLLECTION = os.getenv("COLLECTION", "legal_cases")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
VECTOR_SIZE = int(os.getenv("VECTOR_SIZE", "768"))
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-r1:8b")
FAST_LLM_MODEL = os.getenv("FAST_LLM_MODEL", "llama3.1:8b")

PDF_DIR = Path(os.getenv("PDF_DIR", str(BACKEND_DIR / "pdfs"))).resolve()
MANIFEST_PATH = (BACKEND_DIR / "data" / "ingestion_manifest.json").resolve()

# Empty API_PREFIX in .env would mount routes at "" while the UI expects /api — normalize to /api.
_api_prefix_raw = os.getenv("API_PREFIX", "/api").strip()
API_PREFIX = _api_prefix_raw if _api_prefix_raw else "/api"
