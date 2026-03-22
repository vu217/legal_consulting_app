"""FastAPI application entrypoint."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import settings
from app.routes import analysis, health, ingest

app = FastAPI(title="Legal AI API", version="1.0.0")

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
