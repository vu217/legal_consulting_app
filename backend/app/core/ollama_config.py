"""Ollama client options from environment (CPU fallback when CUDA fails)."""

import os


def get_ollama_num_gpu() -> int | None:
    if os.getenv("OLLAMA_USE_CPU", "").strip().lower() in ("1", "true", "yes", "on"):
        return 0
    raw = os.getenv("OLLAMA_NUM_GPU")
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return int(raw)
    except ValueError:
        return None
