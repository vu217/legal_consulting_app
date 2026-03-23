import re
import logging

logger = logging.getLogger(__name__)

# Gazette registration ID pattern: CG-DL-E-29092023-248880
_GAZETTE_ID = re.compile(r'CG-DL-[A-Z]-\d{8}-\d+')

# Page numbers standing alone on a line
_PAGE_NUMBER = re.compile(r'^\s*\d{1,4}\s*$', re.MULTILINE)

# Long separator lines (5+ repeated characters)
_SEPARATOR = re.compile(r'[-_=*]{5,}')

# Common header/footer strings repeated across pages
_BOILERPLATE_STRINGS = [
    "THE GAZETTE OF INDIA EXTRAORDINARY",
    "EXTRAORDINARY PART II",
    "REGISTERED NO. DL",
    "Hkkjr dk jkti=k",         # Devanagari "Gazette of India"
    "\u0905\u0938\u093e\u0927\u093e\u0930\u0923",                  # "Extraordinary" in Hindi
    "\u092d\u093e\u0917 II",                   # "Part II" in Hindi
    "MINISTRY OF LAW AND JUSTICE",
    "Ministry of Law and Justice",
    "CIN:",
    "www.egazette.gov.in",
]

# Devanagari Unicode block: U+0900 to U+097F
_DEVANAGARI = re.compile(r'[\u0900-\u097F]+')

# 3+ consecutive blank lines → single blank line
_MULTI_BLANK = re.compile(r'\n{3,}')

# Copyright footers
_COPYRIGHT = re.compile(
    r'\u00a9.*?reserved\.?', re.IGNORECASE | re.DOTALL
)

# Court seal / stamp artifacts (common in scanned PDFs)
_SEAL_ARTIFACTS = re.compile(
    r'(SEAL|STAMP|CERTIFIED COPY|TRUE COPY|CERTIFIED TRUE COPY)',
    re.IGNORECASE
)


def clean_text(raw: str) -> str:
    """
    Apply all cleaning passes in sequence.
    Returns cleaned text ready for chunking.
    Input is the raw text from PyMuPDF page extraction.
    """
    text = raw

    # Remove gazette registration IDs
    text = _GAZETTE_ID.sub('', text)

    # Remove repeated boilerplate strings
    for bp in _BOILERPLATE_STRINGS:
        text = text.replace(bp, '')

    # Remove Devanagari blocks (garbled in most PyMuPDF extractions of bilingual PDFs)
    text = _DEVANAGARI.sub('', text)

    # Remove copyright footers
    text = _COPYRIGHT.sub('', text)

    # Remove court seal artifacts
    text = _SEAL_ARTIFACTS.sub('', text)

    # Remove separator lines
    text = _SEPARATOR.sub('', text)

    # Remove standalone page numbers
    text = _PAGE_NUMBER.sub('', text)

    # Collapse multiple blank lines
    text = _MULTI_BLANK.sub('\n\n', text)

    # Strip leading/trailing whitespace per line
    lines = [line.rstrip() for line in text.split('\n')]
    text = '\n'.join(lines)

    # Final strip
    text = text.strip()

    return text


def clean_pdf_pages(pages: list[str]) -> list[str]:
    """
    Apply clean_text to each page string individually.
    Returns list of cleaned page strings in the same order.
    """
    return [clean_text(p) for p in pages]
