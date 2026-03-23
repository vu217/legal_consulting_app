import re
import logging
from pathlib import Path
from backend.services.ingestion import Chunk

logger = logging.getLogger(__name__)

# Signals that mark the start of a ratio/holding block
_RATIO_SIGNALS = [
    r'\bHeld[,:]',
    r'\bIt was held\b',
    r'\bThis Court held\b',
    r'\bThe Court held\b',
    r'\bThe Supreme Court held\b',
    r'\bthe High Court held\b',
    r'\bDecided[,:]',
    r'\bJudgment[,:]',
]
_RATIO_RE = re.compile('|'.join(_RATIO_SIGNALS), re.IGNORECASE)

# Case name patterns: "Virsa Singh v. State of Punjab"
_CASE_NAME_RE = re.compile(
    r'^([A-Z][a-zA-Z\s]+(?:v\.|vs\.|versus)\s+[A-Z][a-zA-Z\s,\.]+)',
    re.MULTILINE
)

# Citation patterns: AIR 1958 SC 465 / (2003) 2 SCC 316
_CITATION_RE = re.compile(
    r'(AIR\s+\d{4}\s+[A-Z]+\s+\d+|'
    r'\(\d{4}\)\s+\d+\s+SCC\s+\d+|'
    r'\d{4}\s+Cri\s+LJ\s+\d+)',
    re.IGNORECASE
)

# Year from citation
_YEAR_RE = re.compile(r'\b(19|20)\d{2}\b')

# Court signals
_COURT_SIGNALS = {
    "SC": ["Supreme Court", "Apex Court", "Hon'ble Supreme Court", "AIR.*SC"],
    "HC": ["High Court", "Hon'ble High Court"],
    "tribunal": ["Tribunal", "Commission", "Forum"],
}

# BNS/IPC section references
_SECTION_REF_RE = re.compile(
    r'\b(?:Section|Sec\.|s\.)\s+(\d{1,3}[A-Z]?)\s+(?:of\s+)?'
    r'(?:BNS|IPC|BNSS|CrPC|Bharatiya|Indian Penal)',
    re.IGNORECASE
)

# Legal principle signals
_PRINCIPLE_SIGNALS = {
    "mens rea": ["mens rea", "guilty mind", "criminal intent"],
    "actus reus": ["actus reus"],
    "transferred intention": ["transferred intention", "transferred malice"],
    "strict liability": ["strict liability"],
    "vicarious liability": ["vicarious liability"],
    "common intention": ["common intention", "Section 34"],
    "grave and sudden provocation": ["grave and sudden provocation", "provocation"],
    "self defence": ["self defence", "self-defence", "private defence"],
    "insanity": ["unsound mind", "insanity", "Section 84"],
    "abetment": ["abetment", "abets"],
    "conspiracy": ["criminal conspiracy"],
    "attempt": ["attempt to commit"],
}

# Syllabus/unit header patterns — exclude these entirely
_SYLLABUS_RE = re.compile(
    r'^(Unit\s+[IVXLC\d]+|UNIT\s+[IVXLC\d]+|Syllabus|SYLLABUS|Course Outline)',
    re.MULTILINE
)

# Case separator: a blank line followed by a new case name or citation
_CASE_SEPARATOR_RE = re.compile(
    r'\n{2,}(?=[A-Z][a-zA-Z\s]+(?:v\.|vs\.|versus)\s+[A-Z])',
)


def _detect_court(text: str) -> str:
    for court, signals in _COURT_SIGNALS.items():
        for signal in signals:
            if re.search(signal, text, re.IGNORECASE):
                return court
    return "unknown"


def _extract_principles(text: str) -> list[str]:
    found = []
    lower = text.lower()
    for principle, signals in _PRINCIPLE_SIGNALS.items():
        if any(s.lower() in lower for s in signals):
            found.append(principle)
    return found


def _extract_bns_sections(text: str) -> list[str]:
    return [f"Section {m.group(1)}" for m in _SECTION_REF_RE.finditer(text)]


