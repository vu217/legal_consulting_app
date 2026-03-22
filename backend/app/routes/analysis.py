"""Case analysis endpoint."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.master_agent import run_analysis

router = APIRouter(tags=["analysis"])
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="analysis")


class AnalysisRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=50_000)


@router.post("/analysis")
async def analyze_case(body: AnalysisRequest) -> dict:
    q = body.query.strip()
    if not q:
        raise HTTPException(status_code=400, detail="query must not be empty")
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(_executor, run_analysis, q)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Analysis failed: {e!s}") from e
    return result
