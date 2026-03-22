# Backend

FastAPI application package: `app/` (import as `app` with working directory set to this folder, e.g. `uvicorn app.main:app`).

- **`app/core/`** — RAG pipeline: `master_agent`, `ingestion`, `shared_retriever`, `legal_chunker`, `sync_incremental`, `ollama_config`.
- **`app/routes/`** — HTTP API routers.
- **`pdfs/`** — Source PDFs for incremental ingest.
- **`data/`** — Local manifest for sync (not committed).

Install: `pip install -r requirements.txt` (use the repo-root `.venv`).
