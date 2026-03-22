"""
agents/strategy_agent.py
Context formatter for legal strategy analysis.
Retrieval handled by shared_retriever; LLM call handled by master_agent.
"""

import os
from dotenv import load_dotenv
from langchain_ollama import ChatOllama

from shared_retriever import retrieve_docs

load_dotenv()

LLM_MODEL      = os.getenv("LLM_MODEL",      "deepseek-r1:8b")
FAST_LLM_MODEL = os.getenv("FAST_LLM_MODEL", "llama3.1:8b")


def build_context(docs: list, max_chars: int = 500) -> str:
    return "\n\n".join(
        f"[Strategy from {d.metadata.get('court','')} {d.metadata.get('year','')}]\n"
        f"Outcome: {d.metadata.get('outcome','')}\n"
        f"Text: {d.page_content[:max_chars]}"
        for d in docs
    )


def run(query: str, docs: list | None = None) -> dict:
    """
    Standalone mode: fetches its own docs if none provided.
    In the optimised pipeline, master_agent passes pre-fetched docs.
    """
    if docs is None:
        docs = retrieve_docs(f"arguments strategy framing submissions defence prosecution: {query}", k=5)

    arg_docs = [d for d in docs if d.metadata.get("section_type") == "arguments"] or docs
    context = build_context(arg_docs[:5])

    llm = ChatOllama(
        model=FAST_LLM_MODEL,
        num_predict=600,
        temperature=0.3,
        num_ctx=4096,
    )
    prompt = f"""You are a senior advocate. Based on outcomes in similar cases, suggest 2-3 distinct legal strategies.

Query: {query}

Case law context:
{context}

For each strategy:
- Strategy name (e.g. "Attack chain of custody")
- Core argument in one sentence
- Supporting precedent from the context
- Risk level: Low / Medium / High
- Estimated effectiveness given the case law

Be direct. Think like a lawyer preparing for trial. Max 300 words."""

    response = llm.invoke(prompt)

    return {
        "agent":       "strategy",
        "analysis":    response.content,
        "raw_context": context,
    }
