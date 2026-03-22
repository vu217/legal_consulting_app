"""Singleton OllamaEmbeddings + QdrantVectorStore for retrieval."""

from __future__ import annotations

import threading

from langchain_ollama import OllamaEmbeddings
from langchain_qdrant import QdrantVectorStore

from app import settings
from app.core.ollama_config import get_ollama_num_gpu

_vectorstore: QdrantVectorStore | None = None
_lock = threading.Lock()


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


def retrieve_docs(query: str, k: int = 12) -> list:
    vs = get_vectorstore()
    retriever = vs.as_retriever(search_kwargs={"k": k})
    return retriever.invoke(query)


def reset_vectorstore_cache() -> None:
    """Clear cached store (e.g. after collection recreation)."""
    global _vectorstore
    with _lock:
        _vectorstore = None
