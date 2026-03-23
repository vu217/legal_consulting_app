"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import settings
from app.debug_session_log import debug_log
from app.routes import analysis, health, ingest, stats


_log = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI):
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
    pfx = settings.API_PREFIX.rstrip("/") or ""
    mount = f"{pfx}/" if pfx else "/"
    _log.info("Legal AI API: HTTP routes under %s (e.g. %shealth)", mount, mount)

    _validate_startup()
    yield


def _validate_startup() -> None:
    """Best-effort checks at boot — log warnings but don't block startup."""
    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(url=settings.QDRANT_URL, timeout=3)
        cols = [c.name for c in client.get_collections().collections]
        if settings.COLLECTION in cols:
            info = client.get_collection(collection_name=settings.COLLECTION)
            vec_cfg = info.config.params.vectors
            actual_size = getattr(vec_cfg, "size", None)
            if actual_size and actual_size != settings.VECTOR_SIZE:
                _log.warning(
                    "Vector dimension mismatch: collection has %d but VECTOR_SIZE=%d. "
                    "Re-create the collection or update VECTOR_SIZE.",
                    actual_size,
                    settings.VECTOR_SIZE,
                )
    except Exception as e:
        _log.warning("Startup validation skipped (Qdrant unreachable): %s", e)


app = FastAPI(title="Legal AI API", version="2.0.0", lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_request: Request, exc: RequestValidationError):
    errors = []
    for err in exc.errors():
        loc = " → ".join(str(l) for l in err.get("loc", []))
        errors.append(f"{loc}: {err.get('msg', 'invalid')}")
    return JSONResponse(
        status_code=422,
        content={"detail": "; ".join(errors), "type": "validation_error"},
    )


@app.exception_handler(Exception)
async def generic_error_handler(_request: Request, exc: Exception):
    _log.exception("Unhandled error: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "type": "server_error"},
    )


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
