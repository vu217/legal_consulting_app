import re
import fitz  # PyMuPDF
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DOCUMENT_TYPES = ["legislative_act", "comparison_table", "casebook", "judgment"]

# Signals for each type. Checked in order — first match wins.
# More specific signals listed before generic ones to avoid false positives.
_SIGNALS: dict[str, list[str]] = {
    "comparison_table": [
        "Correspondence Table",
        "BNSS Section",
        "CrPC Section",
        "Comparison Summary",
        "Section of BNSS",
        "Section of CrPC",
        "correspondence between",
    ],
    "judgment": [
        "JUDGMENT",
        "CORAM:",
        "CORAM :",
        "This petition",
        "The appellant",
        "The petitioner",
        "HON'BLE",
        "BEFORE THE HON",
        "IN THE HIGH COURT",
        "IN THE SUPREME COURT",
        "CRIMINAL APPEAL",
        "WRIT PETITION",
        "SLP (CRL",
    ],
    "casebook": [
        " v. ",
        " vs. ",
        " v ",
        "AIR 19",
        "AIR 20",
        "(1999) SCC",
        "(2000) SCC",
        "(2001) SCC",
        "(2002) SCC",
        "(2003) SCC",
        "(2004) SCC",
        "(2005) SCC",
        "(2006) SCC",
        "(2007) SCC",
        "(2008) SCC",
        "(2009) SCC",
        "(2010) SCC",
        "(2011) SCC",
        "(2012) SCC",
        "(2013) SCC",
        "(2014) SCC",
        "(2015) SCC",
        "(2016) SCC",
        "(2017) SCC",
        "(2018) SCC",
        "(2019) SCC",
        "(2020) SCC",
        "(2021) SCC",
        "(2022) SCC",
        "(2023) SCC",
        "(2024) SCC",
        "Petitioner",
        "Respondent",
        "Held:",
        "Unit I",
        "Unit II",
        "Unit III",
        "Law of Crimes",
    ],
    "legislative_act": [
        "Be it enacted",
        "BE IT ENACTED",
        "Chapter I",
        "CHAPTER I",
        "Preliminary",
        "PRELIMINARY",
        "Sanhita",
        "Sanhita, 2023",
        "THE GAZETTE OF INDIA",
        "Ministry of Law",
        "Short title",
    ],
}


def classify_document(pdf_path: Path) -> str:
    """
    Open the PDF, read the first 3000 characters, and return the document type.
    Falls back to 'legislative_act' if no signals match (safest default).
    """
    try:
        doc = fitz.open(str(pdf_path))
        # Grab first two pages worth of text for classification
        sample = ""
        for i in range(min(2, len(doc))):
            sample += doc[i].get_text("text")
        doc.close()
        sample = sample[:3000]
    except Exception as e:
        logger.error(f"Could not read {pdf_path} for classification: {e}")
        return "legislative_act"

    # Check in priority order: comparison_table first (most distinctive),
    # then judgment, then casebook, then legislative_act
    for doc_type in ["comparison_table", "judgment", "casebook", "legislative_act"]:
        for signal in _SIGNALS[doc_type]:
            if signal in sample:
                logger.info(f"Classified '{pdf_path.name}' as '{doc_type}' (signal: '{signal}')")
                return doc_type

    logger.warning(
        f"No classification signal matched for '{pdf_path.name}'. "
        f"Defaulting to 'legislative_act'."
    )
    return "legislative_act"
