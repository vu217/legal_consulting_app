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
CASE_UPLOAD_DIR = Path(os.getenv("CASE_UPLOAD_DIR", str(BACKEND_DIR / "case_uploads"))).resolve()
MANIFEST_PATH = (BACKEND_DIR / "data" / "ingestion_manifest.json").resolve()

MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))
ENABLE_PARALLEL_AGENTS = os.getenv("ENABLE_PARALLEL_AGENTS", "").strip().lower() in ("1", "true", "yes")

_api_prefix_raw = os.getenv("API_PREFIX", "/api").strip()
API_PREFIX = _api_prefix_raw if _api_prefix_raw else "/api"

VALID_COURT_TYPES = frozenset({
    "supreme_court", "high_court", "district_court", "sessions_court",
    "tribunal", "consumer_forum", "family_court", "other",
})
VALID_CASE_TYPES = frozenset({
    "criminal", "civil", "constitutional", "family",
    "commercial", "tax", "labor", "other",
})
