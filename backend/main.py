import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings
from backend.routers import analysis, health, ingest, query
from backend.services.graph_store import init_graph
from backend.services.qdrant_client import init_qdrant
from backend.services.ollama_client import check_ollama_health

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=== Legal RAG API — Starting ===")

    logger.info("Step 1/4 — Connecting to Qdrant...")
    await init_qdrant()

    logger.info("Step 2/4 — Checking Ollama...")
    await check_ollama_health()

    logger.info("Step 3/4 — Loading knowledge graph...")
    init_graph()

    logger.info("Step 4/4 — Building BM25 index...")
    from backend.services.retrieval.bm25_index import build_bm25_index
    build_bm25_index()

    settings.pdf_dir.mkdir(parents=True, exist_ok=True)
    settings.case_upload_dir.mkdir(parents=True, exist_ok=True)
    settings.graph_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info("=== Startup complete. Listening. ===")
    yield
    logger.info("=== Legal RAG API — Shutting down ===")


app = FastAPI(
    title="Legal RAG API",
    description="Laptop-optimised legal research system — GTX 1650, 16GB RAM.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_PREFIX = "/api"
app.include_router(health.router, prefix=API_PREFIX)
app.include_router(ingest.router, prefix=API_PREFIX)
app.include_router(query.router, prefix=API_PREFIX)
app.include_router(analysis.router, prefix=API_PREFIX)


@app.get("/")
async def root():
    return {
        "service": "Legal RAG API",
        "phase": "1 — Foundation",
        "docs": "/docs",
        "health": "/health/",
    }
