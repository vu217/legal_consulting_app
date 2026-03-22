"""
Optimised pipeline: single retrieval, one fast multi-section call, one synthesis call.
"""

from __future__ import annotations

import re
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from langchain_ollama import ChatOllama

from app import settings
from app.core.ollama_config import get_ollama_num_gpu
from app.core.shared_retriever import retrieve_docs

OLLAMA_TAGS_URL = "http://127.0.0.1:11434/api/tags"
_FAST_MODEL_CACHE_TTL_SEC = 60.0
_fast_model_cache: tuple[float, str] | None = None


class AnalysisCancelled(Exception):
    """Raised when the client disconnects or the user cancels between pipeline phases."""


def check_ollama_reachable() -> None:
    try:
        with urllib.request.urlopen(OLLAMA_TAGS_URL, timeout=2) as resp:
            if not (200 <= int(resp.status) < 300):
                raise RuntimeError("unexpected status")
    except Exception as e:
        raise RuntimeError(
            "The local AI server is not running. Start it with `ollama serve`, or run `npm run dev` to start the stack."
        ) from e


def _resolve_fast_model() -> str:
    try:
        result = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=5)
        if settings.FAST_LLM_MODEL.split(":")[0] in result.stdout:
            return settings.FAST_LLM_MODEL
    except Exception:
        pass
    return settings.LLM_MODEL


def get_fast_model() -> str:
    global _fast_model_cache
    now = time.monotonic()
    if _fast_model_cache is not None and (now - _fast_model_cache[0]) < _FAST_MODEL_CACHE_TTL_SEC:
        return _fast_model_cache[1]
    resolved = _resolve_fast_model()
    _fast_model_cache = (now, resolved)
    return resolved


def _strip_thinking(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _emit(
    progress: Callable[[str, dict[str, Any]], None] | None,
    phase: str,
    data: dict[str, Any] | None = None,
) -> None:
    if progress:
        progress(phase, data or {})


def _ensure_not_cancelled(should_cancel: Callable[[], bool] | None) -> None:
    if should_cancel and should_cancel():
        raise AnalysisCancelled()


def _build_combined_prompt(query: str, docs: list) -> str:
    def fmt(doc_list, max_chars=400):
        if not doc_list:
            return "No relevant documents found."
        return "\n\n".join(
            f"[Doc {i+1}] Court:{d.metadata.get('court','?')} | "
            f"Year:{d.metadata.get('year','?')} | "
            f"Outcome:{d.metadata.get('outcome','?')} | "
            f"Statutes:{d.metadata.get('statutes','')[:80]}\n"
            f"{d.page_content[:max_chars]}"
            for i, d in enumerate(doc_list)
        )

    by_type: dict[str, list] = {}
    for d in docs:
        st = d.metadata.get("section_type", "other")
        by_type.setdefault(st, []).append(d)

    evidence_docs = by_type.get("evidence", []) or docs[:4]
    statute_docs = by_type.get("statutes", []) or docs[:4]
    argument_docs = by_type.get("arguments", []) or docs[:4]
    all_docs = docs

    precedent_ctx = fmt(all_docs[:5])
    evidence_ctx = fmt(evidence_docs[:4])
    statute_ctx = fmt(statute_docs[:4])
    strategy_ctx = fmt(argument_docs[:4])
    winrate_ctx = fmt(all_docs[:6], max_chars=250)

    win_outcomes = {"allowed", "acquitted", "upheld", "set aside", "quashed"}
    lose_outcomes = {"convicted", "sentenced", "dismissed", "remanded"}
    wins = sum(1 for d in docs if any(w in d.metadata.get("outcome", "").lower() for w in win_outcomes))
    losses = sum(1 for d in docs if any(l in d.metadata.get("outcome", "").lower() for l in lose_outcomes))
    base_info = f"{wins} wins, {losses} losses from {wins+losses} known outcomes in retrieved cases."

    return f"""You are a senior legal analyst. Analyse the case query below using the provided case law context.
Respond ONLY with the exact section markers shown. Be concise and direct — each section max 250 words.

CASE QUERY: {query}

===PRECEDENTS===
Context (top similar cases):
{precedent_ctx}

Identify the 3 most relevant precedents. For each: case name (if known), court/year, why it is relevant, outcome.
Use bullet points.

===EVIDENCE===
Context (evidence patterns in similar cases):
{evidence_ctx}

List what evidence to gather: physical/documentary, witnesses, forensic. Include priority (High/Medium/Low).

===STATUTES===
Context (statutes applied in similar cases):
{statute_ctx}

List applicable statutes with section numbers. Mark each FAVOURABLE or ADVERSE. Group: Favourable | Adverse | Neutral/procedural.

===STRATEGY===
Context (arguments and outcomes in similar cases):
{strategy_ctx}

Suggest 2-3 distinct legal strategies. For each: name, core argument (1 sentence), supporting precedent, risk (Low/Medium/High).

===WINRATE===
Context (case outcomes):
{winrate_ctx}
Base rate: {base_info}

Give a win probability % (e.g. "65%"). List factors that increase it, factors that decrease it, and confidence (Low/Medium/High).
"""


def _parse_combined_output(raw: str) -> dict:
    sections = {}
    markers = ["PRECEDENTS", "EVIDENCE", "STATUTES", "STRATEGY", "WINRATE"]
    for i, marker in enumerate(markers):
        next_marker = markers[i + 1] if i + 1 < len(markers) else None
        pattern = (
            rf"==={marker}===(.*?)==={next_marker}==="
            if next_marker
            else rf"==={marker}===(.*?)$"
        )
        m = re.search(pattern, raw, re.DOTALL | re.IGNORECASE)
        sections[marker.lower()] = m.group(1).strip() if m else ""
    return sections


def _parse_winrate_probability(text: str) -> int:
    matches = re.findall(r"(\d{1,3})\s*%", text)
    if matches:
        vals = [int(m) for m in matches if 1 <= int(m) <= 99]
        return vals[0] if vals else 50
    return 50


def _build_agent_outputs(query: str, docs: list, sections: dict) -> dict:
    win_text = sections.get("winrate", "")
    llm_prob = _parse_winrate_probability(win_text)

    win_outcomes = {"allowed", "acquitted", "upheld", "set aside", "quashed"}
    lose_outcomes = {"convicted", "sentenced", "dismissed", "remanded"}
    wins = sum(1 for d in docs if any(w in d.metadata.get("outcome", "").lower() for w in win_outcomes))
    losses = sum(1 for d in docs if any(l in d.metadata.get("outcome", "").lower() for l in lose_outcomes))
    total = wins + losses
    base_rate = round((wins / total) * 100) if total > 0 else 50
    blended = round(0.4 * base_rate + 0.6 * llm_prob)

    similar_cases = [
        {
            "rank": i + 1,
            "case_name": d.metadata.get("case_name", f"Case {i+1}"),
            "court": d.metadata.get("court", "Unknown court"),
            "year": d.metadata.get("year", "Unknown year"),
            "outcome": d.metadata.get("outcome", "Unknown"),
            "parties": d.metadata.get("parties", ""),
            "statutes": d.metadata.get("statutes", ""),
            "chunk": d.page_content[:400],
            "source": d.metadata.get("source", ""),
        }
        for i, d in enumerate(docs[:5])
    ]

    all_statutes = []
    for d in docs:
        s = d.metadata.get("statutes", "")
        if s:
            all_statutes.extend([x.strip() for x in s.split(";") if x.strip()])
    all_statutes = list(dict.fromkeys(all_statutes))[:15]

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
            "stats": {"wins": wins, "losses": losses, "unknowns": len(docs) - total, "base_rate_pct": base_rate},
            "analysis": win_text,
        },
    }


