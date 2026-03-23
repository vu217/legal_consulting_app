"""
legal_chunker.py
Legal-context-aware chunker for Indian court documents.

Detects numbered sections, Articles, Clauses, Rules, Regulations, Schedules.
Preserves [TABLE]...[/TABLE] blocks as atomic chunks (never split mid-table).
Paragraph-aware splitting with overlap at paragraph granularity.
Extracts case_type (criminal/civil/etc) and court_type as first-class metadata.
"""

import re
from dataclasses import dataclass, field
from typing import Optional

from langchain_core.documents import Document


# ── Section header patterns ────────────────────────────────────────────────────

SECTION_PATTERNS = [
    ("case_name",   re.compile(r"(?i)^(in\s+the\s+matter\s+of|between)[:\s]")),
    ("court",       re.compile(r"(?i)(high\s+court|supreme\s+court|district\s+court|sessions\s+court|tribunal|magistrate|nclat|ncdrc|itat|ngt|sat|drt|cat|arat)[^\n]*")),
    ("parties",     re.compile(r"(?i)^(parties|petitioner|respondent|appellant|plaintiff|defendant|complainant|accused)[:\s]")),
    ("facts",       re.compile(r"(?i)^(facts|background|brief\s+facts|statement\s+of\s+facts|factual\s+matrix|case\s+background)[:\s]")),
    ("evidence",    re.compile(r"(?i)^(evidence|exhibits|documents\s+relied|proof|witnesses|oral\s+evidence|documentary\s+evidence)[:\s]")),
    ("arguments",   re.compile(r"(?i)^(arguments|submissions|contention|pleadings|written\s+submissions|oral\s+arguments|counsel\s+submitted)[:\s]")),
    ("statutes",    re.compile(r"(?i)^(sections?\s+cited|laws?\s+cited|statutory\s+provisions|acts?\s+referred|ipc|crpc|cpc|applicable\s+law)[:\s]")),
    ("ruling",      re.compile(r"(?i)^(held|order|judgment|decree|ruling|decision|the\s+court\s+held|court\s+order)[:\s]")),
    ("ratio",       re.compile(r"(?i)^(ratio\s+decidendi|ratio|principle\s+laid\s+down|proposition\s+of\s+law)[:\s]")),
    ("outcome",     re.compile(r"(?i)^(result|disposed|acquitted|convicted|sentenced|dismissed|allowed|set\s+aside|quashed|remanded)[:\s]")),
    ("sentence",    re.compile(r"(?i)^(sentence|punishment|penalty|fine|imprisonment|award\s+of\s+compensation)[:\s]")),
    ("precedents",  re.compile(r"(?i)^(cases?\s+cited|precedents?|relied\s+upon|authorities|case\s+law\s+referred)[:\s]")),
    ("article",     re.compile(r"(?i)^(article\s+\d+|art\.\s*\d+)[.:\s—-]")),
    ("clause",      re.compile(r"(?i)^(clause\s+\d+|cl\.\s*\d+)[.:\s—-]")),
    ("rule",        re.compile(r"(?i)^(rule\s+\d+|order\s+[ivxlcdm]+\s+rule\s+\d+)[.:\s—-]")),
    ("regulation",  re.compile(r"(?i)^(regulation\s+\d+|reg\.\s*\d+)[.:\s—-]")),
    ("schedule",    re.compile(r"(?i)^(schedule\s+[ivxlcdm\d]+|annexure\s+[a-z\d]+|appendix\s+[a-z\d]+)[.:\s—-]")),
    ("section_num", re.compile(r"(?i)^(section\s+\d+[\w\s]*?(?:ipc|crpc|cpc|evidence\s+act|constitution|companies\s+act|it\s+act|ndps|pmla|ni\s+act|mv\s+act|pocso|ibc|rera|gst|income\s+tax)?)[.:\s—-]")),
    ("para",        re.compile(r"(?i)^(para(?:graph)?\s*\.?\s*\d+|p\.\s*\d+)[.:\s—-]")),
    ("numbered",    re.compile(r"^(\d+\.|[ivxlcdm]+\.|[a-z]\.)[\s]")),
    ("lettered",    re.compile(r"^\([a-z0-9ivxlcdm]+\)\s")),
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

CASE_REF_RE = re.compile(
    r"("
    r"[A-Z][a-zA-Z\s\.]+\s+[Vv][Ss]?\.?\s+[A-Z][a-zA-Z\s\.]+"
    r"(?:\s*,\s*(?:\(\d{4}\)|\d{4}))?"
    r"(?:\s+\d+\s+(?:AIR|SCC|SCR|Cr\.?LJ|SLT|All\s*LR|BomLR|MLJ|KLT|CLT)\s+\d+)?"
    r"|(?:AIR|SCC|SCR)\s+\d{4}\s+\w+\s+\d+"
    r"|\(\d{4}\)\s+\d+\s+SCC\s+\d+"
    r"|\d{4}\s+\(\d+\)\s+SCC\s+\d+"
    r")"
)

OUTCOME_RE = re.compile(
    r"(?i)\b(acquitted|convicted|sentenced|dismissed|allowed|upheld|set\s+aside|remanded|quashed|partly\s+allowed|disposed\s+of)\b"
)

CROSS_REF_RE = re.compile(
    r"(?i)(r/?w\.?\s+(?:Section|Sec\.|S\.)\s*\d+|read\s+with\s+(?:Section|Sec\.)\s*\d+|along\s+with\s+(?:Section|Sec\.)\s*\d+)"
)

TABLE_BLOCK_RE = re.compile(r"\[TABLE\].*?\[/TABLE\]", re.DOTALL)


# ── Case-type and court-type detection ────────────────────────────────────────

_CRIMINAL_KEYWORDS = re.compile(
    r"(?i)\b(IPC|Indian\s+Penal\s+Code|CrPC|Cr\.P\.C|FIR|chargesheet|bail|"
    r"accused|prosecution|complainant|cognizable|bailable|non-bailable|"
    r"NDPS|PMLA|POCSO|murder|theft|robbery|cheating|forgery|assault|"
    r"criminal\s+appeal|criminal\s+revision|sessions\s+trial|"
    r"Section\s+(?:3[02][0-9]|4[0-9]{2}|120B|34|149|302|304|306|307|354|376|379|406|420|468|471|498A|506)\s*(?:IPC)?)\b"
)

_CIVIL_KEYWORDS = re.compile(
    r"(?i)\b(CPC|C\.P\.C|civil\s+suit|plaintiff|defendant|decree|injunction|"
    r"specific\s+performance|partition|declaration|possession|mesne\s+profits|"
    r"Transfer\s+of\s+Property|Specific\s+Relief|Limitation\s+Act|"
    r"civil\s+appeal|civil\s+revision|Order\s+\d+\s+Rule)\b"
)

_CONSTITUTIONAL_KEYWORDS = re.compile(
    r"(?i)\b(Article\s+\d+|writ\s+petition|habeas\s+corpus|mandamus|certiorari|"
    r"prohibition|quo\s+warranto|fundamental\s+rights?|PIL|public\s+interest\s+litigation|"
    r"Constitution\s+of\s+India|constitutional\s+bench)\b"
)

_FAMILY_KEYWORDS = re.compile(
    r"(?i)\b(divorce|custody|maintenance|alimony|matrimonial|"
    r"Hindu\s+Marriage\s+Act|Special\s+Marriage|guardianship|"
    r"Domestic\s+Violence|DV\s+Act|family\s+court|restitution\s+of\s+conjugal)\b"
)

_COMMERCIAL_KEYWORDS = re.compile(
    r"(?i)\b(Companies\s+Act|IBC|insolvency|NCLT|NCLAT|arbitration|"
    r"commercial\s+court|commercial\s+dispute|winding\s+up|CIRP|"
    r"resolution\s+professional|RERA|real\s+estate)\b"
)

_TAX_KEYWORDS = re.compile(
    r"(?i)\b(Income[\s-]Tax|GST|ITAT|CESTAT|customs|excise|"
    r"assessment\s+year|tax\s+tribunal|revenue|assessee)\b"
)

_COURT_NORM_MAP = {
    "supreme_court": re.compile(r"(?i)supreme\s+court"),
    "high_court": re.compile(r"(?i)high\s+court"),
    "district_court": re.compile(r"(?i)district\s+court"),
    "sessions_court": re.compile(r"(?i)sessions\s+court"),
    "tribunal": re.compile(r"(?i)(tribunal|NCLAT|NCDRC|SAT|CAT|ITAT|NGT|DRT|DRAT|CESTAT|COMPAT|TDSAT|NCLT)"),
    "consumer_forum": re.compile(r"(?i)consumer\s+(?:disputes?\s+)?(?:redressal|forum|commission)"),
    "family_court": re.compile(r"(?i)family\s+court"),
}


def detect_case_type(text: str) -> str:
    """Heuristic: count keyword matches to classify case type."""
    sample = text[:8000]
    scores = {
        "criminal": len(_CRIMINAL_KEYWORDS.findall(sample)),
        "civil": len(_CIVIL_KEYWORDS.findall(sample)),
        "constitutional": len(_CONSTITUTIONAL_KEYWORDS.findall(sample)),
        "family": len(_FAMILY_KEYWORDS.findall(sample)),
        "commercial": len(_COMMERCIAL_KEYWORDS.findall(sample)),
        "tax": len(_TAX_KEYWORDS.findall(sample)),
    }
    best = max(scores, key=scores.get)  # type: ignore[arg-type]
    return best if scores[best] >= 2 else "other"


def normalize_court_type(court_text: str | None) -> str:
    """Map raw court string to a normalized category."""
    if not court_text:
        return "other"
    for norm_key, pattern in _COURT_NORM_MAP.items():
        if pattern.search(court_text):
            return norm_key
    return "other"


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class LegalChunk:
    source_file:   str
    chunk_index:   int
    section_type:  str
    text:          str
    case_name:     Optional[str] = None
    court:         Optional[str] = None
    court_type:    str = "other"
    year:          Optional[str] = None
    case_type:     str = "other"
    statutes:      list = field(default_factory=list)
    precedents:    list = field(default_factory=list)
    outcome:       Optional[str] = None
    outcome_detail: Optional[str] = None
    parties:       Optional[str] = None
    cross_refs:    list = field(default_factory=list)

    def to_document(self) -> Document:
        return Document(
            page_content=self.text,
            metadata={
                "source":         self.source_file,
                "chunk_index":    self.chunk_index,
                "section_type":   self.section_type,
                "case_name":      self.case_name or "",
                "court":          self.court or "",
                "court_type":     self.court_type,
                "year":           self.year or "",
                "case_type":      self.case_type,
                "statutes":       "; ".join(self.statutes),
                "precedents":     "; ".join(self.precedents),
                "outcome":        self.outcome or "",
                "outcome_detail": self.outcome_detail or "",
                "parties":        self.parties or "",
                "cross_refs":     "; ".join(self.cross_refs),
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

def _extract_outcome_detail(text: str) -> Optional[str]:
    """Capture a longer outcome phrase with surrounding context."""
    m = re.search(
        r"(?i)((?:appeal|petition|suit|case|writ)\s+(?:is\s+)?(?:hereby\s+)?"
        r"(?:acquitted|convicted|sentenced|dismissed|allowed|upheld|set\s+aside|"
        r"remanded|quashed|partly\s+allowed|disposed\s+of)"
        r"[^.]{0,80}\.)",
        text[-3000:],
    )
    return m.group(0).strip()[:200] if m else None

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
    table_store: dict[str, str] = {}
    def _stash_table(m):
        key = f"\x00TABLE{len(table_store)}\x00"
        table_store[key] = m.group(0)
        return key

    protected = TABLE_BLOCK_RE.sub(_stash_table, text)

    sections: list[tuple[str, list[str]]] = [("preamble", [])]

    for line in protected.splitlines():
        if line.strip() in table_store:
            sections.append(("table", [table_store[line.strip()]]))
            sections.append(("preamble", []))
            continue

        matched = False
        for key, pat in SECTION_PATTERNS:
            if pat.match(line.strip()):
                sections.append((key, [line]))
                matched = True
                break
        if not matched:
            sections[-1][1].append(line)

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
    if len(text) <= max_size:
        return [text]

    table_store: dict[str, str] = {}
    def _stash(m):
        key = f"\x00T{len(table_store)}\x00"
        table_store[key] = m.group(0)
        return key

    protected = TABLE_BLOCK_RE.sub(_stash, text)
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", protected) if p.strip()]

    chunks: list[str] = []
    current_paras: list[str] = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para)

        if para_len > max_size:
            if current_paras:
                chunks.append("\n\n".join(current_paras))
                current_paras = [current_paras[-1]]
                current_len = len(current_paras[0])
            chunks.append(para)
            current_paras = [para]
            current_len = para_len
            continue

        if current_len + para_len + 2 > max_size and current_paras:
            chunks.append("\n\n".join(current_paras))
            current_paras = [current_paras[-1], para]
            current_len = len(current_paras[0]) + para_len + 2
        else:
            current_paras.append(para)
            current_len += para_len + 2

    if current_paras:
        chunks.append("\n\n".join(current_paras))

    restored = []
    for chunk in chunks:
        for placeholder, original in table_store.items():
            chunk = chunk.replace(placeholder, original)
        restored.append(chunk)

    return restored


# ── Chunk factory ─────────────────────────────────────────────────────────────

def _make_chunk(source: str, idx: int, section: str, text: str, full_text: str,
                case_type: str = "other", court_type: str = "other") -> LegalChunk:
    court_raw = _extract_court(full_text)
    return LegalChunk(
        source_file    = source,
        chunk_index    = idx,
        section_type   = section,
        text           = text,
        case_name      = _extract_case_name(full_text),
        court          = court_raw,
        court_type     = court_type or normalize_court_type(court_raw),
        year           = _extract_year(full_text),
        case_type      = case_type,
        statutes       = _extract_statutes(text),
        precedents     = _extract_precedents(text),
        outcome        = _extract_outcome(full_text),
        outcome_detail = _extract_outcome_detail(full_text),
        parties        = _extract_parties(full_text),
        cross_refs     = _extract_cross_refs(text),
    )


# ── Public entry point ────────────────────────────────────────────────────────

def chunk_legal_document(file_path: str, raw_text: str) -> list:
    """
    Returns list[Document] — one summary chunk + one per section sub-chunk.
    Auto-detects case_type and court_type from document content.
    """
    docs = []
    sections = _split_into_sections(raw_text)

    case_type = detect_case_type(raw_text)
    court_raw = _extract_court(raw_text)
    court_type = normalize_court_type(court_raw)

    docs.append(
        _make_chunk(file_path, 0, "full_case", raw_text[:3000], raw_text,
                    case_type=case_type, court_type=court_type).to_document()
    )

    idx = 1
    for section_key, section_text in sections:
        if len(section_text) < 30:
            continue

        if section_key == "table" or TABLE_BLOCK_RE.search(section_text):
            docs.append(
                _make_chunk(file_path, idx, "table", section_text, raw_text,
                            case_type=case_type, court_type=court_type).to_document()
            )
            idx += 1
            continue

        sub_texts = _para_split(section_text) if len(section_text) > 1200 else [section_text]
        for sub in sub_texts:
            if len(sub) < 30:
                continue
            docs.append(
                _make_chunk(file_path, idx, section_key, sub, raw_text,
                            case_type=case_type, court_type=court_type).to_document()
            )
            idx += 1

    return docs
