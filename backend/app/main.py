"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import settings
from app.debug_session_log import debug_log
from app.routes import analysis, health, ingest, stats


_log = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # region agent log
    debug_log(
        "H1",
        "main.py:lifespan",
        "fastapi_startup",
        {
            "api_prefix": settings.API_PREFIX,
            "collection": settings.COLLECTION,
            "pdf_dir_set": bool(str(settings.PDF_DIR)),
            "qdrant_url_len": len(settings.QDRANT_URL or ""),
        },
    )
    # endregion
    pfx = settings.API_PREFIX.rstrip("/") or ""
    mount = f"{pfx}/" if pfx else "/"
    _log.info("Legal AI API: HTTP routes under %s (e.g. %shealth)", mount, mount)
    yield


app = FastAPI(title="Legal AI API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

prefix = settings.API_PREFIX.rstrip("/") or ""

app.include_router(health.router, prefix=prefix)
app.include_router(analysis.router, prefix=prefix)
app.include_router(ingest.router, prefix=prefix)
app.include_router(stats.router, prefix=prefix)
