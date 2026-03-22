"""
master_agent.py
Optimised pipeline for local LLM execution:
  1. Single Qdrant retrieval (shared_retriever, k=12)
  2. One fast-model call (llama3.1:8b) produces all 5 analysis sections at once
  3. One R1 synthesis call (deepseek-r1:8b) generates the executive summary

Total LLM calls reduced from 6 → 2 compared to the original design.
"""

import os
import re
import subprocess
from dotenv import load_dotenv
from langchain_ollama import ChatOllama

from shared_retriever import retrieve_docs
from agents import precedent_agent, evidence_agent, statute_agent, strategy_agent, winrate_agent

load_dotenv()

LLM_MODEL      = os.getenv("LLM_MODEL",      "deepseek-r1:8b")
FAST_LLM_MODEL = os.getenv("FAST_LLM_MODEL", "llama3.1:8b")


def _resolve_fast_model() -> str:
    """
    Return FAST_LLM_MODEL if it is available in the local Ollama registry,
    otherwise fall back to LLM_MODEL so the app still works while llama3.1
    is being downloaded.
    """
    try:
        result = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=5)
        if FAST_LLM_MODEL.split(":")[0] in result.stdout:
            return FAST_LLM_MODEL
    except Exception:
        pass
    return LLM_MODEL


_FAST_MODEL = _resolve_fast_model()


