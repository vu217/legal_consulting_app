import re
import logging
import networkx as nx
from backend.services.ingestion import Chunk

logger = logging.getLogger(__name__)

# Edge type constants
INTERPRETED_BY = "INTERPRETED_BY"
FOLLOWED_BY = "FOLLOWED_BY"
EXCEPTION_TO = "EXCEPTION_TO"
APPLIES_DOCTRINE = "APPLIES_DOCTRINE"
REPLACED_BY = "REPLACED_BY"
PUNISHMENT_UNDER = "PUNISHMENT_UNDER"

# Patterns for edge extraction from text
_FOLLOWING_RE = re.compile(
    r'\b(?:following|relied upon|approved in|affirmed in)\s+([A-Z][a-zA-Z\s]+(?:v\.|vs\.)\s+[A-Z][a-zA-Z\s]+)',
    re.IGNORECASE
)
_DISTINGUISHED_RE = re.compile(
    r'\b(?:distinguished in|overruled in|not followed in)\s+([A-Z][a-zA-Z\s]+(?:v\.|vs\.)\s+[A-Z][a-zA-Z\s]+)',
    re.IGNORECASE
)
_SUBJECT_TO_RE = re.compile(r'\bsubject to\s+(?:section|sec\.|s\.)\s+(\d{1,3}[A-Z]?)', re.IGNORECASE)
_AS_DEFINED_RE = re.compile(r'\bas defined in\s+(?:section|sec\.|s\.)\s+(\d{1,3}[A-Z]?)', re.IGNORECASE)
_EXCEPTION_RE = re.compile(r'\bException\s+\d+\b|\bProviso\b', re.IGNORECASE)
_PUNISHMENT_RE = re.compile(
    r'(?:punishment|penalty)\s+(?:for|under)\s+(?:section|sec\.|s\.)\s+(\d{1,3}[A-Z]?)',
    re.IGNORECASE
)
_DOCTRINE_RE = re.compile(
    r'\b(mens rea|actus reus|transferred intention|strict liability|vicarious liability|'
    r'common intention|grave and sudden provocation|self.?defence|private defence|insanity)\b',
    re.IGNORECASE
)


def build_graph_from_chunks(
    chunks: list[Chunk],
    existing_graph: nx.DiGraph | None = None,
    crpc_to_bnss: dict[str, str] | None = None,
) -> nx.DiGraph:
    """
    Build or update a NetworkX DiGraph from a list of chunks.
    If existing_graph is provided, add edges to it (incremental build).
    crpc_to_bnss is used to add REPLACED_BY edges from comparison table data.

    Node naming convention:
      - Statute nodes: "{act} S.{section_number}"   e.g. "BNS S.100"
      - Case nodes:    "{case_name}"                 e.g. "Virsa Singh v. Punjab"
      - Doctrine nodes: "{doctrine}"                 e.g. "mens rea"
    """
    G: nx.DiGraph = existing_graph if existing_graph is not None else nx.DiGraph()

    for chunk in chunks:
        _process_chunk(G, chunk)

    # Add REPLACED_BY edges from the CrPC→BNS lookup
    if crpc_to_bnss:
        for crpc_sec, bnss_sec in crpc_to_bnss.items():
            crpc_node = f"CrPC S.{crpc_sec}"
            bnss_node = f"BNS S.{bnss_sec}"
            if not G.has_edge(crpc_node, bnss_node):
                G.add_edge(crpc_node, bnss_node, relation=REPLACED_BY)

    edge_count = G.number_of_edges()
    node_count = G.number_of_nodes()
    logger.info(f"Graph updated — nodes: {node_count}, edges: {edge_count}")
    return G


def _process_chunk(G: nx.DiGraph, chunk: Chunk) -> None:
    if chunk.legal_layer == "statute":
        _process_statute_chunk(G, chunk)
    elif chunk.legal_layer in ("case_ratio", "case_facts", "case_analysis"):
        _process_case_chunk(G, chunk)
    elif chunk.legal_layer == "comparison":
        pass  # Handled via crpc_to_bnss dict


def _process_statute_chunk(G: nx.DiGraph, chunk: Chunk) -> None:
    if not chunk.section_number or chunk.section_number == "intro":
        return

    act = chunk.act or "unknown"
    section_node = f"{act} S.{chunk.section_number}"
    G.add_node(section_node, act=act, section=chunk.section_number, layer="statute")

    # EXCEPTION_TO: if text contains "Exception" or "Proviso", link to parent section
    if _EXCEPTION_RE.search(chunk.text) and chunk.section_number:
        try:
            parent_num = int(re.sub(r'[A-Z]', '', chunk.section_number)) - 1
            if parent_num > 0:
                parent_node = f"{act} S.{parent_num}"
                if not G.has_edge(section_node, parent_node):
                    G.add_edge(section_node, parent_node, relation=EXCEPTION_TO)
        except (ValueError, TypeError):
            pass

    # Cross-reference edges (INTERPRETED_BY placeholders — cases link back in _process_case_chunk)
    for ref in chunk.cross_refs or []:
        ref_num = re.search(r'\d+', ref)
        if ref_num:
            ref_node = f"{act} S.{ref_num.group()}"
            G.add_node(ref_node, act=act, layer="statute")

    # PUNISHMENT_UNDER edges
    for m in _PUNISHMENT_RE.finditer(chunk.text):
        penalty_sec = m.group(1)
        penalty_node = f"{act} S.{penalty_sec}"
        if not G.has_edge(section_node, penalty_node):
            G.add_edge(section_node, penalty_node, relation=PUNISHMENT_UNDER)


def _process_case_chunk(G: nx.DiGraph, chunk: Chunk) -> None:
    if not chunk.case_name:
        return

    case_node = chunk.case_name
    G.add_node(case_node, citation=chunk.citation, court=chunk.court, layer="case")

    # INTERPRETED_BY: case interprets BNS/IPC sections
    for sec in chunk.bns_sections or []:
        sec_num = re.search(r'\d+', sec)
        if sec_num:
            act = "BNS"  # default
            statute_node = f"{act} S.{sec_num.group()}"
            G.add_node(statute_node, act=act, layer="statute")
            if not G.has_edge(statute_node, case_node):
                G.add_edge(statute_node, case_node, relation=INTERPRETED_BY)

    # FOLLOWED_BY: case follows another case
    for m in _FOLLOWING_RE.finditer(chunk.text):
        followed_case = m.group(1).strip()
        if followed_case != case_node:
            G.add_node(followed_case, layer="case")
            if not G.has_edge(followed_case, case_node):
                G.add_edge(followed_case, case_node, relation=FOLLOWED_BY)

    # APPLIES_DOCTRINE
    for m in _DOCTRINE_RE.finditer(chunk.text):
        doctrine = m.group(1).lower()
        doctrine_node = doctrine
        G.add_node(doctrine_node, layer="doctrine")
        if not G.has_edge(case_node, doctrine_node):
            G.add_edge(case_node, doctrine_node, relation=APPLIES_DOCTRINE)
