"""Case analysis endpoint."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.master_agent import run_analysis
from app.debug_session_log import debug_log

router = APIRouter(tags=["analysis"])
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="analysis")


class AnalysisRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=50_000)


@router.post("/analysis")
async def analyze_case(body: AnalysisRequest) -> dict:
    q = body.query.strip()
    if not q:
        raise HTTPException(status_code=400, detail="query must not be empty")
    # region agent log
    debug_log("H3", "analysis.py:analyze_case", "analysis_start", {"query_len": len(q)})
    # endregion
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(_executor, run_analysis, q)
    except Exception as e:
        # region agent log
        debug_log(
            "H3",
            "analysis.py:analyze_case",
            "analysis_error",
            {"exc_type": type(e).__name__, "exc_len": len(str(e))},
        )
        # endregion
        raise HTTPException(status_code=502, detail=f"Analysis failed: {e!s}") from e
    # region agent log
    debug_log(
        "H3",
        "analysis.py:analyze_case",
        "analysis_ok",
        {
            "win_probability": result.get("win_probability"),
            "has_summary": bool(result.get("summary")),
            "similar_n": len((result.get("precedent") or {}).get("similar_cases") or []),
        },
    )
    # endregion
    return result
