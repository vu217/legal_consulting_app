from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    # Models
    embed_model: str = "nomic-embed-text"
    llm_model: str = "qwen2.5:3b"
    fast_llm_model: str = "qwen2.5:3b"

    # Ollama
    ollama_host: str = "http://127.0.0.1:11434"

    # Qdrant
    qdrant_host: str = "http://localhost:6333"
    collection_statutes: str = "legal_statutes"
    collection_cases: str = "legal_cases"
    vector_size: int = 768

    # Retrieval
    retrieval_k: int = 20
    final_k: int = 12

    # Paths
    pdf_dir: Path = Path("backend/pdfs")
    case_upload_dir: Path = Path("backend/case_uploads")
    graph_path: Path = Path("backend/data/legal_graph.json")
    crpc_bnss_map_path: Path = Path("backend/data/crpc_bnss_map.json")

    # Server
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