def _strip_thinking(text: str) -> str:
    """Remove <think>...</think> reasoning blocks produced by deepseek-r1."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _build_combined_prompt(query: str, docs: list) -> str:
    """
    Build a single structured prompt for the fast model.
    Docs are routed by section_type so each section gets the most relevant context.
    """
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

    # Route docs by section type for targeted context
    by_type: dict[str, list] = {}
    for d in docs:
        st = d.metadata.get("section_type", "other")
        by_type.setdefault(st, []).append(d)

    evidence_docs  = by_type.get("evidence", []) or docs[:4]
    statute_docs   = by_type.get("statutes", []) or docs[:4]
    argument_docs  = by_type.get("arguments", []) or docs[:4]
    all_docs       = docs

    precedent_ctx = fmt(all_docs[:5])
    evidence_ctx  = fmt(evidence_docs[:4])
    statute_ctx   = fmt(statute_docs[:4])
    strategy_ctx  = fmt(argument_docs[:4])
    winrate_ctx   = fmt(all_docs[:6], max_chars=250)

    # Compute base rate inline for winrate section
    win_outcomes  = {"allowed", "acquitted", "upheld", "set aside", "quashed"}
    lose_outcomes = {"convicted", "sentenced", "dismissed", "remanded"}
    wins = sum(1 for d in docs if any(w in d.metadata.get("outcome","").lower() for w in win_outcomes))
    losses = sum(1 for d in docs if any(l in d.metadata.get("outcome","").lower() for l in lose_outcomes))
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
    """Split the combined LLM output by section markers into individual analysis strings."""
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
    """Extract numeric win probability from winrate text."""
    matches = re.findall(r"(\d{1,3})\s*%", text)
    if matches:
        vals = [int(m) for m in matches if 1 <= int(m) <= 99]
        return vals[0] if vals else 50
    return 50


def _build_agent_outputs(query: str, docs: list, sections: dict) -> dict:
    """
    Reconstruct the same output dict structure the old agents returned,
    so dashboard.py needs zero changes.
    """
    win_text   = sections.get("winrate", "")
    llm_prob   = _parse_winrate_probability(win_text)

    # Base rate from metadata outcomes
    win_outcomes  = {"allowed", "acquitted", "upheld", "set aside", "quashed"}
    lose_outcomes = {"convicted", "sentenced", "dismissed", "remanded"}
    wins   = sum(1 for d in docs if any(w in d.metadata.get("outcome","").lower() for w in win_outcomes))
    losses = sum(1 for d in docs if any(l in d.metadata.get("outcome","").lower() for l in lose_outcomes))
    total  = wins + losses
    base_rate = round((wins / total) * 100) if total > 0 else 50
    blended   = round(0.4 * base_rate + 0.6 * llm_prob)

    # Build similar_cases list from retrieved docs (for dashboard precedent cards)
    similar_cases = [
        {
            "rank":      i + 1,
            "case_name": d.metadata.get("case_name", f"Case {i+1}"),
            "court":     d.metadata.get("court",     "Unknown court"),
            "year":      d.metadata.get("year",      "Unknown year"),
            "outcome":   d.metadata.get("outcome",   "Unknown"),
            "parties":   d.metadata.get("parties",   ""),
            "statutes":  d.metadata.get("statutes",  ""),
            "chunk":     d.page_content[:400],
            "source":    d.metadata.get("source",    ""),
        }
        for i, d in enumerate(docs[:5])
    ]

    # Collect statutes from metadata for the statute pills in the dashboard
    all_statutes = []
    for d in docs:
        s = d.metadata.get("statutes", "")
        if s:
            all_statutes.extend([x.strip() for x in s.split(";") if x.strip()])
    all_statutes = list(dict.fromkeys(all_statutes))[:15]

    return {
        "precedent": {
            "agent":         "precedent",
            "similar_cases": similar_cases,
            "analysis":      sections.get("precedents", ""),
        },
        "evidence": {
            "agent":    "evidence",
            "analysis": sections.get("evidence", ""),
        },
        "statute": {
            "agent":        "statute",
            "statutes_raw": all_statutes,
            "analysis":     sections.get("statutes", ""),
        },
        "strategy": {
            "agent":    "strategy",
            "analysis": sections.get("strategy", ""),
        },
        "winrate": {
            "agent":           "winrate",
            "win_probability": blended,
            "base_rate":       base_rate,
            "llm_estimate":    llm_prob,
            "stats":           {"wins": wins, "losses": losses, "unknowns": len(docs) - total, "base_rate_pct": base_rate},
            "analysis":        win_text,
        },
    }


def _run_combined_analysis(query: str, docs: list) -> dict:
    """Call 1: fast model produces all 5 analysis sections in one pass."""
    prompt = _build_combined_prompt(query, docs)
    fast_llm = ChatOllama(
        model=_FAST_MODEL,
        num_predict=1200,
        temperature=0.3,
        num_ctx=4096,
    )
    response = fast_llm.invoke(prompt)
    raw = _strip_thinking(response.content)
    sections = _parse_combined_output(raw)
    return _build_agent_outputs(query, docs, sections)


def _compile_summary(query: str, agent_outputs: dict) -> str:
    """Call 2: R1 synthesis — strip <think> block from output."""
    precedent_text = agent_outputs.get("precedent", {}).get("analysis", "N/A")
    evidence_text  = agent_outputs.get("evidence",  {}).get("analysis", "N/A")
    statute_text   = agent_outputs.get("statute",   {}).get("analysis", "N/A")
    strategy_text  = agent_outputs.get("strategy",  {}).get("analysis", "N/A")
    winrate_text   = agent_outputs.get("winrate",   {}).get("analysis", "N/A")
    win_prob       = agent_outputs.get("winrate",   {}).get("win_probability", "?")

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
        model=LLM_MODEL,
        num_predict=700,
        temperature=0.4,
        num_ctx=4096,
    )
    response = r1_llm.invoke(prompt)
    return _strip_thinking(response.content)


def run_analysis(query: str) -> dict:
    """
    Main entry point called by dashboard.py.
    Returns the full structured result dict (same schema as before).
    """
    # Phase 1: single retrieval for all agents combined
    docs = retrieve_docs(query, k=12)

    # Phase 2: one fast-model pass for all 5 analysis sections
    agent_outputs = _run_combined_analysis(query, docs)

    # Phase 3: R1 executive synthesis
    summary = _compile_summary(query, agent_outputs)

    win_prob = agent_outputs.get("winrate", {}).get("win_probability", 50)

    return {
        "query":           query,
        "win_probability": win_prob,
        "summary":         summary,
        "precedent":       agent_outputs.get("precedent", {}),
        "evidence":        agent_outputs.get("evidence",  {}),
        "statute":         agent_outputs.get("statute",   {}),
        "strategy":        agent_outputs.get("strategy",  {}),
        "winrate":         agent_outputs.get("winrate",   {}),
    }
