"""
Case-analysis endpoints: POST /analysis and POST /analysis/stream.

Two-stage LLM pipeline:
  1. Retrieval  — hybrid (dense + BM25) + knowledge-graph augmentation.
  2. Fast LLM   — single combined prompt covering precedents, evidence,
                  statutes, strategy, and win-rate.
  3. Summary LLM — executive summary synthesising everything.

Progress is streamed to the frontend via SSE so the dashboard shows a live
progress tracker.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, Callable

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.config import settings
from backend.services.ollama_client import generate
from backend.services.retrieval.hybrid import RetrievedChunk, hybrid_retrieve
from backend.services.retrieval.graph_augment import augment_with_graph

logger = logging.getLogger(__name__)
router = APIRouter(tags=["analysis"])

# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------

VALID_COURT_TYPES = frozenset({
    "supreme_court", "high_court", "district_court", "sessions_court",
    "tribunal", "consumer_forum", "family_court", "other",
})
VALID_CASE_TYPES = frozenset({
    "criminal", "civil", "constitutional", "family",
    "commercial", "tax", "labor", "other",
})


class AnalysisRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=50_000)
    court_type: str | None = Field(None)
    case_type: str | None = Field(None)
    case_context: str | None = Field(None, max_length=5000)
    desired_outcome: str | None = Field(None, max_length=500)
    uploaded_file_ids: list[str] = Field(default_factory=list)


def _validate_enums(body: AnalysisRequest) -> None:
    if body.court_type and body.court_type not in VALID_COURT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid court_type '{body.court_type}'. "
                   f"Valid: {sorted(VALID_COURT_TYPES)}",
        )
    if body.case_type and body.case_type not in VALID_CASE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid case_type '{body.case_type}'. "
                   f"Valid: {sorted(VALID_CASE_TYPES)}",
        )


# ---------------------------------------------------------------------------
# Prompt helpers
# ---------------------------------------------------------------------------

def _strip_thinking(text: str) -> str:
    """Remove <think>…</think> blocks some models emit."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _fmt_chunks(chunks: list[RetrievedChunk], max_chars: int = 400) -> str:
    if not chunks:
        return "No relevant documents found."
    parts = []
    for i, c in enumerate(chunks):
        p = c.payload
        parts.append(
            f"[Doc {i+1}] Court:{p.get('court','?')} | "
            f"Type:{p.get('case_type', p.get('legal_layer','?'))} | "
            f"Year:{p.get('year','?')} | "
            f"Outcome:{p.get('outcome','?')} | "
            f"Statutes:{str(p.get('statutes',''))[:80]}\n"
            f"{c.text[:max_chars]}"
        )
    return "\n\n".join(parts)


def _build_combined_prompt(
    query: str,
    chunks: list[RetrievedChunk],
    court_type: str,
    case_type: str,
    case_context: str,
    desired_outcome: str,
) -> str:
    by_layer: dict[str, list[RetrievedChunk]] = {}
    for c in chunks:
        layer = c.payload.get("legal_layer", "other")
        by_layer.setdefault(layer, []).append(c)

    statute_chunks = by_layer.get("statute", []) or chunks[:4]
    case_chunks = [
        c for c in chunks
        if c.payload.get("legal_layer", "").startswith("case")
    ] or chunks[:4]

    precedent_ctx = _fmt_chunks(chunks[:5])
    evidence_ctx = _fmt_chunks(case_chunks[:4])
    statute_ctx = _fmt_chunks(statute_chunks[:4])
    strategy_ctx = _fmt_chunks(case_chunks[:4])
    winrate_ctx = _fmt_chunks(chunks[:6], max_chars=250)

    win_outcomes = {"allowed", "acquitted", "upheld", "set aside", "quashed"}
    lose_outcomes = {"convicted", "sentenced", "dismissed", "remanded"}
    wins = sum(
        1 for c in chunks
        if any(w in c.payload.get("outcome", "").lower() for w in win_outcomes)
    )
    losses = sum(
        1 for c in chunks
        if any(w in c.payload.get("outcome", "").lower() for w in lose_outcomes)
    )
    base_info = (
        f"{wins} wins, {losses} losses from {wins + losses} known outcomes "
        f"in retrieved cases."
    )

    extra = ""
    if court_type:
        extra += f"\nCOURT TYPE: {court_type.replace('_', ' ').title()}"
    if case_type:
        extra += f"\nCASE TYPE: {case_type.title()}"
    if case_context:
        extra += f"\nADDITIONAL CONTEXT: {case_context[:500]}"
    if desired_outcome:
        extra += f"\nDESIRED OUTCOME: {desired_outcome}"

    court_hint = (
        f"Focus on {court_type.replace('_', ' ')} precedents where available."
        if court_type else ""
    )
    evidence_hint = (
        f"Consider evidence typically required in {case_type} cases."
        if case_type else ""
    )
    strategy_hint = (
        f"Tailor strategies toward achieving: {desired_outcome}"
        if desired_outcome else ""
    )

    return f"""You are a senior legal analyst. Analyse the case query below using the provided case law context.
Respond ONLY with the exact section markers shown. Be concise and direct — each section max 250 words.

CASE QUERY: {query}
{extra}

===PRECEDENTS===
Context (top similar cases):
{precedent_ctx}

Identify the 3 most relevant precedents. For each: case name (if known), court/year, why it is relevant, outcome.
{court_hint}
Use bullet points.

===EVIDENCE===
Context (evidence patterns in similar cases):
{evidence_ctx}

List what evidence to gather: physical/documentary, witnesses, forensic. Include priority (High/Medium/Low).
{evidence_hint}

===STATUTES===
Context (statutes applied in similar cases):
{statute_ctx}

List applicable statutes with section numbers. Mark each FAVOURABLE or ADVERSE. Group: Favourable | Adverse | Neutral/procedural.

===STRATEGY===
Context (arguments and outcomes in similar cases):
{strategy_ctx}

Suggest 2-3 distinct legal strategies. For each: name, core argument (1 sentence), supporting precedent, risk (Low/Medium/High).
{strategy_hint}

===WINRATE===
Context (case outcomes):
{winrate_ctx}
Base rate: {base_info}

Give a win probability % (e.g. "65%"). List factors that increase it, factors that decrease it, and confidence (Low/Medium/High).
"""


