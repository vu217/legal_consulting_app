"""
legal_chunker.py
Legal-context-aware chunker for Indian court documents.

Key improvements over v1:
- Detects numbered sections, Articles, Clauses, Rules, Regulations, Schedules
- Preserves [TABLE]...[/TABLE] blocks as atomic chunks (never split mid-table)
- Paragraph-aware splitting: splits on natural double-newline boundaries
- Overlap at paragraph granularity (not arbitrary characters)
- Minimum chunk size reduced to 30 chars to preserve short rulings/orders
- Extended statute regex covers 20+ major Indian acts
- Recognises AIR / SCC / SCR / Cr.LJ / SLT citation formats
- Covers full court hierarchy including NCLAT, NCDRC, ITAT, NGT, SAT, DRT
- Detects "r/w", "read with", "along with Section" cross-reference patterns
- New section_type="table" for tabular data
"""

import re
from dataclasses import dataclass, field
from typing import Optional

try:
    from langchain_core.documents import Document
except ImportError:
    from langchain_core.documents import Document


# ── Section header patterns ────────────────────────────────────────────────────
# Order matters: more specific patterns first

SECTION_PATTERNS = [
    # Document structure
    ("case_name",   re.compile(r"(?i)^(in\s+the\s+matter\s+of|between)[:\s]")),
    ("court",       re.compile(r"(?i)(high\s+court|supreme\s+court|district\s+court|sessions\s+court|tribunal|magistrate|nclat|ncdrc|itat|ngt|sat|drt|cat|arat)[^\n]*")),
    ("parties",     re.compile(r"(?i)^(parties|petitioner|respondent|appellant|plaintiff|defendant|complainant|accused)[:\s]")),

    # Case body sections
    ("facts",       re.compile(r"(?i)^(facts|background|brief\s+facts|statement\s+of\s+facts|factual\s+matrix|case\s+background)[:\s]")),
    ("evidence",    re.compile(r"(?i)^(evidence|exhibits|documents\s+relied|proof|witnesses|oral\s+evidence|documentary\s+evidence)[:\s]")),
    ("arguments",   re.compile(r"(?i)^(arguments|submissions|contention|pleadings|written\s+submissions|oral\s+arguments|counsel\s+submitted)[:\s]")),
    ("statutes",    re.compile(r"(?i)^(sections?\s+cited|laws?\s+cited|statutory\s+provisions|acts?\s+referred|ipc|crpc|cpc|applicable\s+law)[:\s]")),
    ("ruling",      re.compile(r"(?i)^(held|order|judgment|decree|ruling|decision|the\s+court\s+held|court\s+order)[:\s]")),
    ("ratio",       re.compile(r"(?i)^(ratio\s+decidendi|ratio|principle\s+laid\s+down|proposition\s+of\s+law)[:\s]")),
    ("outcome",     re.compile(r"(?i)^(result|disposed|acquitted|convicted|sentenced|dismissed|allowed|set\s+aside|quashed|remanded)[:\s]")),
    ("sentence",    re.compile(r"(?i)^(sentence|punishment|penalty|fine|imprisonment|award\s+of\s+compensation)[:\s]")),
    ("precedents",  re.compile(r"(?i)^(cases?\s+cited|precedents?|relied\s+upon|authorities|case\s+law\s+referred)[:\s]")),

    # Statutory document structure
    ("article",     re.compile(r"(?i)^(article\s+\d+|art\.\s*\d+)[.:\s—-]")),
    ("clause",      re.compile(r"(?i)^(clause\s+\d+|cl\.\s*\d+)[.:\s—-]")),
    ("rule",        re.compile(r"(?i)^(rule\s+\d+|order\s+[ivxlcdm]+\s+rule\s+\d+)[.:\s—-]")),
    ("regulation",  re.compile(r"(?i)^(regulation\s+\d+|reg\.\s*\d+)[.:\s—-]")),
    ("schedule",    re.compile(r"(?i)^(schedule\s+[ivxlcdm\d]+|annexure\s+[a-z\d]+|appendix\s+[a-z\d]+)[.:\s—-]")),
    ("section_num", re.compile(r"(?i)^(section\s+\d+[\w\s]*?(?:ipc|crpc|cpc|evidence\s+act|constitution|companies\s+act|it\s+act|ndps|pmla|ni\s+act|mv\s+act|pocso|ibc|rera|gst|income\s+tax)?)[.:\s—-]")),

    # Numbered para / order markers
    ("para",        re.compile(r"(?i)^(para(?:graph)?\s*\.?\s*\d+|p\.\s*\d+)[.:\s—-]")),
    ("numbered",    re.compile(r"^(\d+\.|[ivxlcdm]+\.|[a-z]\.)[\s]")),      # 1. / i. / a.
    ("lettered",    re.compile(r"^\([a-z0-9ivxlcdm]+\)\s")),                # (a) / (i) / (1)

    # Table marker from ingestion.py
    ("table",       re.compile(r"^\[TABLE\]")),
]


