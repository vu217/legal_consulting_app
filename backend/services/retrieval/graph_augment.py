import logging
from backend.services.retrieval.hybrid import RetrievedChunk
from backend.services.graph_store import get_graph
from backend.services.qdrant_client import get_qdrant_client
from backend.config import settings
from backend.services.ingestion.graph_builder import (
    INTERPRETED_BY, FOLLOWED_BY, EXCEPTION_TO, REPLACED_BY,
)

logger = logging.getLogger(__name__)

MAX_AUGMENTED = 12   # Hard cap on total chunks after augmentation
MAX_HOPS = 2         # Maximum graph traversal depth


def _fetch_chunk_by_id(chunk_id: str) -> RetrievedChunk | None:
    """Fetch a chunk from Qdrant by its chunk_id payload field."""
    client = get_qdrant_client()

    from qdrant_client.http import models as qmodels

    for collection_name in [settings.collection_statutes, settings.collection_cases]:
        try:
            results, _ = client.scroll(
                collection_name=collection_name,
                scroll_filter=qmodels.Filter(
                    must=[
                        qmodels.FieldCondition(
                            key="chunk_id",
                            match=qmodels.MatchValue(value=chunk_id),
                        )
                    ]
                ),
                limit=1,
                with_payload=True,
                with_vectors=False,
            )
            if results:
                payload = results[0].payload or {}
                return RetrievedChunk(
                    chunk_id=chunk_id,
                    text=payload.get("text", ""),
                    score=0.5,   # Augmented chunks get a fixed mid score
                    payload=payload,
                    source_collections=["graph_augment"],
                )
        except Exception:
            continue
    return None


def augment_with_graph(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """
    Augment the retrieved chunk list using graph edges.

    For statute chunks -> follow INTERPRETED_BY edges -> add related case ratio chunks.
    For case chunks -> follow reverse INTERPRETED_BY edges -> add related statute chunks.
    For case chunks -> follow FOLLOWED_BY edges up to MAX_HOPS -> add downstream cases.

    Cap final result at MAX_AUGMENTED chunks.
    When trimming, prefer case_ratio and statute layers.
    """
    G = get_graph()

    if G.number_of_nodes() == 0:
        logger.info("Graph is empty — skipping augmentation.")
        return chunks

    existing_ids = {c.chunk_id for c in chunks}
    augmented: list[RetrievedChunk] = []

    for chunk in chunks:
        layer = chunk.payload.get("legal_layer", "")
        act = chunk.payload.get("act", "BNS")
        section_num = chunk.payload.get("section_number", "")
        case_name = chunk.payload.get("case_name", "")

        if layer == "statute" and section_num and section_num != "intro":
            # Find cases that interpret this statute section
            statute_node = f"{act} S.{section_num}"
            if G.has_node(statute_node):
                for _, case_node, edge_data in G.out_edges(statute_node, data=True):
                    if edge_data.get("relation") == INTERPRETED_BY:
                        fetched = _fetch_by_case_name(case_node, "case_ratio")
                        if fetched and fetched.chunk_id not in existing_ids:
                            augmented.append(fetched)
                            existing_ids.add(fetched.chunk_id)

        elif layer in ("case_ratio", "case_facts", "case_analysis") and case_name:
            # Find statute sections this case interprets (reverse INTERPRETED_BY)
            if G.has_node(case_name):
                for statute_node, _, edge_data in G.in_edges(case_name, data=True):
                    if edge_data.get("relation") == INTERPRETED_BY:
                        fetched = _fetch_by_section_node(statute_node)
                        if fetched and fetched.chunk_id not in existing_ids:
                            augmented.append(fetched)
                            existing_ids.add(fetched.chunk_id)

                # Follow FOLLOWED_BY edges for downstream cases (max MAX_HOPS)
                visited = {case_name}
                frontier = [case_name]
                for _ in range(MAX_HOPS):
                    next_frontier = []
                    for node in frontier:
                        for _, successor, edge_data in G.out_edges(node, data=True):
                            if (
                                edge_data.get("relation") == FOLLOWED_BY
                                and successor not in visited
                            ):
                                visited.add(successor)
                                next_frontier.append(successor)
                                fetched = _fetch_by_case_name(successor, "case_ratio")
                                if fetched and fetched.chunk_id not in existing_ids:
                                    augmented.append(fetched)
                                    existing_ids.add(fetched.chunk_id)
                    frontier = next_frontier
                    if not frontier:
                        break

    # Combine original + augmented
    all_chunks = list(chunks) + augmented

    # Trim to MAX_AUGMENTED, preferring case_ratio and statute layers
    if len(all_chunks) > MAX_AUGMENTED:
        priority_layers = {"case_ratio", "statute"}
        priority = [c for c in all_chunks if c.payload.get("legal_layer") in priority_layers]
        others = [c for c in all_chunks if c.payload.get("legal_layer") not in priority_layers]
        all_chunks = (priority + others)[:MAX_AUGMENTED]

    logger.info(
        f"Graph augmentation: {len(chunks)} → {len(all_chunks)} chunks "
        f"({len(augmented)} added)"
    )
    return all_chunks


def _fetch_by_case_name(case_name: str, preferred_layer: str) -> RetrievedChunk | None:
    """Find a chunk in Qdrant matching a case name, preferring a specific legal_layer."""
    client = get_qdrant_client()
    from qdrant_client.http import models as qmodels

    for layer in [preferred_layer, "case_facts", "case_analysis"]:
        try:
            results, _ = client.scroll(
                collection_name=settings.collection_cases,
                scroll_filter=qmodels.Filter(
                    must=[
                        qmodels.FieldCondition(key="case_name", match=qmodels.MatchValue(value=case_name)),
                        qmodels.FieldCondition(key="legal_layer", match=qmodels.MatchValue(value=layer)),
                    ]
                ),
                limit=1,
                with_payload=True,
                with_vectors=False,
            )
            if results:
                payload = results[0].payload or {}
                chunk_id = payload.get("chunk_id", str(results[0].id))
                return RetrievedChunk(
                    chunk_id=chunk_id,
                    text=payload.get("text", ""),
                    score=0.5,
                    payload=payload,
                    source_collections=["graph_augment"],
                )
        except Exception:
            continue
    return None


def _fetch_by_section_node(statute_node: str) -> RetrievedChunk | None:
    """Parse a statute node like 'BNS S.100' and fetch the corresponding chunk."""
    import re
    m = re.match(r'(\w+)\s+S\.(\w+)', statute_node)
    if not m:
        return None
    act, sec_num = m.group(1), m.group(2)

    client = get_qdrant_client()
    from qdrant_client.http import models as qmodels

    try:
        results, _ = client.scroll(
            collection_name=settings.collection_statutes,
            scroll_filter=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(key="act", match=qmodels.MatchValue(value=act)),
                    qmodels.FieldCondition(key="section_number", match=qmodels.MatchValue(value=sec_num)),
                    qmodels.FieldCondition(key="legal_layer", match=qmodels.MatchValue(value="statute")),
                ]
            ),
            limit=1,
            with_payload=True,
            with_vectors=False,
        )
        if results:
            payload = results[0].payload or {}
            chunk_id = payload.get("chunk_id", str(results[0].id))
            return RetrievedChunk(
                chunk_id=chunk_id,
                text=payload.get("text", ""),
                score=0.5,
                payload=payload,
                source_collections=["graph_augment"],
            )
    except Exception:
        pass
    return None
