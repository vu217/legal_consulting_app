"""Case analysis endpoint."""

from __future__ import annotations

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.master_agent import AnalysisCancelled, run_analysis
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


def _sse_progress_put(loop: asyncio.AbstractEventLoop, aq: asyncio.Queue, phase: str, data: dict) -> None:
    payload = {"type": "progress", "phase": phase, **data}
    try:
        loop.call_soon_threadsafe(aq.put_nowait, payload)
    except RuntimeError:
        pass


@router.post("/analysis/stream")
async def analyze_case_stream(body: AnalysisRequest):
    q = body.query.strip()
    if not q:
        raise HTTPException(status_code=400, detail="query must not be empty")

    loop = asyncio.get_running_loop()
    aq: asyncio.Queue = asyncio.Queue()
    cancel_event = threading.Event()

    def worker() -> None:
        def progress(phase: str, data: dict) -> None:
            if cancel_event.is_set():
                return
            _sse_progress_put(loop, aq, phase, data)

        try:
            out = run_analysis(q, progress=progress, should_cancel=cancel_event.is_set)
            loop.call_soon_threadsafe(
                aq.put_nowait,
                {"type": "result", "payload": out},
            )
        except AnalysisCancelled:
            loop.call_soon_threadsafe(
                aq.put_nowait,
                {"type": "error", "code": "cancelled", "detail": "Analysis was cancelled."},
            )
        except Exception as e:
            loop.call_soon_threadsafe(
                aq.put_nowait,
                {"type": "error", "detail": str(e)},
            )

    fut = loop.run_in_executor(_executor, worker)

    async def event_gen():
        try:
            while True:
                msg = await aq.get()
                line = f"data: {json.dumps(msg, default=str)}\n\n"
                yield line
                if msg.get("type") in ("result", "error"):
                    break
        finally:
            cancel_event.set()
        try:
            await fut
        except Exception:
            pass

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