def _run_combined_analysis(query: str, docs: list, fast_model: str) -> dict:
    prompt = _build_combined_prompt(query, docs)
    fast_llm = ChatOllama(
        model=fast_model,
        num_predict=1200,
        temperature=0.3,
        num_ctx=2048,
        num_gpu=get_ollama_num_gpu(),
    )
    response = fast_llm.invoke(prompt)
    raw = _strip_thinking(response.content)
    sections = _parse_combined_output(raw)
    return _build_agent_outputs(query, docs, sections)


def _compile_summary(query: str, agent_outputs: dict) -> str:
    precedent_text = agent_outputs.get("precedent", {}).get("analysis", "N/A")
    evidence_text = agent_outputs.get("evidence", {}).get("analysis", "N/A")
    statute_text = agent_outputs.get("statute", {}).get("analysis", "N/A")
    strategy_text = agent_outputs.get("strategy", {}).get("analysis", "N/A")
    winrate_text = agent_outputs.get("winrate", {}).get("analysis", "N/A")
    win_prob = agent_outputs.get("winrate", {}).get("win_probability", "?")

    prompt = f"""You are a senior legal counsel preparing a case briefing. Synthesise the research below into a clear executive summary.

CASE QUERY: {query}

WIN PROBABILITY ESTIMATE: {win_prob}%

PRECEDENTS FOUND:
{precedent_text}

EVIDENCE TO SEEK:
{evidence_text}

APPLICABLE STATUTES:
{statute_text}

RECOMMENDED STRATEGIES:
{strategy_text}

WIN RATE ANALYSIS:
{winrate_text}

Write a 3-paragraph executive summary:
Paragraph 1: Overall assessment and win probability reasoning
Paragraph 2: Strongest arguments and key precedents to rely on
Paragraph 3: Immediate action items (evidence to collect, filings to make)

Be direct, specific, and actionable. Write for a client who needs clarity."""

    r1_llm = ChatOllama(
        model=settings.LLM_MODEL,
        num_predict=700,
        temperature=0.4,
        num_ctx=2048,
        num_gpu=get_ollama_num_gpu(),
    )
    response = r1_llm.invoke(prompt)
    return _strip_thinking(response.content)


def run_analysis(
    query: str,
    progress: Callable[[str, dict[str, Any]], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> dict:
    check_ollama_reachable()
    k = 12
    _emit(progress, "retrieve_start", {"k": k})
    try:
        docs = retrieve_docs(query, k=k)
    except Exception as e:
        _emit(progress, "phase_error", {"failed_phase": "retrieve", "detail": str(e)})
        raise
    _emit(progress, "retrieve_done", {"doc_count": len(docs)})

    _ensure_not_cancelled(should_cancel)
    fast_model = get_fast_model()
    _emit(progress, "fast_llm_start", {"model": fast_model})
    try:
        agent_outputs = _run_combined_analysis(query, docs, fast_model)
    except Exception as e:
        _emit(progress, "phase_error", {"failed_phase": "fast_llm", "detail": str(e)})
        raise
    _emit(progress, "fast_llm_done", {})

    _ensure_not_cancelled(should_cancel)
    _emit(progress, "summary_llm_start", {"model": settings.LLM_MODEL})
    try:
        summary = _compile_summary(query, agent_outputs)
    except Exception as e:
        _emit(progress, "phase_error", {"failed_phase": "summary_llm", "detail": str(e)})
        raise
    _emit(progress, "summary_llm_done", {})

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
    }
