from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Tuple, Optional

import pdfplumber


_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_DATE_RE = re.compile(
    r"\b(?:"
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+\d{1,2},\s+\d{4}"
    r"|"
    r"\d{1,2}/\d{1,2}/\d{2,4}"
    r"|"
    r"\d{4}-\d{2}-\d{2}"
    r")\b",
    re.IGNORECASE,
)

# Very lightweight signals (we will improve later with AI)
_CERT_KEYWORDS = [
    "SDVOSB",
    "8(a)",
    "WOSB",
    "EDWOSB",
    "HUBZone",
    "HUBZONE",
    "VOSB",
    "Small Business",
    "SAM.gov",
    "CAGE",
    "UEI",
]
_ELIGIBILITY_HINTS = [
    "eligible",
    "eligibility",
    "must be",
    "shall be",
    "offeror shall",
    "vendor shall",
    "requirements for offerors",
    "set-aside",
]
_PAST_PERF_HINTS = [
    "past performance",
    "references",
    "relevant experience",
    "experience requirement",
    "previous contract",
]


@dataclass
class ParsedRFP:
    text: str
    pages: int
    due_date: str
    submission_email: str
    requirements: List[str]
    certifications_required: List[str]
    eligibility_rules: List[str]
    past_performance_requirements: List[str]
    flags: List[str]


def extract_text_from_pdf(file_bytes: bytes) -> Tuple[str, int, List[str]]:
    """
    Extract text + page count from a PDF using pdfplumber.
    Returns (text, pages, flags).
    This function is designed to never crash the app: it returns safe defaults.
    """
    flags: List[str] = []
    if not file_bytes:
        return "", 0, ["No file bytes provided."]

    try:
        with pdfplumber.open(file_bytes) as pdf:
            pages = len(pdf.pages)
            chunks: List[str] = []
            for p in pdf.pages:
                try:
                    t = p.extract_text() or ""
                    chunks.append(t)
                except Exception:
                    # Continue extracting other pages
                    chunks.append("")
            text = "\n".join(chunks).strip()

        if not text:
            flags.append("PDF extracted but text appears empty (scan/image-based PDF).")
        return text, pages, flags
    except Exception as e:
        return "", 0, [f"PDF extraction error: {e}"]


def _find_submission_email(text: str) -> str:
    emails = list(dict.fromkeys(_EMAIL_RE.findall(text or "")))  # de-dup preserve order
    if not emails:
        return ""
    # Heuristic: prefer ones near "submit" or "proposal"
    lowered = (text or "").lower()
    for e in emails:
        idx = lowered.find(e.lower())
        window = lowered[max(0, idx - 80): idx + 80] if idx >= 0 else ""
        if "submit" in window or "proposal" in window or "offers" in window:
            return e
    return emails[0]


def _find_due_date(text: str) -> str:
    # Heuristic: find date strings near “due”, “deadline”, “submit by”
    dates = list(dict.fromkeys(_DATE_RE.findall(text or "")))
    if not dates:
        return ""

    lowered = (text or "").lower()
    for d in dates:
        idx = lowered.find(d.lower())
        window = lowered[max(0, idx - 120): idx + 120] if idx >= 0 else ""
        if "due" in window or "deadline" in window or "submit" in window or "closing" in window:
            return d
    return dates[0]


def _collect_bullets(text: str) -> List[str]:
    """
    Pulls bullet-ish requirement lines in a simple way.
    This will be improved later with AI requirement extraction.
    """
    if not text:
        return []

    lines = [ln.strip() for ln in text.splitlines()]
    bullets: List[str] = []
    for ln in lines:
        if len(ln) < 8:
            continue
        if len(ln) > 240:
            continue
        if ln.startswith(("-", "•", "*")):
            bullets.append(ln.lstrip("-•* ").strip())
            continue
        # e.g., "1. Provide ..." or "a) ..."
        if re.match(r"^(\d+\.|\d+\)|[a-zA-Z]\)|[a-zA-Z]\.)\s+\S+", ln):
            bullets.append(re.sub(r"^(\d+\.|\d+\)|[a-zA-Z]\)|[a-zA-Z]\.)\s+", "", ln).strip())

    # De-dup while preserving order
    seen = set()
    out: List[str] = []
    for b in bullets:
        key = b.lower()
        if key not in seen:
            seen.add(key)
            out.append(b)
    return out[:80]  # safety cap


def _extract_certifications(text: str) -> List[str]:
    if not text:
        return []
    found = []
    for kw in _CERT_KEYWORDS:
        if re.search(rf"\b{re.escape(kw)}\b", text, flags=re.IGNORECASE):
            found.append(kw.upper() if kw.lower() == "hubzone" else kw)
    # De-dup
    return list(dict.fromkeys(found))


def _extract_eligibility_rules(text: str) -> List[str]:
    if not text:
        return []
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    rules: List[str] = []

    for ln in lines:
        low = ln.lower()
        if any(h in low for h in _ELIGIBILITY_HINTS):
            if 20 <= len(ln) <= 240:
                rules.append(ln)

    # de-dup and cap
    rules = list(dict.fromkeys(rules))
    return rules[:40]


def _extract_past_performance(text: str) -> List[str]:
    if not text:
        return []
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    pp: List[str] = []
    for ln in lines:
        low = ln.lower()
        if any(h in low for h in _PAST_PERF_HINTS):
            if 20 <= len(ln) <= 240:
                pp.append(ln)
    pp = list(dict.fromkeys(pp))
    return pp[:40]


def parse_rfp_from_pdf_bytes(file_bytes: bytes) -> ParsedRFP:
    """
    One-stop parse: extract text/pages + key signals.
    Safe defaults if anything goes sideways.
    """
    text, pages, flags = extract_text_from_pdf(file_bytes)

    due = _find_due_date(text)
    email = _find_submission_email(text)
    requirements = _collect_bullets(text)

    certs = _extract_certifications(text)
    eligibility = _extract_eligibility_rules(text)
    past_perf = _extract_past_performance(text)

    if pages == 0:
        flags.append("Could not determine page count.")
    if not due:
        flags.append("Due date not detected (you can still proceed).")
    if not email:
        flags.append("Submission email not detected (you can still proceed).")
    if not requirements:
        flags.append("Requirements list not detected yet (compatibility matrix will be limited).")

    return ParsedRFP(
        text=text,
        pages=pages,
        due_date=due,
        submission_email=email,
        requirements=requirements,
        certifications_required=certs,
        eligibility_rules=eligibility,
        past_performance_requirements=past_perf,
        flags=flags,
    )