def _build_summary_prompt(
    query: str,
    agent_outputs: dict,
    desired_outcome: str,
) -> str:
    prec = agent_outputs.get("precedent", {}).get("analysis", "N/A")
    evid = agent_outputs.get("evidence", {}).get("analysis", "N/A")
    stat = agent_outputs.get("statute", {}).get("analysis", "N/A")
    strat = agent_outputs.get("strategy", {}).get("analysis", "N/A")
    winr = agent_outputs.get("winrate", {}).get("analysis", "N/A")
    prob = agent_outputs.get("winrate", {}).get("win_probability", "?")

    outcome_line = f"\nDESIRED OUTCOME: {desired_outcome}" if desired_outcome else ""

    return f"""You are a senior legal counsel preparing a case briefing. Synthesise the research below into a clear executive summary.

CASE QUERY: {query}{outcome_line}

WIN PROBABILITY ESTIMATE: {prob}%

PRECEDENTS FOUND:
{prec}

EVIDENCE TO SEEK:
{evid}

APPLICABLE STATUTES:
{stat}

RECOMMENDED STRATEGIES:
{strat}

WIN RATE ANALYSIS:
{winr}

Write a 3-paragraph executive summary:
Paragraph 1: Overall assessment and win probability reasoning
Paragraph 2: Strongest arguments and key precedents to rely on
Paragraph 3: Immediate action items (evidence to collect, filings to make)

Be direct, specific, and actionable. Write for a client who needs clarity."""


# ---------------------------------------------------------------------------
# Output parsing
# ---------------------------------------------------------------------------

_REQUIRED_MARKERS = {"PRECEDENTS", "EVIDENCE", "STATUTES", "STRATEGY", "WINRATE"}


def _validate_combined(output: str) -> bool:
    found = {m for m in _REQUIRED_MARKERS if f"==={m}===" in output.upper()}
    return len(found) >= 3


def _parse_combined_output(raw: str) -> dict[str, str]:
    markers = ["PRECEDENTS", "EVIDENCE", "STATUTES", "STRATEGY", "WINRATE"]
    sections: dict[str, str] = {}
    for i, marker in enumerate(markers):
        nxt = markers[i + 1] if i + 1 < len(markers) else None
        pattern = (
            rf"==={marker}===(.*?)==={nxt}==="
            if nxt
            else rf"==={marker}===(.*?)$"
        )
        m = re.search(pattern, raw, re.DOTALL | re.IGNORECASE)
        sections[marker.lower()] = m.group(1).strip() if m else ""
    return sections


def _parse_winrate_probability(text: str) -> int:
    matches = re.findall(r"(\d{1,3})\s*%", text)
    if matches:
        vals = [int(v) for v in matches if 1 <= int(v) <= 99]
        return vals[0] if vals else 50
    return 50


# ---------------------------------------------------------------------------
# Result assembly
# ---------------------------------------------------------------------------

