"""
agents/precedent_agent.py
Context formatter for precedent analysis.
Retrieval is handled by shared_retriever; LLM call is handled by master_agent.
This module remains importable for standalone use, but in the normal pipeline
master_agent.py calls shared_retriever directly and parses sections itself.
"""

import os
from dotenv import load_dotenv
from langchain_ollama import ChatOllama

from shared_retriever import retrieve_docs

load_dotenv()

LLM_MODEL      = os.getenv("LLM_MODEL",      "deepseek-r1:8b")
FAST_LLM_MODEL = os.getenv("FAST_LLM_MODEL", "llama3.1:8b")


def build_context(docs: list, max_chars: int = 600) -> str:
    """Format retrieved docs into a context string for the prompt."""
    return "\n\n".join(
        f"[Case {i+1}]\n"
        f"Court: {d.metadata.get('court','Unknown')}\n"
        f"Year: {d.metadata.get('year','Unknown')}\n"
        f"Outcome: {d.metadata.get('outcome','Unknown')}\n"
        f"Parties: {d.metadata.get('parties','Unknown')}\n"
        f"Text: {d.page_content[:max_chars]}"
        for i, d in enumerate(docs)
    )


def build_similar_cases(docs: list) -> list:
    """Build the similar_cases list consumed by dashboard.py."""
    return [
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


def run(query: str, docs: list | None = None) -> dict:
    """
    Standalone mode: fetches its own docs if none provided, then calls LLM.
    In the optimised pipeline, master_agent passes pre-fetched docs.
    """
    if docs is None:
        docs = retrieve_docs(f"similar cases precedents: {query}", k=5)

    context = build_context(docs)

    llm = ChatOllama(
        model=FAST_LLM_MODEL,
        num_predict=600,
        temperature=0.3,
        num_ctx=4096,
    )
    prompt = f"""You are a legal research assistant. Based on the cases below, identify the top 3 most relevant precedents for this query.

Query: {query}

Cases:
{context}

For each relevant case:
- Case name (if identifiable)
- Court and year
- Why it is relevant
- What the outcome was

Be concise. Use bullet points. Max 300 words."""

    response = llm.invoke(prompt)

    return {
        "agent":         "precedent",
        "similar_cases": build_similar_cases(docs),
        "analysis":      response.content,
        "raw_context":   context,
    }