# ── Extraction regexes ─────────────────────────────────────────────────────────

COURT_RE = re.compile(
    r"(?i)("
    r"Supreme\s+Court(?:\s+of\s+India)?"
    r"|High\s+Court(?:\s+of\s+[\w\s]+)?"
    r"|District\s+Court"
    r"|Sessions\s+Court"
    r"|Magistrate(?:\s+Court)?"
    r"|(?:[\w\s]+)\s+Tribunal"
    r"|NCLAT|NCDRC|SAT|CAT|ITAT|NGT|DRT|DRAT|CESTAT|COMPAT|TDSAT"
    r"|Family\s+Court"
    r"|Motor\s+Accident\s+Claims\s+Tribunal"
    r"|Consumer\s+(?:Disputes\s+)?Redressal\s+(?:Commission|Forum)"
    r")"
)

YEAR_RE = re.compile(r"\b(19[5-9]\d|20[0-2]\d)\b")

STATUTE_RE = re.compile(
    r"(?i)("
    r"(?:Section|Sec\.|S\.)\s*\d+[\w\s,()]*?"
    r"(?:IPC|Indian\s+Penal\s+Code"
    r"|CrPC|Cr\.P\.C\.|Code\s+of\s+Criminal\s+Procedure"
    r"|CPC|C\.P\.C\.|Code\s+of\s+Civil\s+Procedure"
    r"|Evidence\s+Act"
    r"|Constitution(?:\s+of\s+India)?"
    r"|Companies\s+Act"
    r"|IT\s+Act|Information\s+Technology\s+Act"
    r"|NDPS\s+Act|Narcotic\s+Drugs"
    r"|PMLA|Prevention\s+of\s+Money\s+Laundering"
    r"|NI\s+Act|Negotiable\s+Instruments\s+Act"
    r"|MV\s+Act|Motor\s+Vehicles\s+Act"
    r"|POCSO|Protection\s+of\s+Children"
    r"|Domestic\s+Violence\s+Act|DV\s+Act"
    r"|Consumer\s+Protection\s+Act"
    r"|Arbitration(?:\s+and\s+Conciliation)?\s+Act"
    r"|RERA|Real\s+Estate(?:\s+\(Regulation\s+and\s+Development\))?\s+Act"
    r"|GST|Goods\s+and\s+Services\s+Tax"
    r"|Income[\s-]Tax\s+Act"
    r"|IBC|Insolvency\s+and\s+Bankruptcy\s+Code"
    r"|Limitation\s+Act"
    r"|Transfer\s+of\s+Property\s+Act"
    r"|Specific\s+Relief\s+Act"
    r"|Hindu(?:\s+Marriage|\s+Succession|\s+Adoption)?\s+Act"
    r"|Special\s+Marriage\s+Act"
    r"|Dowry\s+Prohibition\s+Act"
    r")[^\n,.;]{0,60}"
    r")"
)

# Recognises AIR / SCC / SCR / Cr.LJ / SLT / All LR citations
CASE_REF_RE = re.compile(
    r"("
    r"[A-Z][a-zA-Z\s\.]+\s+[Vv][Ss]?\.?\s+[A-Z][a-zA-Z\s\.]+"  # Name v. Name
    r"(?:\s*,\s*(?:\(\d{4}\)|\d{4}))?"                            # optional year
    r"(?:\s+\d+\s+(?:AIR|SCC|SCR|Cr\.?LJ|SLT|All\s*LR|BomLR|MLJ|KLT|CLT)\s+\d+)?"  # citation
    r"|(?:AIR|SCC|SCR)\s+\d{4}\s+\w+\s+\d+"                     # citation-first format
    r"|\(\d{4}\)\s+\d+\s+SCC\s+\d+"                              # (2020) 5 SCC 123
    r"|\d{4}\s+\(\d+\)\s+SCC\s+\d+"
    r")"
)

