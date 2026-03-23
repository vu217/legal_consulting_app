import logging
from qdrant_client import QdrantClient as _QdrantClient
from backend.config import settings

logger = logging.getLogger(__name__)

_client: _QdrantClient | None = None


def get_qdrant_client() -> _QdrantClient:
    global _client
    if _client is None:
        raise RuntimeError(
            "Qdrant client not initialised. init_qdrant() must be called at startup."
        )
    return _client


async def init_qdrant() -> None:
    global _client
    try:
        _client = _QdrantClient(url=settings.qdrant_host, timeout=30)
        collections = _client.get_collections().collections
        names = [c.name for c in collections]
        logger.info(f"Qdrant connected. Collections present: {names}")

        for required in [settings.collection_statutes, settings.collection_cases]:
            if required not in names:
                logger.warning(
                    f"Collection '{required}' is missing from Qdrant. "
                    f"Run setup_collections.py to create it."
                )
    except Exception as e:
        logger.error(f"Could not connect to Qdrant at {settings.qdrant_host}: {e}")
        raise
