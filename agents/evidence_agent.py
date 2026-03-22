"""
agents/evidence_agent.py
Context formatter for evidence analysis.
Retrieval handled by shared_retriever; LLM call handled by master_agent.
"""

import os
from dotenv import load_dotenv
from langchain_ollama import ChatOllama

from shared_retriever import retrieve_docs, get_vectorstore

load_dotenv()

LLM_MODEL      = os.getenv("LLM_MODEL",      "deepseek-r1:8b")
FAST_LLM_MODEL = os.getenv("FAST_LLM_MODEL", "llama3.1:8b")


def build_context(docs: list, max_chars: int = 500) -> str:
    return "\n\n".join(
        f"[Evidence from case {i+1}]\n"
        f"Court: {d.metadata.get('court','')}\n"
        f"Outcome: {d.metadata.get('outcome','')}\n"
        f"Text: {d.page_content[:max_chars]}"
        for i, d in enumerate(docs)
    )


def run(query: str, docs: list | None = None) -> dict:
    """
    Standalone mode: fetches evidence-typed docs first, falls back to general.
    In the optimised pipeline, master_agent passes pre-fetched docs.
    """
    if docs is None:
        vs = get_vectorstore()
        retriever = vs.as_retriever(
            search_kwargs={"k": 5, "filter": {"must": [{"key": "section_type", "match": {"value": "evidence"}}]}}
        )
        docs = retriever.invoke(f"evidence proof documents witnesses: {query}")
        if not docs:
            docs = retrieve_docs(f"evidence proof documents: {query}", k=5)

    # Prefer evidence-typed docs from pre-fetched set
    evidence_docs = [d for d in docs if d.metadata.get("section_type") == "evidence"] or docs
    context = build_context(evidence_docs[:5])

    llm = ChatOllama(
        model=FAST_LLM_MODEL,
        num_predict=500,
        temperature=0.3,
        num_ctx=4096,
    )
    prompt = f"""You are a litigation strategy expert. Based on evidence patterns in similar cases below, advise what evidence to seek for this case.

Query: {query}

Evidence from similar cases:
{context}

List:
1. Physical/documentary evidence to gather
2. Witnesses to identify
3. Forensic evidence that may help
4. Priority (High / Medium / Low) for each

Be specific and practical. Max 250 words."""

    response = llm.invoke(prompt)

    return {
        "agent":       "evidence",
        "analysis":    response.content,
        "raw_context": context,
    }