OUTCOME_RE = re.compile(
    r"(?i)\b(acquitted|convicted|sentenced|dismissed|allowed|upheld|set\s+aside|remanded|quashed|partly\s+allowed|disposed\s+of)\b"
)

# Cross-reference patterns: "r/w", "read with", "along with Section"
CROSS_REF_RE = re.compile(
    r"(?i)(r/?w\.?\s+(?:Section|Sec\.|S\.)\s*\d+|read\s+with\s+(?:Section|Sec\.)\s*\d+|along\s+with\s+(?:Section|Sec\.)\s*\d+)"
)

TABLE_BLOCK_RE = re.compile(r"\[TABLE\].*?\[/TABLE\]", re.DOTALL)


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class LegalChunk:
    source_file:   str
    chunk_index:   int
    section_type:  str
    text:          str
    case_name:     Optional[str] = None
    court:         Optional[str] = None
    year:          Optional[str] = None
    statutes:      list = field(default_factory=list)
    precedents:    list = field(default_factory=list)
    outcome:       Optional[str] = None
    parties:       Optional[str] = None
    cross_refs:    list = field(default_factory=list)

    def to_document(self) -> Document:
        return Document(
            page_content=self.text,
            metadata={
                "source":       self.source_file,
                "chunk_index":  self.chunk_index,
                "section_type": self.section_type,
                "case_name":    self.case_name   or "",
                "court":        self.court       or "",
                "year":         self.year        or "",
                "statutes":     "; ".join(self.statutes),
                "precedents":   "; ".join(self.precedents),
                "outcome":      self.outcome     or "",
                "parties":      self.parties     or "",
                "cross_refs":   "; ".join(self.cross_refs),
            }
        )


# ── Metadata extractors ───────────────────────────────────────────────────────

def _extract_court(text: str) -> Optional[str]:
    m = COURT_RE.search(text)
    return m.group(0).strip() if m else None

def _extract_year(text: str) -> Optional[str]:
    years = YEAR_RE.findall(text)
    return max(years) if years else None

def _extract_statutes(text: str) -> list:
    return list(dict.fromkeys(s.strip() for s in STATUTE_RE.findall(text)))[:12]

def _extract_precedents(text: str) -> list:
    return list(dict.fromkeys(c.strip() for c in CASE_REF_RE.findall(text)))[:12]

def _extract_outcome(text: str) -> Optional[str]:
    m = OUTCOME_RE.search(text)
    return m.group(0).lower() if m else None

def _extract_case_name(text: str) -> Optional[str]:
    m = CASE_REF_RE.search(text[:3000])
    return m.group(0).strip() if m else None

def _extract_parties(text: str) -> Optional[str]:
    for line in text[:3000].splitlines()[:30]:
        stripped = line.strip()
        if re.search(r"(?i)\bversus\b|\bv[s]?\.", stripped) and len(stripped) > 5:
            return stripped[:200]
    return None

def _extract_cross_refs(text: str) -> list:
    return list(dict.fromkeys(r.strip() for r in CROSS_REF_RE.findall(text)))[:8]


# ── Section splitter ──────────────────────────────────────────────────────────

def _split_into_sections(text: str) -> list[tuple[str, str]]:
    """
    Returns an ordered list of (section_key, text) tuples.
    Tables inside [TABLE]...[/TABLE] are treated as opaque blocks and never
    matched against section header patterns — they get their own "table" entry.
    """
    # First, extract and stash all table blocks with placeholders
    table_store: dict[str, str] = {}
    def _stash_table(m):
        key = f"\x00TABLE{len(table_store)}\x00"
        table_store[key] = m.group(0)
        return key

    protected = TABLE_BLOCK_RE.sub(_stash_table, text)

    sections: list[tuple[str, list[str]]] = [("preamble", [])]

    for line in protected.splitlines():
        # Check if the line is a table placeholder
        if line.strip() in table_store:
            # Flush any current section, then add table as its own section
            sections.append(("table", [table_store[line.strip()]]))
            sections.append(("preamble", []))  # resume with fresh preamble
            continue

        matched = False
        for key, pat in SECTION_PATTERNS:
            if pat.match(line.strip()):
                sections.append((key, [line]))
                matched = True
                break
        if not matched:
            sections[-1][1].append(line)

    # Restore any inline table placeholders that weren't on their own line
    result = []
    for key, lines in sections:
        body = "\n".join(lines).strip()
        for placeholder, original in table_store.items():
            body = body.replace(placeholder, original)
        if body:
            result.append((key, body))
    return result


