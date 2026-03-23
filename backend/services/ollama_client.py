import httpx
import logging
from backend.config import settings

logger = logging.getLogger(__name__)


async def check_ollama_health() -> dict:
    """
    Confirms Ollama is reachable and both required models are listed.
    Does NOT load any model into VRAM. Models load on first inference request.
    """
    result = {
        "reachable": False,
        "embed_model_available": False,
        "llm_model_available": False,
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{settings.ollama_host}/api/tags")

        if response.status_code != 200:
            logger.error(f"Ollama /api/tags returned HTTP {response.status_code}")
            return result

        result["reachable"] = True
        available = [m["name"] for m in response.json().get("models", [])]

        if any(settings.embed_model in m for m in available):
            result["embed_model_available"] = True
            logger.info(f"Embed model '{settings.embed_model}' found.")
        else:
            logger.warning(
                f"Embed model '{settings.embed_model}' not found in Ollama. "
                f"Pull it before ingestion: ollama pull {settings.embed_model}"
            )

        if any(settings.llm_model in m for m in available):
            result["llm_model_available"] = True
            logger.info(f"LLM model '{settings.llm_model}' found.")
        else:
            logger.warning(
                f"LLM model '{settings.llm_model}' not found in Ollama. "
                f"Pull it before querying: ollama pull {settings.llm_model}"
            )

    except httpx.ConnectError:
        logger.error(
            f"Ollama unreachable at {settings.ollama_host}. "
            f"Is the Ollama service running?"
        )

    return result


async def embed_text(text: str) -> list[float]:
    """
    Embed one string using nomic-embed-text via Ollama.
    Returns 768 floats. Used in Phase 2 ingestion.
    Stub is complete and functional — Phase 2 calls this directly.
    """
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            f"{settings.ollama_host}/api/embeddings",
            json={"model": settings.embed_model, "prompt": text},
        )
        response.raise_for_status()
        return response.json()["embedding"]


async def generate(prompt: str, system: str = "") -> str:
    """
    Single non-streaming LLM call.
    Temperature 0.1, max 1500 tokens.
    Full structured prompting logic added in Phase 4.
    """
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            f"{settings.ollama_host}/api/chat",
            json={
                "model": settings.llm_model,
                "messages": messages,
                "options": {
                    "temperature": 0.1,
                    "num_predict": 1500,
                },
                "stream": False,
            },
        )
        response.raise_for_status()
        return response.json()["message"]["content"]