def _split_into_three(case_text: str) -> tuple[str, str, str]:
    """
    Split case text into (facts, ratio, analysis).
    Ratio starts at first ratio signal. Analysis is everything after the ratio.
    Facts is everything before the ratio.
    Ratio is capped at 6 sentences.
    """
    ratio_match = _RATIO_RE.search(case_text)

    if not ratio_match:
        return case_text.strip(), "", ""

    facts = case_text[:ratio_match.start()].strip()
    remainder = case_text[ratio_match.start():].strip()

    # Split remainder into sentences to cap ratio at 6
    sentences = re.split(r'(?<=[.!?])\s+', remainder)
    ratio_sentences = sentences[:6]
    analysis_sentences = sentences[6:]

    ratio = " ".join(ratio_sentences).strip()
    analysis = " ".join(analysis_sentences).strip()

    return facts, ratio, analysis


def _split_cases(full_text: str) -> list[str]:
    """
    Split the full casebook text into individual case blocks.
    Uses blank-line-before-case-name as the separator.
    """
    parts = _CASE_SEPARATOR_RE.split(full_text)
    if len(parts) <= 1:
        parts = re.split(r'\n{3,}', full_text)

    # Filter: keep only blocks that contain a case name or citation
    case_blocks = []
    for part in parts:
        part = part.strip()
        if len(part) < 100:
            continue
        if _CASE_NAME_RE.search(part) or _CITATION_RE.search(part):
            case_blocks.append(part)

    return case_blocks


def chunk_casebook(full_text: str, source_name: str) -> list[Chunk]:
    """
    Split casebook into individual cases, then produce three chunks per case:
    case_facts, case_ratio, case_analysis.
    Also extracts doctrine chunks from commentary blocks.
    Strips syllabus/unit header text entirely.
    """
    chunks: list[Chunk] = []
    source_stem = Path(source_name).stem

    # Strip syllabus blocks
    clean = _SYLLABUS_RE.sub('', full_text)

    case_blocks = _split_cases(clean)

    if not case_blocks:
        logger.warning(f"[casebook] No case blocks found in {source_name}. Emitting as single chunk.")
        chunks.append(Chunk(
            text=full_text[:3000],
            chunk_id=f"{source_stem}_raw_0",
            source=source_name,
            legal_layer="case_facts",
        ))
        return chunks

    for i, case_text in enumerate(case_blocks):
        # Extract metadata
        name_match = _CASE_NAME_RE.search(case_text)
        case_name = name_match.group(1).strip() if name_match else f"Case_{i}"

        citation_match = _CITATION_RE.search(case_text)
        citation = citation_match.group(0).strip() if citation_match else ""

        year_match = _YEAR_RE.search(citation or case_text[:200])
        year = year_match.group(0) if year_match else ""

        court = _detect_court(case_text)
        bns_sections = _extract_bns_sections(case_text)
        principles = _extract_principles(case_text)

        facts_text, ratio_text, analysis_text = _split_into_three(case_text)

        base_meta = dict(
            source=source_name,
            case_name=case_name,
            citation=citation,
            year=year,
            court=court,
            bns_sections=bns_sections,
            principles=principles,
        )

        # facts chunk (always emit)
        if facts_text:
            chunks.append(Chunk(
                text=facts_text[:1500],
                chunk_id=f"{source_stem}_facts_{i}",
                legal_layer="case_facts",
                **base_meta,
            ))

        # ratio chunk (most important — always emit if we have it)
        if ratio_text:
            chunks.append(Chunk(
                text=ratio_text,
                chunk_id=f"{source_stem}_ratio_{i}",
                legal_layer="case_ratio",
                **base_meta,
            ))

        # analysis chunk (lower priority)
        if analysis_text and len(analysis_text) > 100:
            chunks.append(Chunk(
                text=analysis_text[:2000],
                chunk_id=f"{source_stem}_analysis_{i}",
                legal_layer="case_analysis",
                **base_meta,
            ))

    logger.info(f"[casebook] {source_name} → {len(case_blocks)} cases → {len(chunks)} chunks")
    return chunks
