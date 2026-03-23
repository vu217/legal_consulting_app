import logging
from rank_bm25 import BM25Okapi
from backend.config import settings
from backend.services.qdrant_client import get_qdrant_client

logger = logging.getLogger(__name__)

# In-memory state
_bm25: BM25Okapi | None = None
_corpus_texts: list[str] = []
_corpus_ids: list[str] = []          # chunk_ids in same order as _corpus_texts
_corpus_payloads: list[dict] = []    # full payloads in same order


def get_bm25() -> BM25Okapi | None:
    return _bm25


def get_corpus() -> tuple[list[str], list[str], list[dict]]:
    return _corpus_texts, _corpus_ids, _corpus_payloads


def build_bm25_index() -> None:
    """
    Fetch all stored chunk texts from both Qdrant collections.
    Build a BM25Okapi index over them.
    Called at FastAPI startup and after every ingest run.
    """
    global _bm25, _corpus_texts, _corpus_ids, _corpus_payloads

    client = get_qdrant_client()
    texts = []
    ids = []
    payloads = []

    for collection_name in [settings.collection_statutes, settings.collection_cases]:
        try:
            # Scroll through all points in the collection
            offset = None
            while True:
                result, next_offset = client.scroll(
                    collection_name=collection_name,
                    limit=500,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                for point in result:
                    payload = point.payload or {}
                    text = payload.get("text", "")
                    chunk_id = payload.get("chunk_id", str(point.id))
                    if text:
                        texts.append(text)
                        ids.append(chunk_id)
                        payloads.append(payload)

                if next_offset is None:
                    break
                offset = next_offset

        except Exception as e:
            logger.warning(f"Could not scroll '{collection_name}' for BM25 build: {e}")

    if not texts:
        logger.warning("BM25 index is empty — no chunks found in Qdrant. Expected before first ingest.")
        _bm25 = None
        _corpus_texts = []
        _corpus_ids = []
        _corpus_payloads = []
        return

    # Tokenise: lowercase, split on whitespace
    tokenised = [text.lower().split() for text in texts]
    _bm25 = BM25Okapi(tokenised)
    _corpus_texts = texts
    _corpus_ids = ids
    _corpus_payloads = payloads

    logger.info(f"BM25 index built over {len(texts)} chunks from both collections.")
