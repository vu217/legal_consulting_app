import logging
from dataclasses import dataclass
from backend.config import settings
from backend.services.qdrant_client import get_qdrant_client
from backend.services.ollama_client import embed_text
from backend.services.retrieval.bm25_index import get_bm25, get_corpus

logger = logging.getLogger(__name__)

RRF_K = 60  # Standard RRF constant


@dataclass
class RetrievedChunk:
    chunk_id: str
    text: str
    score: float
    payload: dict
    source_collections: list[str]  # which retrieval methods found this


def _rrf_score(rank: int) -> float:
    return 1.0 / (rank + RRF_K)


async def hybrid_retrieve(
    query: str,
    collection: str,
    legal_layer_filter: str | None = None,
    k: int | None = None,
) -> list[RetrievedChunk]:
    """
    Full hybrid retrieval: BM25 + Qdrant dense, fused via RRF.

    Args:
        query: The user query string (after any expansion).
        collection: "legal_statutes" | "legal_cases" | "both"
        legal_layer_filter: Optional Qdrant must-filter on legal_layer field.
        k: How many results to return (defaults to settings.final_k).

    Returns:
        List of RetrievedChunk sorted by descending RRF score.
    """
    if k is None:
        k = settings.final_k

    retrieval_k = settings.retrieval_k

    # ── Dense retrieval (Qdrant) ─────────────────────────────────────────────
    dense_results: list[dict] = []
    client = get_qdrant_client()

    collections_to_search = (
        [settings.collection_statutes, settings.collection_cases]
        if collection == "both"
        else [collection]
    )

    query_vector = await embed_text(query)

    from qdrant_client.http import models as qmodels

    for col in collections_to_search:
        # Build filter
        must_conditions = []
        if legal_layer_filter:
            must_conditions.append(
                qmodels.FieldCondition(
                    key="legal_layer",
                    match=qmodels.MatchValue(value=legal_layer_filter),
                )
            )

        query_filter = qmodels.Filter(must=must_conditions) if must_conditions else None

        try:
            hits = client.search(
                collection_name=col,
                query_vector=query_vector,
                limit=retrieval_k,
                query_filter=query_filter,
                with_payload=True,
            )
            for hit in hits:
                payload = hit.payload or {}
                payload["_qdrant_score"] = hit.score
                payload["_collection"] = col
                dense_results.append(payload)
        except Exception as e:
            logger.warning(f"Qdrant search failed for '{col}': {e}")

        # Fallback: if filtered results < 3, retry without filter
        if legal_layer_filter and len(dense_results) < 3:
            logger.info(f"Filtered results < 3 for '{col}'. Retrying without layer filter.")
            try:
                hits = client.search(
                    collection_name=col,
                    query_vector=query_vector,
                    limit=retrieval_k,
                    with_payload=True,
                )
                for hit in hits:
                    payload = hit.payload or {}
                    payload["_qdrant_score"] = hit.score
                    payload["_collection"] = col
                    dense_results.append(payload)
            except Exception as e:
                logger.warning(f"Fallback Qdrant search failed: {e}")

    # ── Sparse retrieval (BM25) ──────────────────────────────────────────────
    bm25_results: list[dict] = []
    bm25 = get_bm25()
    corpus_texts, corpus_ids, corpus_payloads = get_corpus()

    if bm25 is not None and corpus_texts:
        tokenised_query = query.lower().split()
        scores = bm25.get_scores(tokenised_query)

        # Get top-k indices by score
        top_indices = sorted(
            range(len(scores)), key=lambda i: scores[i], reverse=True
        )[:retrieval_k]

        for idx in top_indices:
            if scores[idx] <= 0:
                break
            payload = dict(corpus_payloads[idx])
            payload["_bm25_score"] = float(scores[idx])
            bm25_results.append(payload)

    # ── RRF Fusion ──────────────────────────────────────────────────────────
    rrf_scores: dict[str, float] = {}
    chunk_data: dict[str, dict] = {}

    for rank, payload in enumerate(dense_results):
        cid = payload.get("chunk_id", f"dense_{rank}")
        rrf_scores[cid] = rrf_scores.get(cid, 0.0) + _rrf_score(rank)
        if cid not in chunk_data:
            chunk_data[cid] = payload
        else:
            chunk_data[cid].setdefault("_sources", []).append("dense")

    for rank, payload in enumerate(bm25_results):
        cid = payload.get("chunk_id", f"bm25_{rank}")
        rrf_scores[cid] = rrf_scores.get(cid, 0.0) + _rrf_score(rank)
        if cid not in chunk_data:
            chunk_data[cid] = payload
        else:
            chunk_data[cid].setdefault("_sources", []).append("bm25")

    # Sort by RRF score descending
    sorted_ids = sorted(rrf_scores, key=lambda x: rrf_scores[x], reverse=True)

    results = []
    for cid in sorted_ids[:k]:
        payload = chunk_data[cid]
        results.append(RetrievedChunk(
            chunk_id=cid,
            text=payload.get("text", ""),
            score=rrf_scores[cid],
            payload=payload,
            source_collections=payload.get("_sources", ["dense"]),
        ))

    logger.info(
        f"Hybrid retrieve: {len(dense_results)} dense + {len(bm25_results)} BM25 "
        f"→ {len(results)} after RRF (collection: {collection})"
    )
    return results
