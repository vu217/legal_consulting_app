import re
import uuid
import logging
from pathlib import Path
from backend.services.ingestion import Chunk

logger = logging.getLogger(__name__)

# Section heading patterns:
# "100. Murder" / "100A. Attempt" / "CHAPTER VI" / "PRELIMINARY"
_SECTION_HEADING = re.compile(
    r'^(\d{1,3}[A-Z]?)\.\s+(.+)$',
    re.MULTILINE
)

_CHAPTER_HEADING = re.compile(
    r'^(CHAPTER\s+[IVXLC]+|Chapter\s+[IVXLC]+)\s*[\.\-]?\s*(.*)$',
    re.MULTILINE
)

# Marginal notes appear as bracketed or indented annotations before/after section headers
# e.g. "[Culpable homicide]" or "[Murder]"
_MARGINAL_NOTE = re.compile(r'^\[([^\]]{3,60})\]', re.MULTILINE)

# Cross-reference patterns within section text
_CROSS_REF = re.compile(
    r'\bsection\s+(\d{1,3}[A-Z]?)\b',
    re.IGNORECASE
)

# Detect act name from text
_ACT_SIGNALS = {
    "BNS": ["Bharatiya Nyaya Sanhita", "BNS"],
    "BNSS": ["Bharatiya Nagarik Suraksha Sanhita", "BNSS"],
    "BSA": ["Bharatiya Sakshya Adhiniyam", "BSA"],
    "IPC": ["Indian Penal Code", "IPC"],
    "CrPC": ["Code of Criminal Procedure", "CrPC"],
    "IEA": ["Indian Evidence Act", "IEA"],
}


def _detect_act(full_text: str) -> str:
    for act_name, signals in _ACT_SIGNALS.items():
        for signal in signals:
            if signal in full_text:
                return act_name
    return "unknown"


def _detect_year(full_text: str) -> str:
    match = re.search(r'\b(19|20)\d{2}\b', full_text[:500])
    return match.group(0) if match else ""


def _extract_cross_refs(text: str) -> list[str]:
    return [f"Section {m.group(1)}" for m in _CROSS_REF.finditer(text)]


def chunk_legislative(full_text: str, source_name: str) -> list[Chunk]:
    """
    Split a legislative act into one Chunk per section.
    Also emits a full_act_intro chunk (first 2000 chars) for top-level queries.
    """
    chunks: list[Chunk] = []
    act = _detect_act(full_text)
    year = _detect_year(full_text)
    current_chapter = ""
    source_stem = Path(source_name).stem

    # Emit intro chunk
    intro_text = full_text[:2000].strip()
    if intro_text:
        chunks.append(Chunk(
            text=intro_text,
            chunk_id=f"{source_stem}_intro_0",
            source=source_name,
            legal_layer="statute",
            section_number="intro",
            section_title="Full act introduction",
            chapter="",
            act=act,
            year=year,
        ))

    # Find all section positions
    section_matches = list(_SECTION_HEADING.finditer(full_text))
    chapter_matches = {m.start(): m for m in _CHAPTER_HEADING.finditer(full_text)}

    if not section_matches:
        logger.warning(f"No sections detected in {source_name}. Emitting as single chunk.")
        chunks.append(Chunk(
            text=full_text[:6000],
            chunk_id=f"{source_stem}_full_0",
            source=source_name,
            legal_layer="statute",
            section_number="",
            section_title="",
            act=act,
            year=year,
        ))
        return chunks

    for i, match in enumerate(section_matches):
        section_num = match.group(1)
        section_title_raw = match.group(2).strip()

        # Determine chapter context by finding the nearest chapter heading before this section
        for pos, ch_match in chapter_matches.items():
            if pos < match.start():
                current_chapter = ch_match.group(0).strip()

        # Extract marginal note if present just before the section heading
        preceding_text = full_text[max(0, match.start() - 100): match.start()]
        marginal = _MARGINAL_NOTE.search(preceding_text)
        if marginal:
            section_title_raw = marginal.group(1).strip()

        # Body: from this section heading to the next, capped at 2000 chars
        start = match.start()
        end = section_matches[i + 1].start() if i + 1 < len(section_matches) else len(full_text)
        body = full_text[start:end].strip()

        # Cap individual section at 2000 chars to keep embedding quality high
        if len(body) > 2000:
            body = body[:2000]

        cross_refs = _extract_cross_refs(body)

        chunk_id = f"{source_stem}_s{section_num}_{i}"

        chunks.append(Chunk(
            text=body,
            chunk_id=chunk_id,
            source=source_name,
            legal_layer="statute",
            section_number=section_num,
            section_title=section_title_raw,
            chapter=current_chapter,
            act=act,
            year=year,
            cross_refs=cross_refs,
        ))

    logger.info(f"[legislative] {source_name} → {len(chunks)} chunks (act: {act})")
    return chunks
