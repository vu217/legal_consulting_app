import json
import logging
from pathlib import Path
from fastapi import APIRouter, HTTPException
from backend.config import settings
from backend.services.ingestion.classifier import classify_document
from backend.services.ingestion.preprocessor import clean_text
from backend.services.ingestion.manifest import get_new_pdfs, mark_ingested
from backend.services.ingestion.embedder import embed_and_upsert
from backend.services.ingestion.graph_builder import build_graph_from_chunks
from backend.services.graph_store import get_graph, save_graph
from backend.services.retrieval.bm25_index import build_bm25_index
from backend.services.ingestion.chunkers import legislative, comparison, casebook, judgment
import fitz

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ingest", tags=["ingest"])


def _extract_text_pages(pdf_path: Path) -> list[str]:
    doc = fitz.open(str(pdf_path))
    pages = [doc[i].get_text("text") for i in range(len(doc))]
    doc.close()
    return pages


@router.post("/")
async def ingest_documents():
    """
    Scan PDF_DIR for new or changed PDFs, chunk them, embed them, and upsert
    into Qdrant. Also rebuilds the knowledge graph and BM25 index.
    """
    pdf_dir = settings.pdf_dir
    if not pdf_dir.exists():
        pdf_dir.mkdir(parents=True, exist_ok=True)

    new_pdfs = get_new_pdfs(pdf_dir)

    if not new_pdfs:
        return {
            "status": "ok",
            "message": "No new or changed PDFs found.",
            "processed": 0,
        }

    crpc_bnss_map: dict[str, str] = {}
    all_chunks = []
    results = []

    for pdf_path in new_pdfs:
        logger.info(f"Processing: {pdf_path.name}")

        try:
            doc_type = classify_document(pdf_path)
            pages = _extract_text_pages(pdf_path)
            clean_pages = [clean_text(p) for p in pages]
            full_text = "\n\n".join(clean_pages)
            source_name = pdf_path.name

            if doc_type == "legislative_act":
                chunks = legislative.chunk_legislative(full_text, source_name)

            elif doc_type == "comparison_table":
                chunks, new_map = comparison.chunk_comparison(pdf_path, source_name)
                crpc_bnss_map.update(new_map)

            elif doc_type == "casebook":
                chunks = casebook.chunk_casebook(full_text, source_name)

            elif doc_type == "judgment":
                chunks = judgment.chunk_judgment(full_text, source_name)

            else:
                logger.warning(f"Unknown doc_type '{doc_type}' for {pdf_path.name}. Skipping.")
                continue

            all_chunks.extend(chunks)

            upsert_counts = await embed_and_upsert(chunks)

            mark_ingested(pdf_path)

            results.append({
                "file": pdf_path.name,
                "type": doc_type,
                "chunks": len(chunks),
                "upserted": upsert_counts,
            })

            logger.info(f"Done: {pdf_path.name} ({doc_type}, {len(chunks)} chunks)")

        except Exception as e:
            logger.error(f"Failed to process {pdf_path.name}: {e}", exc_info=True)
            results.append({"file": pdf_path.name, "error": str(e)})

    # Persist CrPC→BNS map if we got one
    if crpc_bnss_map:
        map_path = settings.crpc_bnss_map_path
        map_path.parent.mkdir(parents=True, exist_ok=True)
        with open(map_path, "w") as f:
            json.dump(crpc_bnss_map, f, indent=2)
        logger.info(f"Saved CrPC→BNS map: {len(crpc_bnss_map)} entries to {map_path}")

    # Rebuild graph
    if all_chunks:
        logger.info("Rebuilding knowledge graph...")
        existing_graph = get_graph()
        updated_graph = build_graph_from_chunks(
            all_chunks,
            existing_graph=existing_graph,
            crpc_to_bnss=crpc_bnss_map,
        )
        # Replace global graph
        import backend.services.graph_store as _gs
        _gs._graph = updated_graph
        save_graph()

    # Rebuild BM25 index
    logger.info("Rebuilding BM25 index...")
    build_bm25_index()

    return {
        "status": "ok",
        "processed": len([r for r in results if "error" not in r]),
        "failed": len([r for r in results if "error" in r]),
        "crpc_bnss_entries": len(crpc_bnss_map),
        "details": results,
    }
