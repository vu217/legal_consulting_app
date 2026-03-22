"""
agents/winrate_agent.py
Context formatter for win-rate estimation.
Retrieval handled by shared_retriever; LLM call handled by master_agent.
"""

import os
import re
from dotenv import load_dotenv
from langchain_ollama import ChatOllama

from shared_retriever import retrieve_docs

load_dotenv()

LLM_MODEL      = os.getenv("LLM_MODEL",      "deepseek-r1:8b")
FAST_LLM_MODEL = os.getenv("FAST_LLM_MODEL", "llama3.1:8b")

WIN_OUTCOMES  = {"allowed", "acquitted", "upheld", "set aside", "quashed"}
LOSE_OUTCOMES = {"convicted", "sentenced", "dismissed", "remanded"}


def calc_base_rate(docs: list) -> dict:
    """Count wins/losses from outcome metadata in retrieved docs."""
    wins = losses = unknowns = 0
    for doc in docs:
        outcome = doc.metadata.get("outcome", "").lower().strip()
        if any(w in outcome for w in WIN_OUTCOMES):
            wins += 1
        elif any(l in outcome for l in LOSE_OUTCOMES):
            losses += 1
        else:
            unknowns += 1
    total = wins + losses
    rate  = round((wins / total) * 100) if total > 0 else 50
    return {"wins": wins, "losses": losses, "unknowns": unknowns, "base_rate_pct": rate}


def parse_llm_probability(text: str) -> int:
    """Extract the first numeric percentage from LLM output."""
    matches = re.findall(r"(\d{1,3})\s*%", text)
    if matches:
        vals = [int(m) for m in matches if 1 <= int(m) <= 99]
        return vals[0] if vals else 50
    return 50


def build_context(docs: list, max_chars: int = 300) -> str:
    return "\n\n".join(
        f"[Case {i+1}] Court:{d.metadata.get('court','')} | "
        f"Year:{d.metadata.get('year','')} | "
        f"Outcome:{d.metadata.get('outcome','unknown')} | "
        f"Text:{d.page_content[:max_chars]}"
        for i, d in enumerate(docs[:6])
    )


def run(query: str, docs: list | None = None) -> dict:
    """
    Standalone mode: fetches its own docs if none provided.
    In the optimised pipeline, master_agent passes pre-fetched docs.
    """
    if docs is None:
        docs = retrieve_docs(query, k=8)

    base   = calc_base_rate(docs)
    context = build_context(docs)

    llm = ChatOllama(
        model=FAST_LLM_MODEL,
        num_predict=500,
        temperature=0.3,
        num_ctx=4096,
    )
    prompt = f"""You are a quantitative legal analyst. Estimate the probability of winning this case.

Query: {query}

Similar case outcomes:
{context}

Base rate: {base['wins']} wins, {base['losses']} losses from {base['wins']+base['losses']} known outcomes.

Provide:
1. Win probability as a percentage (e.g. "65%")
2. Key factors that increase the probability
3. Key factors that decrease the probability
4. Confidence: Low / Medium / High

Be analytical. Ground your estimate in the case data. Max 250 words."""

    response = llm.invoke(prompt)
    llm_prob = parse_llm_probability(response.content)
    blended  = round(0.4 * base["base_rate_pct"] + 0.6 * llm_prob)

    return {
        "agent":           "winrate",
        "win_probability": blended,
        "base_rate":       base["base_rate_pct"],
        "llm_estimate":    llm_prob,
        "stats":           base,
        "analysis":        response.content,
        "raw_context":     context,
    }
