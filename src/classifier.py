"""
Classifies PDF links as 仕様書 (SHIYOUSHO), 提案書 (TEIAN), or OTHER.

Classification is based on:
- Link anchor text
- Filename
- Surrounding context text
"""

import re
from enum import Enum
from typing import Optional

from config import SHIYOUSHO_KEYWORDS, TEIANSHŌ_KEYWORDS, SKIP_KEYWORDS


class DocType(str, Enum):
    SHIYOUSHO = "仕様書"
    TEIAN = "提案書"
    OTHER = "OTHER"


def _normalize(text: str) -> str:
    """Normalize text for matching: strip whitespace, normalize full-width chars."""
    if not text:
        return ""
    # Normalize full-width alphanumerics to half-width
    text = text.strip()
    normalized = ""
    for ch in text:
        code = ord(ch)
        if 0xFF01 <= code <= 0xFF5E:
            normalized += chr(code - 0xFEE0)
        else:
            normalized += ch
    return normalized


def _contains_any(text: str, keywords: list) -> bool:
    """Return True if text contains any of the keywords."""
    if not text:
        return False
    text_norm = _normalize(text)
    for kw in keywords:
        if kw in text_norm:
            return True
    return False


def classify_document(
    link_text: str = "",
    filename: str = "",
    context_text: str = "",
) -> DocType:
    """
    Classify a document link into DocType.

    Parameters
    ----------
    link_text : str
        The anchor text of the PDF link.
    filename : str
        The filename portion of the URL (e.g., 'shiyousho_01.pdf').
    context_text : str
        Surrounding text on the page near the link.

    Returns
    -------
    DocType
        SHIYOUSHO, TEIAN, or OTHER.
    """
    # Combine all signals
    combined = " ".join(filter(None, [link_text, filename, context_text]))

    # Skip-list takes priority — these are explicitly unwanted document types
    if _contains_any(combined, SKIP_KEYWORDS):
        return DocType.OTHER

    # Score each type
    shiyousho_score = sum(
        1 for kw in SHIYOUSHO_KEYWORDS if kw in _normalize(combined)
    )
    teian_score = sum(
        1 for kw in TEIANSHŌ_KEYWORDS if kw in _normalize(combined)
    )

    if shiyousho_score == 0 and teian_score == 0:
        return DocType.OTHER

    if shiyousho_score >= teian_score:
        return DocType.SHIYOUSHO
    else:
        return DocType.TEIAN


def extract_filename_from_url(url: str) -> str:
    """Extract the filename portion from a URL."""
    path = url.split("?")[0].rstrip("/")
    return path.split("/")[-1] if "/" in path else path


def classify_url(
    url: str,
    link_text: str = "",
    context_text: str = "",
) -> DocType:
    """
    Convenience wrapper: classify using URL, link text, and context.

    Only applies to PDF files; non-PDFs are always OTHER.
    """
    filename = extract_filename_from_url(url)
    if not filename.lower().endswith(".pdf"):
        return DocType.OTHER
    return classify_document(
        link_text=link_text,
        filename=filename,
        context_text=context_text,
    )