def _build_agent_outputs(
    query: str,
    chunks: list[RetrievedChunk],
    sections: dict[str, str],
) -> dict[str, Any]:
    win_text = sections.get("winrate", "")
    llm_prob = _parse_winrate_probability(win_text)

    win_outcomes = {"allowed", "acquitted", "upheld", "set aside", "quashed"}
    lose_outcomes = {"convicted", "sentenced", "dismissed", "remanded"}
    wins = sum(
        1 for c in chunks
        if any(w in c.payload.get("outcome", "").lower() for w in win_outcomes)
    )
    losses = sum(
        1 for c in chunks
        if any(w in c.payload.get("outcome", "").lower() for w in lose_outcomes)
    )
    total = wins + losses
    base_rate = round((wins / total) * 100) if total > 0 else 50
    blended = max(1, min(99, round(0.4 * base_rate + 0.6 * llm_prob)))

    similar_cases = []
    for i, c in enumerate(chunks[:5]):
        p = c.payload
        statutes_val = p.get("statutes", "")
        if isinstance(statutes_val, list):
            statutes_val = "; ".join(statutes_val)
        similar_cases.append({
            "rank": i + 1,
            "case_name": p.get("case_name", f"Case {i+1}"),
            "court": p.get("court", "Unknown court"),
            "court_type": p.get("court_type", "other"),
            "year": p.get("year", "Unknown year"),
            "case_type": p.get("case_type", "other"),
            "outcome": p.get("outcome", "Unknown"),
            "outcome_detail": p.get("outcome_detail", ""),
            "parties": p.get("parties", ""),
            "statutes": statutes_val,
            "chunk": c.text[:400],
            "source": p.get("source", ""),
        })

    all_statutes: list[str] = []
    for c in chunks:
        s = c.payload.get("statutes", "")
        if isinstance(s, list):
            all_statutes.extend(s)
        elif isinstance(s, str) and s:
            all_statutes.extend([x.strip() for x in s.split(";") if x.strip()])
    all_statutes = list(dict.fromkeys(all_statutes))[:15]

    judgments = []
    for sc in similar_cases:
        if sc["outcome"] and sc["outcome"] != "Unknown":
            judgments.append({
                "case_name": sc["case_name"],
                "court": sc["court"],
                "year": sc["year"],
                "outcome": sc["outcome"],
                "outcome_detail": sc["outcome_detail"],
                "statutes": sc["statutes"],
            })

    return {
        "precedent": {
            "agent": "precedent",
            "similar_cases": similar_cases,
            "analysis": sections.get("precedents", ""),
        },
        "evidence": {
            "agent": "evidence",
            "analysis": sections.get("evidence", ""),
        },
        "statute": {
            "agent": "statute",
            "statutes_raw": all_statutes,
            "analysis": sections.get("statutes", ""),
        },
        "strategy": {
            "agent": "strategy",
            "analysis": sections.get("strategy", ""),
        },
        "winrate": {
            "agent": "winrate",
            "win_probability": blended,
            "base_rate": base_rate,
            "llm_estimate": llm_prob,
            "stats": {
                "wins": wins,
                "losses": losses,
                "unknowns": len(chunks) - total,
                "base_rate_pct": base_rate,
            },
            "analysis": win_text,
        },
        "judgments": judgments,
    }


def _empty_result(query: str) -> dict:
    return {
        "query": query,
        "win_probability": 50,
        "summary": "No relevant case documents were found. "
                   "Please upload PDFs to the case library.",
        "precedent": {"agent": "precedent", "similar_cases": [], "analysis": ""},
        "evidence": {"agent": "evidence", "analysis": ""},
        "statute": {"agent": "statute", "statutes_raw": [], "analysis": ""},
        "strategy": {"agent": "strategy", "analysis": ""},
        "winrate": {
            "agent": "winrate",
            "win_probability": 50,
            "base_rate": 50,
            "llm_estimate": 50,
            "stats": {"wins": 0, "losses": 0, "unknowns": 0, "base_rate_pct": 50},
            "analysis": "",
        },
        "judgments": [],
    }


# ---------------------------------------------------------------------------
# Core pipeline (async)
# ---------------------------------------------------------------------------

