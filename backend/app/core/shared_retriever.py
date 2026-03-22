"""Singleton OllamaEmbeddings + QdrantVectorStore for retrieval with metadata filtering."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from langchain_ollama import OllamaEmbeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue

from app import settings
from app.core.ollama_config import get_ollama_num_gpu

_log = logging.getLogger("uvicorn.error")
_vectorstore: QdrantVectorStore | None = None
_lock = threading.Lock()

MAX_RETRIES = 3
RETRY_BACKOFF = 1.5


def get_vectorstore() -> QdrantVectorStore:
    global _vectorstore
    if _vectorstore is None:
        with _lock:
            if _vectorstore is None:
                embeddings = OllamaEmbeddings(
                    model=settings.EMBED_MODEL,
                    num_gpu=get_ollama_num_gpu(),
                )
                _vectorstore = QdrantVectorStore.from_existing_collection(
                    embedding=embeddings,
                    url=settings.QDRANT_URL,
                    collection_name=settings.COLLECTION,
                )
    return _vectorstore


def _build_qdrant_filter(
    court_type: str | None = None,
    case_type: str | None = None,
) -> Filter | None:
    conditions = []
    if court_type and court_type != "other":
        conditions.append(
            FieldCondition(key="metadata.court_type", match=MatchValue(value=court_type))
        )
    if case_type and case_type != "other":
        conditions.append(
            FieldCondition(key="metadata.case_type", match=MatchValue(value=case_type))
        )
    if not conditions:
        return None
    return Filter(should=conditions)


def retrieve_docs(
    query: str,
    k: int = 12,
    court_type: str | None = None,
    case_type: str | None = None,
) -> list:
    """
    Retrieve similar documents with optional metadata filtering.
    Uses Qdrant 'should' (OR) filter so matching court/case type boosts relevance
    without excluding documents that don't match.
    Falls back to unfiltered search if filtered returns too few results.
    Includes retry logic for Qdrant connection resilience.
    """
    vs = get_vectorstore()
    qdrant_filter = _build_qdrant_filter(court_type, case_type)

    for attempt in range(MAX_RETRIES):
        try:
            if qdrant_filter:
                search_kwargs: dict[str, Any] = {"k": k, "filter": qdrant_filter}
                retriever = vs.as_retriever(search_kwargs=search_kwargs)
                docs = retriever.invoke(query)

                if len(docs) < 3:
                    _log.info(
                        "Filtered retrieval returned %d docs (< 3), falling back to unfiltered",
                        len(docs),
                    )
                    retriever = vs.as_retriever(search_kwargs={"k": k})
                    docs = retriever.invoke(query)
            else:
                retriever = vs.as_retriever(search_kwargs={"k": k})
                docs = retriever.invoke(query)

            return docs

        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF ** (attempt + 1)
                _log.warning(
                    "Retrieval attempt %d failed (%s), retrying in %.1fs",
                    attempt + 1, e, wait,
                )
                time.sleep(wait)
                reset_vectorstore_cache()
            else:
                raise


def reset_vectorstore_cache() -> None:
    """Clear cached store (e.g. after collection recreation)."""
    global _vectorstore
    with _lock:
        _vectorstore = None
