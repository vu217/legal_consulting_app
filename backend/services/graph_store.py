import json
import logging
from pathlib import Path

import networkx as nx

from backend.config import settings

logger = logging.getLogger(__name__)

_graph: nx.DiGraph | None = None


def get_graph() -> nx.DiGraph:
    global _graph
    if _graph is None:
        raise RuntimeError(
            "Graph not initialised. init_graph() must be called at startup."
        )
    return _graph


def init_graph() -> None:
    """
    Load graph from disk if it exists. If not, start with an empty DiGraph.
    A missing file is expected on first run and must never crash the app.
    """
    global _graph
    path: Path = settings.graph_path

    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            _graph = nx.node_link_graph(data, directed=True, multigraph=False)
            logger.info(
                f"Graph loaded — nodes: {_graph.number_of_nodes()}, "
                f"edges: {_graph.number_of_edges()}"
            )
        except Exception as e:
            logger.error(f"Graph load failed ({e}). Starting with empty graph.")
            _graph = nx.DiGraph()
    else:
        logger.warning(
            f"No graph file at {path}. "
            f"Empty graph initialised. Expected before first ingest."
        )
        _graph = nx.DiGraph()


def save_graph() -> None:
    """
    Write the in-memory graph to disk as JSON.
    Called by the ingestion pipeline at the end of every ingest run.
    """
    path: Path = settings.graph_path
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(nx.node_link_data(get_graph()), f, indent=2, ensure_ascii=False)

    logger.info(f"Graph saved to {path}")
