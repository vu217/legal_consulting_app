"""
Analysis pipeline using the agentic framework.

Two-stage LLM pipeline:
  1. Combined structured analysis (fast model) — produces precedents, evidence,
     statutes, strategy, and winrate in one call for local-LLM efficiency.
  2. Executive summary (main model) — synthesizes all findings.

Enhanced with court_type, case_type, case_context, and desired_outcome support.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from typing import Any, Callable

from app import settings
from app.core.agent_framework import (
    AgentTask,
    ParallelExecutor,
    SequentialExecutor,
    TaskCancelled,
)
from app.core.shared_retriever import retrieve_docs

OLLAMA_TAGS_URL = "http://127.0.0.1:11434/api/tags"


class AnalysisCancelled(Exception):
    pass


def check_ollama_reachable() -> None:
    try:
        with urllib.request.urlopen(OLLAMA_TAGS_URL, timeout=3) as resp:
            if not (200 <= int(resp.status) < 300):
                raise RuntimeError("unexpected status")
    except Exception as e:
        raise RuntimeError(
            "The local AI server is not running. Start it with `ollama serve`, "
            "or run `npm run dev` to start the stack."
        ) from e


# ── Prompt builders ───────────────────────────────────────────────────────────

def _fmt_docs(doc_list: list, max_chars: int = 400) -> str:
    if not doc_list:
        return "No relevant documents found."
    return "\n\n".join(
        f"[Doc {i+1}] Court:{d.metadata.get('court','?')} | "
        f"Type:{d.metadata.get('case_type','?')} | "
        f"Year:{d.metadata.get('year','?')} | "
        f"Outcome:{d.metadata.get('outcome','?')} | "
        f"Statutes:{d.metadata.get('statutes','')[:80]}\n"
        f"{d.page_content[:max_chars]}"
        for i, d in enumerate(doc_list)
    )


def _build_combined_prompt(context: dict[str, Any], prior_results: dict[str, str] = None) -> str:
    query = context["query"]
    docs = context["docs"]
    court_type = context.get("court_type", "")
    case_type = context.get("case_type", "")
    case_context = context.get("case_context", "")
    desired_outcome = context.get("desired_outcome", "")

    by_type: dict[str, list] = {}
    for d in docs:
        st = d.metadata.get("section_type", "other")
        by_type.setdefault(st, []).append(d)

    evidence_docs = by_type.get("evidence", []) or docs[:4]
    statute_docs = by_type.get("statutes", []) or docs[:4]
    argument_docs = by_type.get("arguments", []) or docs[:4]

    precedent_ctx = _fmt_docs(docs[:5])
    evidence_ctx = _fmt_docs(evidence_docs[:4])
    statute_ctx = _fmt_docs(statute_docs[:4])
    strategy_ctx = _fmt_docs(argument_docs[:4])
    winrate_ctx = _fmt_docs(docs[:6], max_chars=250)

    win_outcomes = {"allowed", "acquitted", "upheld", "set aside", "quashed"}
    lose_outcomes = {"convicted", "sentenced", "dismissed", "remanded"}
    wins = sum(1 for d in docs if any(w in d.metadata.get("outcome", "").lower() for w in win_outcomes))
    losses = sum(1 for d in docs if any(l in d.metadata.get("outcome", "").lower() for l in lose_outcomes))
    base_info = f"{wins} wins, {losses} losses from {wins+losses} known outcomes in retrieved cases."

    extra_context = ""
    if court_type:
        extra_context += f"\nCOURT TYPE: {court_type.replace('_', ' ').title()}"
    if case_type:
        extra_context += f"\nCASE TYPE: {case_type.title()}"
    if case_context:
        extra_context += f"\nADDITIONAL CONTEXT: {case_context[:500]}"
    if desired_outcome:
        extra_context += f"\nDESIRED OUTCOME: {desired_outcome}"

    return f"""You are a senior legal analyst. Analyse the case query below using the provided case law context.
Respond ONLY with the exact section markers shown. Be concise and direct — each section max 250 words.

CASE QUERY: {query}
{extra_context}

===PRECEDENTS===
Context (top similar cases):
{precedent_ctx}

Identify the 3 most relevant precedents. For each: case name (if known), court/year, why it is relevant, outcome.
{"Focus on " + court_type.replace('_', ' ') + " precedents where available." if court_type else ""}
Use bullet points.

