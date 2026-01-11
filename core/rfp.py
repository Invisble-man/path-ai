from __future__ import annotations

import re
from dataclasses import asdict
from typing import Dict, List, Optional, Tuple

from pypdf import PdfReader


CERTS = ["SDVOSB", "8(a)", "WOSB", "HUBZone", "VOSB", "SDB", "ISO", "CMMC"]


def _extract_email(text: str) -> str:
    m = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", text or "")
    return m.group(0) if m else ""


def _extract_due_date(text: str) -> str:
    # Loose match for dates like 01/10/2026 or January 10, 2026
    patterns = [
        r"\b(0?[1-9]|1[0-2])/(0?[1-9]|[12]\d|3[01])/(20\d{2})\b",
        r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},\s+20\d{2}\b",
    ]
    for p in patterns:
        m = re.search(p, text or "", flags=re.IGNORECASE)
        if m:
            return m.group(0)
    return ""


def _extract_naics(text: str) -> str:
    m = re.search(r"\bNAICS\s*[:#]?\s*(\d{6})\b", text or "", flags=re.IGNORECASE)
    return m.group(1) if m else ""


def _extract_certs(text: str) -> List[str]:
    found = []
    t = (text or "").upper()
    for c in CERTS:
        if c.upper() in t:
            found.append(c)
    # de-dupe preserve order
    out = []
    for x in found:
        if x not in out:
            out.append(x)
    return out


def parse_rfp_from_pdf_bytes(pdf_bytes: bytes, max_pages_to_read: int = 40) -> Tuple[int, str]:
    """
    Returns (pages_total, extracted_text).
    If text is empty, it may be scanned/image-based.
    """
    reader = PdfReader(pdf_bytes)
    total_pages = len(reader.pages)

    n = min(total_pages, max_pages_to_read)
    parts = []
    for i in range(n):
        try:
            parts.append(reader.pages[i].extract_text() or "")
        except Exception:
            parts.append("")

    text = "\n".join(parts).strip()
    return total_pages, text


def extract_fields_from_text(text: str) -> Dict[str, str | List[str]]:
    return {
        "due_date": _extract_due_date(text),
        "submission_email": _extract_email(text),
        "certifications_required": _extract_certs(text),
        "naics": _extract_naics(text),
    }