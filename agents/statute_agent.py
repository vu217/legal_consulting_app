"""
agents/statute_agent.py
Context formatter for statute analysis.
Retrieval handled by shared_retriever; LLM call handled by master_agent.
"""

import os
from dotenv import load_dotenv
from langchain_ollama import ChatOllama

from shared_retriever import retrieve_docs

load_dotenv()

LLM_MODEL      = os.getenv("LLM_MODEL",      "deepseek-r1:8b")
FAST_LLM_MODEL = os.getenv("FAST_LLM_MODEL", "llama3.1:8b")


def collect_statutes(docs: list) -> list:
    """Extract and deduplicate statute references from doc metadata."""
    all_statutes = []
    for doc in docs:
        s = doc.metadata.get("statutes", "")
        if s:
            all_statutes.extend([x.strip() for x in s.split(";") if x.strip()])
    return list(dict.fromkeys(all_statutes))[:15]


def build_context(docs: list, max_chars: int = 400) -> str:
    return "\n\n".join(
        f"[Source {i+1}]\n"
        f"Statutes: {d.metadata.get('statutes','')}\n"
        f"Outcome: {d.metadata.get('outcome','')}\n"
        f"Text: {d.page_content[:max_chars]}"
        for i, d in enumerate(docs)
    )


def run(query: str, docs: list | None = None) -> dict:
    """
    Standalone mode: fetches its own docs if none provided.
    In the optimised pipeline, master_agent passes pre-fetched docs.
    """
    if docs is None:
        docs = retrieve_docs(f"statutes sections acts law provisions: {query}", k=6)

    statute_docs = [d for d in docs if d.metadata.get("section_type") == "statutes"] or docs
    context = build_context(statute_docs[:6])
    all_statutes = collect_statutes(docs)

    llm = ChatOllama(
        model=FAST_LLM_MODEL,
        num_predict=500,
        temperature=0.3,
        num_ctx=4096,
    )
    prompt = f"""You are a legal expert. Based on the case law below, identify which statutes apply to this situation.

Query: {query}

Relevant case extracts:
{context}

For each applicable statute or section:
- Section number and act name
- FAVOURABLE or ADVERSE to the querying party
- Brief reason why it applies

Group into: Favourable statutes | Adverse statutes | Neutral/procedural
Max 250 words."""

    response = llm.invoke(prompt)

    return {
        "agent":        "statute",
        "statutes_raw": all_statutes,
        "analysis":     response.content,
        "raw_context":  context,
    }
