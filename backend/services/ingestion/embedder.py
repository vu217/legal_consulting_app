import logging
import uuid
from qdrant_client.http import models as qmodels
from backend.config import settings
from backend.services.ingestion import Chunk
from backend.services.qdrant_client import get_qdrant_client
from backend.services.ollama_client import embed_text

logger = logging.getLogger(__name__)

_STATUTE_LAYERS = {"statute", "comparison"}
_CASE_LAYERS = {"case_ratio", "case_facts", "case_analysis", "doctrine"}
_SKIP_LAYERS = {"syllabus"}

BATCH_SIZE = 10  # Embed and upsert in batches to avoid OOM on 16GB RAM


def _route_collection(chunk: Chunk) -> str | None:
    if chunk.legal_layer in _STATUTE_LAYERS:
        return settings.collection_statutes
    if chunk.legal_layer in _CASE_LAYERS:
        return settings.collection_cases
    if chunk.legal_layer in _SKIP_LAYERS:
        return None  # Skip entirely
    logger.warning(f"Unknown legal_layer '{chunk.legal_layer}' for chunk {chunk.chunk_id}. Skipping.")
    return None


async def embed_and_upsert(chunks: list[Chunk]) -> dict[str, int]:
    """
    Embed each chunk and upsert into the correct Qdrant collection.
    Returns dict with counts: {collection_name: count_upserted}
    Skips syllabus-layer chunks entirely.
    Processes in batches of BATCH_SIZE.
    """
    client = get_qdrant_client()
    counts: dict[str, int] = {
        settings.collection_statutes: 0,
        settings.collection_cases: 0,
        "skipped": 0,
    }

    # Group chunks by target collection
    routed: dict[str, list[Chunk]] = {
        settings.collection_statutes: [],
        settings.collection_cases: [],
    }

    for chunk in chunks:
        collection = _route_collection(chunk)
        if collection is None:
            counts["skipped"] += 1
            continue
        routed[collection].append(chunk)

    # Process each collection
    for collection_name, col_chunks in routed.items():
        if not col_chunks:
            continue

        logger.info(f"Upserting {len(col_chunks)} chunks to '{collection_name}'...")

        for i in range(0, len(col_chunks), BATCH_SIZE):
            batch = col_chunks[i:i + BATCH_SIZE]
            points = []

            for chunk in batch:
                try:
                    vector = await embed_text(chunk.text)
                except Exception as e:
                    logger.error(f"Embedding failed for {chunk.chunk_id}: {e}. Skipping.")
                    counts["skipped"] += 1
                    continue

                point = qmodels.PointStruct(
                    id=str(uuid.uuid5(uuid.NAMESPACE_DNS, chunk.chunk_id)),
                    vector=vector,
                    payload=chunk.to_qdrant_payload(),
                )
                points.append(point)

            if points:
                try:
                    client.upsert(
                        collection_name=collection_name,
                        points=points,
                        wait=True,
                    )
                    counts[collection_name] += len(points)
                except Exception as e:
                    logger.error(f"Upsert failed for batch {i}-{i+BATCH_SIZE}: {e}")

    logger.info(f"Upsert complete: {counts}")
    return counts
