# legal_consulting_app

Local legal RAG stack: **React (Vite)** in `frontend/`, **FastAPI** in `backend/`, **Qdrant** via Docker, **Ollama** on the host.

## Quick start

1. **Python:** `python -m venv .venv` at the repo root, then  
   `.venv\Scripts\pip install -r backend\requirements.txt` (Windows) or  
   `.venv/bin/pip install -r backend/requirements.txt` (macOS/Linux).

2. **Run everything** from the repo root: **`npm run dev`**  
   - Starts **Docker Compose** (Qdrant), **FastAPI** on **http://localhost:8000**, incremental ingest for **`backend/pdfs/`**, **Vite** on **http://localhost:5173**.  
   - If `frontend/node_modules` is missing, the script installs frontend deps first.

3. **Ollama** must be running with models from `.env` (e.g. `nomic-embed-text`, `deepseek-r1:8b`, `llama3.1:8b`). Use **`OLLAMA_USE_CPU=1`** in `.env` if GPU/CUDA fails.

## Repo layout

| Path | Purpose |
|------|---------|
| `frontend/` | React app; API base URL via `VITE_API_BASE` (see `frontend/.env.example`). |
| `backend/app/` | FastAPI app: `main.py`, `settings.py`, `routes/`, `core/` (RAG, ingest, chunker). |
| `backend/pdfs/` | Drop PDFs here for ingestion (or upload in the UI). |
| `backend/data/` | Ingest manifest (generated; gitignored). |
| `scripts/dev.js` | One-command dev orchestration (`npm run dev`). |
| `docker-compose.yml` | Qdrant service; data in `qdrant_storage/`. |
| `.env` | Repo root; loaded by `backend/app/settings.py`. |

Optional: if you keep a root `pdfs/` folder, `npm run dev` copies any new `.pdf` files into `backend/pdfs` once.