===EVIDENCE===
Context (evidence patterns in similar cases):
{evidence_ctx}

List what evidence to gather: physical/documentary, witnesses, forensic. Include priority (High/Medium/Low).
{"Consider evidence typically required in " + case_type + " cases." if case_type else ""}

===STATUTES===
Context (statutes applied in similar cases):
{statute_ctx}

List applicable statutes with section numbers. Mark each FAVOURABLE or ADVERSE. Group: Favourable | Adverse | Neutral/procedural.

===STRATEGY===
Context (arguments and outcomes in similar cases):
{strategy_ctx}

Suggest 2-3 distinct legal strategies. For each: name, core argument (1 sentence), supporting precedent, risk (Low/Medium/High).
{"Tailor strategies toward achieving: " + desired_outcome if desired_outcome else ""}

===WINRATE===
Context (case outcomes):
{winrate_ctx}
Base rate: {base_info}

Give a win probability % (e.g. "65%"). List factors that increase it, factors that decrease it, and confidence (Low/Medium/High).
"""


def _build_summary_prompt(context: dict[str, Any], prior_results: dict[str, str] = None) -> str:
    query = context["query"]
    desired_outcome = context.get("desired_outcome", "")
    agent_outputs = context.get("agent_outputs", {})

    precedent_text = agent_outputs.get("precedent", {}).get("analysis", "N/A")
    evidence_text = agent_outputs.get("evidence", {}).get("analysis", "N/A")
    statute_text = agent_outputs.get("statute", {}).get("analysis", "N/A")
    strategy_text = agent_outputs.get("strategy", {}).get("analysis", "N/A")
    winrate_text = agent_outputs.get("winrate", {}).get("analysis", "N/A")
    win_prob = agent_outputs.get("winrate", {}).get("win_probability", "?")

    outcome_line = f"\nDESIRED OUTCOME: {desired_outcome}" if desired_outcome else ""

    return f"""You are a senior legal counsel preparing a case briefing. Synthesise the research below into a clear executive summary.

CASE QUERY: {query}{outcome_line}

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


# ── Section-marker validation ─────────────────────────────────────────────────

_REQUIRED_MARKERS = {"PRECEDENTS", "EVIDENCE", "STATUTES", "STRATEGY", "WINRATE"}


def _validate_combined(output: str) -> bool:
    found = set()
    for marker in _REQUIRED_MARKERS:
        if f"==={marker}===" in output.upper():
            found.add(marker)
    return len(found) >= 3


