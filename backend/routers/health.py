from fastapi import APIRouter
from backend.config import settings
from backend.services.qdrant_client import get_qdrant_client
from backend.services.ollama_client import check_ollama_health
from backend.services.graph_store import get_graph

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/")
async def health_check():
    # Qdrant status
    qdrant_ok = False
    col_names = []
    try:
        col_names = [
            c.name for c in get_qdrant_client().get_collections().collections
        ]
        qdrant_ok = (
            settings.collection_statutes in col_names
            and settings.collection_cases in col_names
        )
    except Exception:
        pass

    # Ollama status
    ollama = await check_ollama_health()

    # Graph status
    graph = get_graph()

    return {
        "status": "ok",
        "qdrant": {
            "connected": qdrant_ok,
            "collections": col_names,
            "expected_collections": [
                settings.collection_statutes,
                settings.collection_cases,
            ],
        },
        "ollama": ollama,
        "graph": {
            "nodes": graph.number_of_nodes(),
            "edges": graph.number_of_edges(),
            "note": "0 nodes and 0 edges is correct before first ingestion.",
        },
        "config": {
            "embed_model": settings.embed_model,
            "llm_model": settings.llm_model,
            "vector_size": settings.vector_size,
            "retrieval_k": settings.retrieval_k,
            "final_k": settings.final_k,
            "qdrant_host": settings.qdrant_host,
            "ollama_host": settings.ollama_host,
        },
    }