# ── Paragraph-aware splitter ──────────────────────────────────────────────────

def _para_split(text: str, max_size: int = 1200) -> list[str]:
    """
    Split text into chunks at natural paragraph boundaries (double newlines).
    Tables enclosed in [TABLE]...[/TABLE] are never broken up.
    Overlap is achieved by carrying the last paragraph into the next chunk.
    """
    if len(text) <= max_size:
        return [text]

    # Protect table blocks
    table_store: dict[str, str] = {}
    def _stash(m):
        key = f"\x00T{len(table_store)}\x00"
        table_store[key] = m.group(0)
        return key

    protected = TABLE_BLOCK_RE.sub(_stash, text)

    # Split into paragraphs on blank lines
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", protected) if p.strip()]

    chunks: list[str] = []
    current_paras: list[str] = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para)

        # Single paragraph larger than max — must go as its own chunk
        if para_len > max_size:
            if current_paras:
                chunks.append("\n\n".join(current_paras))
                # carry last paragraph as overlap seed for next chunk
                current_paras = [current_paras[-1]]
                current_len   = len(current_paras[0])
            chunks.append(para)
            current_paras = [para]
            current_len   = para_len
            continue

        if current_len + para_len + 2 > max_size and current_paras:
            chunks.append("\n\n".join(current_paras))
            # Overlap: carry last paragraph into next chunk
            current_paras = [current_paras[-1], para]
            current_len   = len(current_paras[0]) + para_len + 2
        else:
            current_paras.append(para)
            current_len += para_len + 2

    if current_paras:
        chunks.append("\n\n".join(current_paras))

    # Restore table placeholders
    restored = []
    for chunk in chunks:
        for placeholder, original in table_store.items():
            chunk = chunk.replace(placeholder, original)
        restored.append(chunk)

    return restored


# ── Chunk factory ─────────────────────────────────────────────────────────────

def _make_chunk(source: str, idx: int, section: str, text: str, full_text: str) -> LegalChunk:
    return LegalChunk(
        source_file  = source,
        chunk_index  = idx,
        section_type = section,
        text         = text,
        case_name    = _extract_case_name(full_text),
        court        = _extract_court(full_text),
        year         = _extract_year(full_text),
        statutes     = _extract_statutes(text),
        precedents   = _extract_precedents(text),
        outcome      = _extract_outcome(full_text),
        parties      = _extract_parties(full_text),
        cross_refs   = _extract_cross_refs(text),
    )


# ── Public entry point ────────────────────────────────────────────────────────

def chunk_legal_document(file_path: str, raw_text: str) -> list:
    """
    Main entry point.
    Returns list[Document] — one summary chunk + one per section sub-chunk.
    """
    docs = []
    sections = _split_into_sections(raw_text)

    # Full-case summary chunk (first 3000 chars) for holistic retrieval
    docs.append(_make_chunk(file_path, 0, "full_case", raw_text[:3000], raw_text).to_document())

    idx = 1
    for section_key, section_text in sections:
        # Minimum size reduced to 30 to preserve short orders/rulings
        if len(section_text) < 30:
            continue

        # Table blocks: always one chunk, never split
        if section_key == "table" or TABLE_BLOCK_RE.search(section_text):
            docs.append(_make_chunk(file_path, idx, "table", section_text, raw_text).to_document())
            idx += 1
            continue

        # Large sections: paragraph-aware split
        sub_texts = _para_split(section_text) if len(section_text) > 1200 else [section_text]
        for sub in sub_texts:
            if len(sub) < 30:
                continue
            docs.append(_make_chunk(file_path, idx, section_key, sub, raw_text).to_document())
            idx += 1

    return docs
