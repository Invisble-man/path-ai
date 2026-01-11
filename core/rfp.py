from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
import re
from typing import List, Optional

import pdfplumber
from pypdf import PdfReader


@dataclass
class ParsedRFP:
    pages: int = 0
    text: str = ""
    due_date: Optional[str] = None
    submission_email: Optional[str] = None
    certifications_required: List[str] = field(default_factory=list)
    eligibility_rules: List[str] = field(default_factory=list)
    past_performance_requirements: List[str] = field(default_factory=list)
    requirements: List[str] = field(default_factory=list)
    flags: List[str] = field(default_factory=list)


EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)

# Common formats seen in solicitations
DUE_DATE_RE = re.compile(
    r"(OFFER DUE DATE\s*/?\s*LOCAL\s*TIME\s*[:\-]?\s*)(?P<date>\d{1,2}/\d{1,2}/\d{2,4})\s*(?P<time>\d{1,2}:\d{2}\s*(AM|PM)?)?\s*(?P<tz>[A-Z]{2,4})?",
    re.IGNORECASE,
)

CERT_KEYWORDS = [
    "SDVOSB",
    "8(a)",
    "HUBZone",
    "WOSB",
    "EDWOSB",
    "CMMC",
    "ISO",
    "SAM",
    "UEI",
    "CAGE",
]


def _safe_page_count(pdf_bytes: bytes) -> int:
    try:
        reader = PdfReader(BytesIO(pdf_bytes))
        return len(reader.pages)
    except Exception:
        return 0


def _extract_text_pdfplumber(pdf_bytes: bytes, max_pages: int) -> str:
    out: List[str] = []
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        total = len(pdf.pages)
        limit = min(total, max_pages)
        for i in range(limit):
            page = pdf.pages[i]
            txt = page.extract_text() or ""
            txt = txt.replace("\x00", "").strip()
            if txt:
                out.append(txt)
    return "\n\n".join(out).strip()


def _find_due_date(text: str) -> Optional[str]:
    m = DUE_DATE_RE.search(text)
    if not m:
        return None
    date = (m.group("date") or "").strip()
    time = (m.group("time") or "").strip()
    tz = (m.group("tz") or "").strip()
    parts = [p for p in [date, time, tz] if p]
    return " ".join(parts) if parts else None


def _find_emails(text: str) -> List[str]:
    emails = EMAIL_RE.findall(text or "")
    # De-dupe, preserve order
    seen = set()
    uniq = []
    for e in emails:
        e_norm = e.lower()
        if e_norm not in seen:
            seen.add(e_norm)
            uniq.append(e)
    return uniq


def _detect_certifications(text: str) -> List[str]:
    found = []
    upper = (text or "").upper()
    for k in CERT_KEYWORDS:
        if k.upper() in upper:
            found.append(k)
    # De-dupe
    return sorted(set(found), key=lambda x: x.lower())


def _extract_requirement_lines(text: str, max_items: int = 80) -> List[str]:
    """
    Lightweight heuristic:
    - Grab lines containing SHALL / MUST / REQUIRED / WILL
    - Also grab bullet-like lines
    """
    if not text:
        return []

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    candidates: List[str] = []

    trigger = re.compile(r"\b(shall|must|required|will be required|offeror shall|contractor shall)\b", re.IGNORECASE)
    bullet = re.compile(r"^(\-|\*|•|\d+\.)\s+")

    for ln in lines:
        if len(ln) < 18:
            continue
        if trigger.search(ln) or bullet.match(ln):
            # avoid garbage repeated headers/footers
            if "page" in ln.lower() and re.search(r"\bpage\s+\d+\b", ln.lower()):
                continue
            candidates.append(ln)

    # De-dupe while preserving order
    seen = set()
    uniq = []
    for c in candidates:
        c_norm = re.sub(r"\s+", " ", c).strip().lower()
        if c_norm in seen:
            continue
        seen.add(c_norm)
        uniq.append(re.sub(r"\s+", " ", c).strip())
        if len(uniq) >= max_items:
            break
    return uniq


def parse_rfp_from_pdf_bytes(pdf_bytes: bytes, max_pages_to_read: int = 60) -> ParsedRFP:
    """
    Robust PDF parser designed for Streamlit uploads (bytes in memory).
    - Counts total pages safely
    - Extracts text from first N pages (default 60) to avoid crashing on huge PDFs
    """
    parsed = ParsedRFP()

    if not pdf_bytes:
        parsed.flags.append("No PDF bytes received.")
        return parsed

    parsed.pages = _safe_page_count(pdf_bytes)

    # Huge PDF protection (your TRGR file is enormous)
    if parsed.pages >= 300:
        parsed.flags.append(
            f"Large PDF detected ({parsed.pages} pages). Extracting only the first {max_pages_to_read} pages to stay fast and stable."
        )

    try:
        parsed.text = _extract_text_pdfplumber(pdf_bytes, max_pages=max_pages_to_read)
    except Exception as e:
        parsed.text = ""
        parsed.flags.append(f"Text extraction failed: {type(e).__name__}")

    if not parsed.text.strip():
        parsed.flags.append("No extractable text found in sampled pages (may be scanned, protected, or extraction failed).")
        return parsed

    parsed.due_date = _find_due_date(parsed.text)

    emails = _find_emails(parsed.text)
    parsed.submission_email = emails[0] if emails else None

    parsed.certifications_required = _detect_certifications(parsed.text)

    # Requirements seed (heuristic)
    parsed.requirements = _extract_requirement_lines(parsed.text, max_items=100)

    # Extra “rule of thumb” buckets (very lightweight)
    upper = parsed.text.upper()
    if "PAST PERFORMANCE" in upper:
        parsed.past_performance_requirements.append("Past Performance is mentioned (review section for details).")
    if "EVALUATION" in upper:
        parsed.eligibility_rules.append("Evaluation criteria section is present (review and map to response).")

    return parsed