from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Chunk:
    """
    The atomic unit produced by every chunker.
    Every field must be populated — no None values except where Optional is explicit.
    Qdrant payload is built directly from this object's fields.
    """
    # Content
    text: str                          # The actual text that gets embedded
    chunk_id: str                      # Unique ID: "{source_stem}_{type}_{index}"

    # Source
    source: str                        # Original PDF filename
    legal_layer: str                   # statute | case_ratio | case_facts | case_analysis | doctrine | syllabus | comparison

    # Statute-specific (leave as "" if not applicable)
    section_number: str = ""
    section_title: str = ""
    chapter: str = ""
    act: str = ""                      # BNS | IPC | BNSS | CrPC | other
    year: str = ""
    cross_refs: list = field(default_factory=list)   # ["Section 101", "Section 4"]

    # Case-specific (leave as "" if not applicable)
    case_name: str = ""
    citation: str = ""                 # AIR/SCC citation string
    court: str = ""                    # SC | HC | tribunal
    unit: str = ""
    unit_topic: str = ""
    bns_sections: list = field(default_factory=list)
    principles: list = field(default_factory=list)   # mens rea | transferred intention | etc.
    outcome: str = ""                  # convicted | acquitted | dismissed | allowed

    # Comparison-specific
    bnss_section: str = ""
    crpc_section: str = ""
    subject: str = ""
    is_boilerplate: bool = False       # True for "No change" rows

    # Judgment-specific
    petitioner: str = ""
    respondent: str = ""
    relief_sought: str = ""
    statutes: list = field(default_factory=list)     # ["BNS Section 100", "Article 21"]

    def to_qdrant_payload(self) -> dict:
        """Serialise to dict for Qdrant payload storage."""
        return {k: v for k, v in self.__dict__.items() if k != "text"}
