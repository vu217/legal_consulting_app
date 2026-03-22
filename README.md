# legal_consulting_app

Local legal RAG stack: **React (Vite)** frontend, **FastAPI** backend, **Qdrant** (Docker), **Ollama** on the host.

## Quick start

1. Create a virtualenv at the repo root and install backend deps:

   `python -m venv .venv` then  
   `.venv\Scripts\pip install -r backend\requirements.txt` (Windows) or  
   `.venv/bin/pip install -r backend/requirements.txt` (macOS/Linux).

2. Install root + frontend deps: `npm install` in `frontend/` (or rely on `npm run dev`, which installs `frontend` if needed).

3. From the repo root: **`npm run dev`**

   This starts **Docker Compose** (Qdrant), the **FastAPI** app on port **8000**, runs **incremental PDF ingest** for `backend/pdfs/` (and copies any `pdfs/*.pdf` from the repo root into `backend/pdfs` once), then **Vite** on **http://localhost:5173**.

4. Ensure **Ollama** is running with models matching `.env` (e.g. `nomic-embed-text`, `deepseek-r1:8b`, `llama3.1:8b`). Optional: `OLLAMA_USE_CPU=1` in `.env` if GPU/CUDA fails.

## Layout

- `frontend/` — React UI (calls `/api/*` on the backend).
- `backend/app/` — FastAPI + RAG pipeline (`core/master_agent.py`, ingestion, sync manifest under `backend/data/`).
- `dashboard.py` — legacy Streamlit UI (optional).
- Root `docker-compose.yml` — Qdrant only.

Override API URL in the browser build with `VITE_API_BASE` (see `frontend/.env.example`).
