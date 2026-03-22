"""
shared_retriever.py
Module-level singleton for OllamaEmbeddings + QdrantVectorStore.
All agents import from here instead of creating their own connections,
eliminating 5 redundant embedding-model loads per query.
"""

import os
import threading
from dotenv import load_dotenv
from langchain_ollama import OllamaEmbeddings
from langchain_qdrant import QdrantVectorStore

load_dotenv()

QDRANT_URL  = os.getenv("QDRANT_URL",  "http://localhost:6333")
COLLECTION  = os.getenv("COLLECTION",  "legal_cases")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")

_vectorstore: QdrantVectorStore | None = None
_lock = threading.Lock()


def get_vectorstore() -> QdrantVectorStore:
    """Return the cached vectorstore, creating it once on first call."""
    global _vectorstore
    if _vectorstore is None:
        with _lock:
            if _vectorstore is None:
                embeddings = OllamaEmbeddings(model=EMBED_MODEL)
                _vectorstore = QdrantVectorStore.from_existing_collection(
                    embedding=embeddings,
                    url=QDRANT_URL,
                    collection_name=COLLECTION,
                )
    return _vectorstore


def retrieve_docs(query: str, k: int = 12) -> list:
    """
    Single retrieval call that fetches k docs.
    Agents use this instead of creating their own retriever.
    """
    vs = get_vectorstore()
    retriever = vs.as_retriever(search_kwargs={"k": k})
    return retriever.invoke(query)
