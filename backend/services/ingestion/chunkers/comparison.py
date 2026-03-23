import re
import fitz
import logging
from pathlib import Path
from backend.services.ingestion import Chunk

logger = logging.getLogger(__name__)

_SECTION_NUM = re.compile(r'\b(\d{1,3}[A-Z]?)\b')
_NO_CHANGE_SIGNALS = ["no change", "no corresponding", "same as", "identical", "not changed"]


def _extract_section_number(text: str) -> str:
    match = _SECTION_NUM.search(text or "")
    return match.group(1) if match else ""


def _is_boilerplate(row_cells: list[str]) -> bool:
    combined = " ".join(row_cells).lower()
    return any(signal in combined for signal in _NO_CHANGE_SIGNALS)


def _row_to_sentence(cells: list[str], bnss_sec: str, crpc_sec: str) -> str:
    """
    Convert raw table cells into a natural-language sentence for embedding.
    Raw tab-separated values degrade embedding quality — always convert to prose.
    """
    subject = cells[2].strip() if len(cells) > 2 else ""
    comparison = cells[3].strip() if len(cells) > 3 else ""

    parts = []
    if bnss_sec and crpc_sec:
        parts.append(
            f"BNSS Section {bnss_sec} corresponds to CrPC Section {crpc_sec}."
        )
    elif bnss_sec:
        parts.append(f"BNSS Section {bnss_sec} is a new provision with no CrPC equivalent.")
    elif crpc_sec:
        parts.append(f"CrPC Section {crpc_sec} has no corresponding BNSS section.")

    if subject:
        parts.append(f"Subject: {subject}.")
    if comparison:
        parts.append(comparison)

    return " ".join(parts).strip()


def chunk_comparison(pdf_path: Path, source_name: str) -> tuple[list[Chunk], dict[str, str]]:
    """
    Extract table rows from a comparison table PDF.
    Returns:
        - list of Chunk objects (one per row)
        - crpc_to_bnss dict {crpc_section_number: bnss_section_number}

    Uses PyMuPDF table extraction. Falls back to text heuristics if no tables found.
    """
    chunks: list[Chunk] = []
    crpc_to_bnss: dict[str, str] = {}
    source_stem = Path(source_name).stem

    try:
        doc = fitz.open(str(pdf_path))
    except Exception as e:
        logger.error(f"Cannot open {pdf_path}: {e}")
        return chunks, crpc_to_bnss

    row_index = 0

    for page_num in range(len(doc)):
        page = doc[page_num]

        try:
            tables = page.find_tables()
        except Exception:
            tables = []

        if not tables:
            continue

        for table in tables:
            try:
                rows = table.extract()
            except Exception:
                continue

            for row in rows:
                if not row or all(not cell for cell in row):
                    continue

                # Normalise cells: strip whitespace, replace None with ""
                cells = [str(c).strip() if c else "" for c in row]

                # Skip header rows
                combined = " ".join(cells).lower()
                if any(h in combined for h in ["bnss section", "crpc section", "section no", "sl. no"]):
                    continue

                # Extract section numbers from first two columns
                bnss_sec = _extract_section_number(cells[0] if cells else "")
                crpc_sec = _extract_section_number(cells[1] if len(cells) > 1 else "")

                # Build lookup dict entry
                if crpc_sec and bnss_sec:
                    crpc_to_bnss[crpc_sec] = bnss_sec

                boilerplate = _is_boilerplate(cells)
                sentence = _row_to_sentence(cells, bnss_sec, crpc_sec)

                if not sentence.strip():
                    continue

                chunk_id = f"{source_stem}_row_{row_index}"

                chunks.append(Chunk(
                    text=sentence,
                    chunk_id=chunk_id,
                    source=source_name,
                    legal_layer="comparison",
                    bnss_section=bnss_sec,
                    crpc_section=crpc_sec,
                    subject=cells[2].strip() if len(cells) > 2 else "",
                    is_boilerplate=boilerplate,
                ))

                row_index += 1

    doc.close()

    logger.info(
        f"[comparison] {source_name} → {len(chunks)} chunks, "
        f"{len(crpc_to_bnss)} CrPC→BNS mappings"
    )
    return chunks, crpc_to_bnss