async def _run_pipeline(
    body: AnalysisRequest,
    emit: Callable[[str, dict], None] | None = None,
) -> dict:
    """
    Full analysis pipeline.  Returns the same JSON shape the frontend expects.
    """
    query = body.query.strip()
    court_type = body.court_type or ""
    case_type = body.case_type or ""
    case_context = body.case_context or ""
    desired_outcome = body.desired_outcome or ""

    def _emit(phase: str, data: dict | None = None) -> None:
        if emit:
            emit(phase, data or {})

    # ── Phase 1: Retrieval ──────────────────────────────────────────────────
    _emit("retrieve_start", {"k": settings.final_k, "court_type": court_type, "case_type": case_type})

    try:
        collection = "both"
        chunks = await hybrid_retrieve(query, collection=collection, k=settings.final_k)
    except Exception as exc:
        _emit("phase_error", {"failed_phase": "retrieve", "detail": str(exc)})
        raise

    chunks = augment_with_graph(chunks)
    _emit("retrieve_done", {"doc_count": len(chunks)})

    if not chunks:
        _emit("phase_error", {
            "failed_phase": "retrieve",
            "detail": "No documents found. Upload case PDFs first.",
        })
        return _empty_result(query)

    # ── Phase 2: Fast combined analysis ─────────────────────────────────────
    _emit("fast_llm_start", {"task": "case_analysis", "model": settings.fast_llm_model})
    _emit("task_start", {"task": "case_analysis", "model": settings.fast_llm_model})

    combined_prompt = _build_combined_prompt(
        query, chunks, court_type, case_type, case_context, desired_outcome,
    )

    raw_analysis = ""
    retries_used = 0
    max_retries = 2

    for attempt in range(max_retries + 1):
        try:
            raw_analysis = await generate(
                prompt=combined_prompt,
                model=settings.fast_llm_model,
                num_predict=1500,
                temperature=0.3,
                num_ctx=2048,
            )
            raw_analysis = _strip_thinking(raw_analysis)

            if _validate_combined(raw_analysis):
                break

            if attempt < max_retries:
                retries_used = attempt + 1
                _emit("task_retry", {
                    "task": "case_analysis",
                    "attempt": retries_used,
                    "reason": "validation_failed",
                })
        except Exception as exc:
            if attempt == max_retries:
                _emit("phase_error", {"failed_phase": "fast_llm", "detail": str(exc)})
                raise
            retries_used = attempt + 1
            _emit("task_retry", {
                "task": "case_analysis",
                "attempt": retries_used,
                "reason": str(exc)[:200],
            })

    _emit("task_done", {"task": "case_analysis", "retries": retries_used})
    _emit("fast_llm_done", {})

    if not raw_analysis:
        return _empty_result(query)

    sections = _parse_combined_output(raw_analysis)
    agent_outputs = _build_agent_outputs(query, chunks, sections)

    # ── Phase 3: Executive summary ──────────────────────────────────────────
    _emit("summary_llm_start", {"model": settings.llm_model})

    summary_prompt = _build_summary_prompt(query, agent_outputs, desired_outcome)

    try:
        summary = await generate(
            prompt=summary_prompt,
            model=settings.llm_model,
            num_predict=700,
            temperature=0.4,
            num_ctx=2048,
        )
        summary = _strip_thinking(summary)
    except Exception as exc:
        logger.error(f"Summary generation failed: {exc}")
        summary = "Summary generation failed."

    _emit("summary_llm_done", {})

    win_prob = agent_outputs.get("winrate", {}).get("win_probability", 50)
    return {
        "query": query,
        "win_probability": win_prob,
        "summary": summary,
        "precedent": agent_outputs.get("precedent", {}),
        "evidence": agent_outputs.get("evidence", {}),
        "statute": agent_outputs.get("statute", {}),
        "strategy": agent_outputs.get("strategy", {}),
        "winrate": agent_outputs.get("winrate", {}),
        "judgments": agent_outputs.get("judgments", []),
    }


# ---------------------------------------------------------------------------
# POST /analysis — non-streaming
# ---------------------------------------------------------------------------

@router.post("/analysis")
async def analyze_case(body: AnalysisRequest) -> dict:
    _validate_enums(body)
    if not body.query.strip():
        raise HTTPException(status_code=400, detail="query must not be empty")

    try:
        return await _run_pipeline(body)
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Analysis failed: {exc!s}"
        ) from exc


# ---------------------------------------------------------------------------
# POST /analysis/stream — SSE streaming
# ---------------------------------------------------------------------------

@router.post("/analysis/stream")
async def analyze_case_stream(body: AnalysisRequest):
    _validate_enums(body)
    if not body.query.strip():
        raise HTTPException(status_code=400, detail="query must not be empty")

    queue: asyncio.Queue = asyncio.Queue()
    cancelled = False

    def emit(phase: str, data: dict) -> None:
        if cancelled:
            return
        queue.put_nowait({"type": "progress", "phase": phase, **data})

    async def worker() -> None:
        try:
            result = await _run_pipeline(body, emit=emit)
            await queue.put({"type": "result", "payload": result})
        except asyncio.CancelledError:
            await queue.put({
                "type": "error",
                "code": "cancelled",
                "detail": "Analysis was cancelled.",
            })
        except Exception as exc:
            await queue.put({"type": "error", "detail": str(exc)})

    task = asyncio.create_task(worker())

    async def event_gen():
        nonlocal cancelled
        try:
            while True:
                msg = await queue.get()
                line = f"data: {json.dumps(msg, default=str)}\n\n"
                yield line
                if msg.get("type") in ("result", "error"):
                    break
        finally:
            cancelled = True
            if not task.done():
                task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
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