# ── Output parsing ────────────────────────────────────────────────────────────

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
    blended = max(1, min(99, round(0.4 * base_rate + 0.6 * llm_prob)))

    similar_cases = [
        {
            "rank": i + 1,
            "case_name": d.metadata.get("case_name", f"Case {i+1}"),
            "court": d.metadata.get("court", "Unknown court"),
            "court_type": d.metadata.get("court_type", "other"),
            "year": d.metadata.get("year", "Unknown year"),
            "case_type": d.metadata.get("case_type", "other"),
            "outcome": d.metadata.get("outcome", "Unknown"),
            "outcome_detail": d.metadata.get("outcome_detail", ""),
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

    judgments = []
    for c in similar_cases:
        if c["outcome"] and c["outcome"] != "Unknown":
            judgments.append({
                "case_name": c["case_name"],
                "court": c["court"],
                "year": c["year"],
                "outcome": c["outcome"],
                "outcome_detail": c["outcome_detail"],
                "statutes": c["statutes"],
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
            "stats": {"wins": wins, "losses": losses, "unknowns": len(docs) - total, "base_rate_pct": base_rate},
            "analysis": win_text,
        },
        "judgments": judgments,
    }


# ── Pipeline entry ────────────────────────────────────────────────────────────

def _emit(
    progress: Callable[[str, dict[str, Any]], None] | None,
    phase: str,
    data: dict[str, Any] | None = None,
) -> None:
    if progress:
        progress(phase, data or {})


def run_analysis(
    query: str,
    court_type: str | None = None,
    case_type: str | None = None,
    case_context: str | None = None,
    desired_outcome: str | None = None,
    progress: Callable[[str, dict[str, Any]], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> dict:
    """
    Full analysis pipeline. Accepts optional case metadata for better retrieval
    and prompt enrichment.
    """
    check_ollama_reachable()

    # Phase 1: Retrieval
    k = 12
    _emit(progress, "retrieve_start", {"k": k, "court_type": court_type, "case_type": case_type})
    try:
        docs = retrieve_docs(query, k=k, court_type=court_type, case_type=case_type)
    except Exception as e:
        _emit(progress, "phase_error", {"failed_phase": "retrieve", "detail": str(e)})
        raise
    _emit(progress, "retrieve_done", {"doc_count": len(docs)})

    if not docs:
        _emit(progress, "phase_error", {
            "failed_phase": "retrieve",
            "detail": "No documents found. Upload case PDFs to the library first.",
        })
        return _empty_result(query)

    if should_cancel and should_cancel():
        raise AnalysisCancelled()

    # Phase 2: Combined structured analysis via agent framework
    analysis_task = AgentTask(
        name="case_analysis",
        prompt_builder=_build_combined_prompt,
        model_key="fast",
        num_predict=1500,
        temperature=0.3,
        num_ctx=2048,
        max_retries=2,
        validator=_validate_combined,
    )

    prompt_context = {
        "query": query,
        "docs": docs,
        "court_type": court_type or "",
        "case_type": case_type or "",
        "case_context": case_context or "",
        "desired_outcome": desired_outcome or "",
    }

    _emit(progress, "fast_llm_start", {"task": "case_analysis"})
    try:
        if settings.ENABLE_PARALLEL_AGENTS:
            executor = ParallelExecutor([analysis_task], progress=progress, should_cancel=should_cancel)
        else:
            executor = SequentialExecutor([analysis_task], progress=progress, should_cancel=should_cancel)
        results = executor.run(prompt_context)
    except TaskCancelled:
        raise AnalysisCancelled()
    except Exception as e:
        _emit(progress, "phase_error", {"failed_phase": "fast_llm", "detail": str(e)})
        raise
    _emit(progress, "fast_llm_done", {})

    raw_analysis = results.get("case_analysis")
    if not raw_analysis or not raw_analysis.success:
        _emit(progress, "phase_error", {
            "failed_phase": "fast_llm",
            "detail": raw_analysis.error if raw_analysis else "no output",
        })
        return _empty_result(query)

    sections = _parse_combined_output(raw_analysis.output)
    agent_outputs = _build_agent_outputs(query, docs, sections)

    if should_cancel and should_cancel():
        raise AnalysisCancelled()

    # Phase 3: Executive summary
    prompt_context["agent_outputs"] = agent_outputs
    summary_task = AgentTask(
        name="executive_summary",
        prompt_builder=_build_summary_prompt,
        model_key="main",
        num_predict=700,
        temperature=0.4,
        num_ctx=2048,
        max_retries=2,
    )

    _emit(progress, "summary_llm_start", {"model": settings.LLM_MODEL})
    try:
        summary_executor = SequentialExecutor([summary_task], progress=progress, should_cancel=should_cancel)
        summary_results = summary_executor.run(prompt_context)
    except TaskCancelled:
        raise AnalysisCancelled()
    except Exception as e:
        _emit(progress, "phase_error", {"failed_phase": "summary_llm", "detail": str(e)})
        raise
    _emit(progress, "summary_llm_done", {})

    summary_result = summary_results.get("executive_summary")
    summary = summary_result.output if summary_result and summary_result.success else "Summary generation failed."

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


def _empty_result(query: str) -> dict:
    return {
        "query": query,
        "win_probability": 50,
        "summary": "No relevant case documents were found. Please upload PDFs to the case library.",
        "precedent": {"agent": "precedent", "similar_cases": [], "analysis": ""},
        "evidence": {"agent": "evidence", "analysis": ""},
        "statute": {"agent": "statute", "statutes_raw": [], "analysis": ""},
        "strategy": {"agent": "strategy", "analysis": ""},
        "winrate": {
            "agent": "winrate", "win_probability": 50, "base_rate": 50,
            "llm_estimate": 50,
            "stats": {"wins": 0, "losses": 0, "unknowns": 0, "base_rate_pct": 50},
            "analysis": "",
        },
        "judgments": [],
    }
