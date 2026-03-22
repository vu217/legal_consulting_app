"""
ingestion.py
Parallel PDF ingestion pipeline.
Reads PDFs from the pdfs/ folder (or a single file path),
runs legal_chunker, embeds with nomic-embed-text, stores in Qdrant.

Table-aware extraction: uses PyMuPDF find_tables() (>=1.23.0) to preserve
tabular structure as markdown so the chunker can index it correctly.
"""

import os
import asyncio
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import fitz  # pymupdf
from dotenv import load_dotenv
from langchain_ollama import OllamaEmbeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

from legal_chunker import chunk_legal_document

load_dotenv()

QDRANT_URL   = os.getenv("QDRANT_URL",   "http://localhost:6333")
COLLECTION   = os.getenv("COLLECTION",   "legal_cases")
EMBED_MODEL  = os.getenv("EMBED_MODEL",  "nomic-embed-text")
VECTOR_SIZE  = int(os.getenv("VECTOR_SIZE", "768"))
PDF_DIR      = Path("pdfs")

# PyMuPDF >= 1.23.0 ships find_tables(). Detect availability once at import time.
_HAS_FIND_TABLES = hasattr(fitz.Page, "find_tables")


# ── Qdrant setup ──────────────────────────────────────────────────────────────

def get_or_create_collection():
    client = QdrantClient(url=QDRANT_URL)
    existing = [c.name for c in client.get_collections().collections]
    if COLLECTION not in existing:
        client.create_collection(
            collection_name=COLLECTION,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
    return client


# ── Single PDF processing ─────────────────────────────────────────────────────

def _table_to_markdown(table) -> str:
    """
    Convert a PyMuPDF Table object to a markdown-formatted string.
    Works with or without pandas installed.
    """
    try:
        import pandas as pd
        df = table.to_pandas()
        return df.to_markdown(index=False)
    except Exception:
        # Fallback: manual markdown table
        rows = table.extract()
        if not rows:
            return ""
        header = rows[0]
        sep    = ["---"] * len(header)
        lines  = [
            "| " + " | ".join(str(c or "") for c in header) + " |",
            "| " + " | ".join(sep) + " |",
        ]
        for row in rows[1:]:
            lines.append("| " + " | ".join(str(c or "") for c in row) + " |")
        return "\n".join(lines)


def extract_text(pdf_path: str) -> str:
    """
    Extract text from every page. When find_tables() is available, tables are
    extracted as markdown blocks tagged [TABLE]...[/TABLE] so the chunker can
    keep them intact and assign section_type="table".
    """
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
                pass  # Non-critical: fall through with plain text

        pages.append(page_text)

    return "\n".join(pages)


def ingest_single_pdf(pdf_path: str) -> dict:
    """Ingest one PDF. Returns a status dict."""
    try:
        text = extract_text(pdf_path)
        if not text.strip():
            return {"file": pdf_path, "status": "skipped", "chunks": 0, "reason": "empty text"}

        docs = chunk_legal_document(pdf_path, text)

        embeddings = OllamaEmbeddings(model=EMBED_MODEL)
        get_or_create_collection()

        QdrantVectorStore.from_documents(
            docs,
            embeddings,
            url=QDRANT_URL,
            collection_name=COLLECTION,
        )
        return {"file": pdf_path, "status": "ok", "chunks": len(docs)}

    except Exception as e:
        return {"file": pdf_path, "status": "error", "chunks": 0, "reason": str(e)}


# ── Batch ingestion (parallel) ────────────────────────────────────────────────

def ingest_all_pdfs(pdf_dir: str = None, max_workers: int = 4) -> list:
    """
    Ingest all PDFs in pdf_dir (default: ./pdfs) in parallel.
    Returns list of status dicts.
    """
    folder = Path(pdf_dir) if pdf_dir else PDF_DIR
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
    """
    Convenience wrapper used by dashboard.py upload handler.
    Returns number of chunks ingested.
    """
    result = ingest_single_pdf(file_path)
    if result["status"] == "error":
        raise RuntimeError(result.get("reason", "ingestion failed"))
    return result["chunks"]


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    print("Starting batch ingestion from ./pdfs ...")
    results = ingest_all_pdfs()
    for r in results:
        print(json.dumps(r, indent=2))
    total = sum(r["chunks"] for r in results)
    ok    = sum(1 for r in results if r["status"] == "ok")
    print(f"\nDone: {ok}/{len(results)} files ingested, {total} total chunks.")
