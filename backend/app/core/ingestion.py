"""PDF ingestion into Qdrant (path-stable, no CWD assumptions)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import fitz
from langchain_ollama import OllamaEmbeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, FieldCondition, Filter, MatchValue, VectorParams

from app import settings
from app.core.legal_chunker import chunk_legal_document
from app.core.ollama_config import get_ollama_num_gpu

_HAS_FIND_TABLES = hasattr(fitz.Page, "find_tables")


def get_or_create_collection() -> QdrantClient:
    client = QdrantClient(url=settings.QDRANT_URL)
    existing = [c.name for c in client.get_collections().collections]
    if settings.COLLECTION not in existing:
        client.create_collection(
            collection_name=settings.COLLECTION,
            vectors_config=VectorParams(size=settings.VECTOR_SIZE, distance=Distance.COSINE),
        )
    return client


def _table_to_markdown(table) -> str:
    try:
        import pandas as pd

        df = table.to_pandas()
        return df.to_markdown(index=False)
    except Exception:
        rows = table.extract()
        if not rows:
            return ""
        header = rows[0]
        sep = ["---"] * len(header)
        lines = [
            "| " + " | ".join(str(c or "") for c in header) + " |",
            "| " + " | ".join(sep) + " |",
        ]
        for row in rows[1:]:
            lines.append("| " + " | ".join(str(c or "") for c in row) + " |")
        return "\n".join(lines)


def extract_text(pdf_path: str) -> str:
    doc = fitz.open(pdf_path)
    pages = []
    for page in doc:
        page_text = page.get_text()
        if _HAS_FIND_TABLES:
            try:
                tables = page.find_tables()
                for table in tables:
                    md = _table_to_markdown(table)
                    if md:
                        page_text += f"\n\n[TABLE]\n{md}\n[/TABLE]\n"
            except Exception:
                pass
        pages.append(page_text)
    return "\n".join(pages)


def delete_qdrant_points_for_source(source_path: str) -> int:
    """
    Remove existing vectors for a PDF before re-ingesting (avoids duplicates).
    Tries common LangChain/Qdrant payload keys for `Document.metadata["source"]`.
    """
    client = QdrantClient(url=settings.QDRANT_URL)
    norm = str(Path(source_path).resolve())
    variants = {norm, source_path, str(Path(source_path))}
    removed = 0
    for key in ("source", "metadata.source"):
        for val in variants:
            try:
                flt = Filter(must=[FieldCondition(key=key, match=MatchValue(value=val))])
                page_offset = None
                while True:
                    points, page_offset = client.scroll(
                        collection_name=settings.COLLECTION,
                        scroll_filter=flt,
                        limit=256,
                        offset=page_offset,
                        with_payload=False,
                        with_vectors=False,
                    )
                    if not points:
                        break
                    client.delete(
                        collection_name=settings.COLLECTION,
                        points_selector=[p.id for p in points],
                    )
                    removed += len(points)
                    if page_offset is None:
                        break
            except Exception:
                continue
    return removed


def ingest_single_pdf(pdf_path: str, replace_existing: bool = True) -> dict:
    path = str(Path(pdf_path).resolve())
    try:
        text = extract_text(path)
        if not text.strip():
            return {"file": path, "status": "skipped", "chunks": 0, "reason": "empty text"}

        if replace_existing:
            delete_qdrant_points_for_source(path)

        docs = chunk_legal_document(path, text)
        embeddings = OllamaEmbeddings(
            model=settings.EMBED_MODEL,
            num_gpu=get_ollama_num_gpu(),
        )
        get_or_create_collection()
        QdrantVectorStore.from_documents(
            docs,
            embeddings,
            url=settings.QDRANT_URL,
            collection_name=settings.COLLECTION,
        )
        return {"file": path, "status": "ok", "chunks": len(docs)}
    except Exception as e:
        return {"file": path, "status": "error", "chunks": 0, "reason": str(e)}


def ingest_all_pdfs(pdf_dir: Path | None = None, max_workers: int = 4) -> list:
    folder = Path(pdf_dir) if pdf_dir else settings.PDF_DIR
    pdf_files = list(folder.glob("*.pdf"))
    if not pdf_files:
        return [{"file": str(folder), "status": "error", "reason": "no PDFs found"}]
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(ingest_single_pdf, str(p)): p for p in pdf_files}
        for future in futures:
            results.append(future.result())
    return results


def ingest_pdf(file_path: str) -> int:
    result = ingest_single_pdf(file_path)
    if result["status"] == "error":
        raise RuntimeError(result.get("reason", "ingestion failed"))
    return result["chunks"]
