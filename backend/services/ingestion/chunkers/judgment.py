import re
import logging
from pathlib import Path
from backend.services.ingestion import Chunk

logger = logging.getLogger(__name__)

_SECTION_SIGNALS = ["FACTS", "BACKGROUND", "SUBMISSIONS", "ARGUMENTS", "HELD", "ORDER", "JUDGMENT"]

_PETITIONER_RE = re.compile(r'(?:Petitioner|Appellant|Complainant)\s*[:\-]\s*(.+?)(?:\n|vs?\.)', re.IGNORECASE)
_RESPONDENT_RE = re.compile(r'(?:Respondent|Accused|State)\s*[:\-]\s*(.+?)(?:\n|$)', re.IGNORECASE)
_OUTCOME_RE = re.compile(
    r'\b(convicted|acquitted|dismissed|allowed|quashed|set aside|upheld|confirmed)\b',
    re.IGNORECASE
)
_STATUTE_RE = re.compile(
    r'(?:Section|Sec\.|s\.)\s+(\d{1,3}[A-Z]?)\s+(?:of\s+)?'
    r'(BNS|IPC|BNSS|CrPC|IEA|BSA|Constitution|Article\s+\d+)',
    re.IGNORECASE
)
_CITATION_RE = re.compile(
    r'(AIR\s+\d{4}\s+[A-Z]+\s+\d+|\(\d{4}\)\s+\d+\s+SCC\s+\d+)',
    re.IGNORECASE
)
_YEAR_RE = re.compile(r'\b(19|20)\d{2}\b')
_RATIO_RE = re.compile(
    r'\b(Held[,:]|This Court holds|We hold|We are of the view|In our view)',
    re.IGNORECASE
)


def _extract_statutes(text: str) -> list[str]:
    return [
        f"{m.group(2)} Section {m.group(1)}"
        for m in _STATUTE_RE.finditer(text)
    ]


def _split_judgment(text: str) -> dict[str, str]:
    """
    Split judgment text into structural sections.
    Returns dict with keys: facts, arguments, ratio, order.
    """
    ratio_match = _RATIO_RE.search(text)
    if not ratio_match:
        return {"facts": text[:2000], "ratio": "", "arguments": "", "order": ""}

    ratio_start = ratio_match.start()
    facts_and_args = text[:ratio_start]
    remainder = text[ratio_start:]

    # Try to split facts from arguments by looking for "SUBMISSIONS" or "ARGUMENTS"
    args_match = re.search(r'\b(SUBMISSIONS|ARGUMENTS|CONTENTION)\b', facts_and_args, re.IGNORECASE)
    if args_match:
        facts = facts_and_args[:args_match.start()].strip()
        arguments = facts_and_args[args_match.start():].strip()
    else:
        facts = facts_and_args.strip()
        arguments = ""

    # Split ratio from final order
    order_match = re.search(r'\b(ORDER|ORDERED|DIRECTION|Accordingly)\b', remainder, re.IGNORECASE)
    if order_match:
        ratio = remainder[:order_match.start()].strip()
        order = remainder[order_match.start():].strip()
    else:
        ratio = remainder.strip()
        order = ""

    return {
        "facts": facts[:1500],
        "arguments": arguments[:1000],
        "ratio": ratio[:2000],
        "order": order[:500],
    }


def chunk_judgment(full_text: str, source_name: str) -> list[Chunk]:
    source_stem = Path(source_name).stem

    petitioner_m = _PETITIONER_RE.search(full_text[:500])
    respondent_m = _RESPONDENT_RE.search(full_text[:500])
    citation_m = _CITATION_RE.search(full_text[:500])
    outcome_m = _OUTCOME_RE.search(full_text)
    year_m = _YEAR_RE.search(full_text[:300])

    petitioner = petitioner_m.group(1).strip() if petitioner_m else ""
    respondent = respondent_m.group(1).strip() if respondent_m else ""
    citation = citation_m.group(0).strip() if citation_m else ""
    outcome = outcome_m.group(1).lower() if outcome_m else ""
    year = year_m.group(0) if year_m else ""
    statutes = _extract_statutes(full_text)

    # Case name: "Petitioner v. Respondent"
    case_name = f"{petitioner} v. {respondent}" if petitioner and respondent else source_stem

    sections = _split_judgment(full_text)

    base_meta = dict(
        source=source_name,
        case_name=case_name,
        citation=citation,
        year=year,
        court="unknown",
        petitioner=petitioner,
        respondent=respondent,
        outcome=outcome,
        statutes=statutes,
    )

    chunks: list[Chunk] = []

    if sections["facts"]:
        chunks.append(Chunk(
            text=sections["facts"],
            chunk_id=f"{source_stem}_facts_0",
            legal_layer="case_facts",
            **base_meta,
        ))

    if sections["ratio"]:
        chunks.append(Chunk(
            text=sections["ratio"],
            chunk_id=f"{source_stem}_ratio_0",
            legal_layer="case_ratio",
            **base_meta,
        ))

    if sections["arguments"]:
        chunks.append(Chunk(
            text=sections["arguments"],
            chunk_id=f"{source_stem}_args_0",
            legal_layer="case_analysis",
            **base_meta,
        ))

    logger.info(f"[judgment] {source_name} → {len(chunks)} chunks (outcome: {outcome})")
    return chunks
