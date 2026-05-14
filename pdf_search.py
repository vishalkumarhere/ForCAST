"""PDF text extraction and keyword search helpers."""

from __future__ import annotations

import re
from pathlib import Path

DOCUMENTS_DIR = Path("Documents")

STATE_NAMES: dict[str, str] = {
    "AL": "Alabama", "AR": "Arkansas", "AZ": "Arizona", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida",
    "GA": "Georgia", "IA": "Iowa", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "MA": "Massachusetts", "MD": "Maryland", "ME": "Maine", "MI": "Michigan",
    "MN": "Minnesota", "MO": "Missouri", "MS": "Mississippi", "MT": "Montana",
    "NC": "North Carolina", "ND": "North Dakota", "NE": "Nebraska",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NV": "Nevada", "NY": "New York", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island",
    "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee",
    "TX": "Texas", "UT": "Utah", "VA": "Virginia", "VT": "Vermont",
    "WA": "Washington", "WI": "Wisconsin", "WV": "West Virginia", "WY": "Wyoming",
}


def list_states() -> list[str]:
    """Return sorted list of state abbreviations that have a subfolder under Documents/."""
    if not DOCUMENTS_DIR.exists():
        return []
    return sorted(
        d.name for d in DOCUMENTS_DIR.iterdir()
        if d.is_dir() and d.name in STATE_NAMES
    )


def list_pdfs_for_state(state_abbr: str) -> list[Path]:
    """Return all PDFs inside Documents/<state_abbr>/."""
    state_dir = DOCUMENTS_DIR / state_abbr
    if not state_dir.exists():
        return []
    return sorted(state_dir.rglob("*.pdf"))


def list_pdf_files() -> list[Path]:
    """Return all PDFs found recursively under Documents/."""
    if not DOCUMENTS_DIR.exists():
        return []
    return sorted(DOCUMENTS_DIR.rglob("*.pdf"))


def extract_pages(pdf_path: Path) -> list[tuple[int, str]]:
    """Return list of (page_number, text) for every page in the PDF."""
    try:
        from pypdf import PdfReader
    except ImportError:
        raise ImportError("pypdf is required: pip install pypdf")

    reader = PdfReader(str(pdf_path))
    pages = []
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        pages.append((i, text))
    return pages


def search_pdf(
    pdf_path: Path,
    query: str,
    context_chars: int = 300,
) -> list[dict]:
    """
    Search a PDF for *query* (case-insensitive).

    Returns a list of match dicts:
        page        – 1-based page number
        snippet     – surrounding text with the match highlighted (markdown bold)
        match_start – char offset of match within page text (for sorting)
    """
    if not query.strip():
        return []

    pattern = re.compile(re.escape(query.strip()), re.IGNORECASE)
    results = []

    for page_num, text in extract_pages(pdf_path):
        for m in pattern.finditer(text):
            start = max(0, m.start() - context_chars)
            end = min(len(text), m.end() + context_chars)
            snippet = text[start:end].strip()
            # Bold the matched term inside the snippet
            snippet = pattern.sub(lambda x: f"**{x.group()}**", snippet)
            # Clean up excessive whitespace / newlines
            snippet = re.sub(r"\n{3,}", "\n\n", snippet)
            results.append(
                {
                    "page": page_num,
                    "snippet": snippet,
                    "match_start": m.start(),
                }
            )

    return results
