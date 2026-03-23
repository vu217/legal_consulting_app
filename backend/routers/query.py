from fastapi import APIRouter

router = APIRouter(prefix="/query", tags=["query"])


@router.post("/")
async def run_query(body: dict):
    """
    Placeholder. Full SSE streaming query pipeline implemented in Phase 4.
    """
    return {
        "status": "not_implemented",
        "message": "Query pipeline is implemented in Phase 4.",
        "received": body.get("query", ""),
    }
