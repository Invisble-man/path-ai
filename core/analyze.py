from __future__ import annotations
import re
from typing import Dict, List, Tuple
from dateutil import parser as dateparser

from pypdf import PdfReader


CERT_KEYWORDS = [
    ("SDVOSB (Service-Disabled Veteran-Owned Small Business)", ["sdvosb", "service-disabled veteran", "service disabled veteran"]),
    ("VOSB (Veteran-Owned Small Business)", ["vosb", "veteran-owned"]),
    ("8(a)", ["8(a)", "eight(a)"]),
    ("HUBZone", ["hubzone"]),
    ("WOSB (Women-Owned Small Business)", ["wosb", "women-owned"]),
    ("EDWOSB (Economically Disadvantaged WOSB)", ["edwosb", "economically disadvantaged women-owned"]),
    ("Small Business", ["small business set-aside", "small business set aside"]),
]


def _safe_extract_pdf_pages(file_bytes: bytes) -> int:
    try:
        reader = PdfReader(file_bytes)
        return len(reader.pages)
    except Exception:
        return 0


def _regex_pick(patterns: List[str], text: str) -> str:
    for p in patterns:
        m = re.search(p, text, flags=re.IGNORECASE | re.MULTILINE)
        if m:
            val = m.group(1).strip()
            return re.sub(r"\s+", " ", val)
    return ""


def _find_emails(text: str) -> List[str]:
    emails = re.findall(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", text, flags=re.IGNORECASE)
    # unique preserve order
    seen = set()
    out = []
    for e in emails:
        if e.lower() not in seen:
            out.append(e)
            seen.add(e.lower())
    return out


def _parse_due_date(text: str) -> str:
    # Look for “due”, “submission”, etc
    candidates = []
    for line in text.splitlines():
        if re.search(r"(due|submit|submission|closing date|response date)", line, re.IGNORECASE):
            candidates.append(line.strip())
    blob = "\n".join(candidates[:40]) or text[:5000]

    # Extract a date-ish substring
    # Examples: "January 10, 2026", "10 Jan 2026", "01/10/2026"
    date_like = _regex_pick(
        [
            r"(?:due|submission|closing date|response date)\s*[:\-]?\s*(.*)$",
            r"(\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2},\s*\d{4}\b)",
            r"(\b\d{1,2}/\d{1,2}/\d{2,4}\b)",
            r"(\b\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{4}\b)",
        ],
        blob,
    )
    if not date_like:
        return ""

    # Attempt parse
    try:
        dt = dateparser.parse(date_like, fuzzy=True)
        if dt:
            return dt.strftime("%b %d, %Y %I:%M %p") if (dt.hour or dt.minute) else dt.strftime("%b %d, %Y")
    except Exception:
        return date_like

    return date_like


def _detect_required_certs(text: str) -> List[str]:
    t = text.lower()
    found = []
    for cert_name, keys in CERT_KEYWORDS:
        if any(k in t for k in keys):
            found.append(cert_name)
    return found


def analyze_rfp(file_bytes: bytes, filename: str, extracted_text: str) -> Tuple[int, Dict, List[Dict]]:
    pages = _safe_extract_pdf_pages(file_bytes)

    text = extracted_text or ""
    text2 = text[:20000]  # keep it lightweight

    meta = {
        "solicitation_number": _regex_pick(
            [
                r"(?:solicitation|rfp|rfi|rfq)\s*(?:number|no\.?)\s*[:\-]?\s*([A-Z0-9\-_.]+)",
                r"(?:solicitation)\s*[:\-]?\s*([A-Z0-9\-_.]+)",
            ],
            text2,
        ),
        "contract_title": _regex_pick(
            [
                r"(?:title|requirement)\s*[:\-]?\s*(.+)$",
                r"(?:subject)\s*[:\-]?\s*(.+)$",
            ],
            text2,
        ),
        "agency": _regex_pick([r"(?:agency|department|office)\s*[:\-]?\s*(.+)$"], text2),
        "due_date": _parse_due_date(text),
        "submission_email": "",
        "submission_method": _regex_pick([r"(?:submit|submission)\s*(?:via|through)\s*[:\-]?\s*(.+)$"], text2),
        "place_of_performance": _regex_pick([r"(?:place of performance|pop)\s*[:\-]?\s*(.+)$"], text2),
        "naics": _regex_pick([r"(?:naics)\s*[:\-]?\s*([0-9]{6})"], text2),
        "set_aside": _regex_pick([r"(?:set[-\s]?aside)\s*[:\-]?\s*(.+)$"], text2),
        "required_certs": _detect_required_certs(text),
    }

    emails = _find_emails(text2)
    if emails:
        meta["submission_email"] = emails[0]

    # Requirements extraction (simple heuristic):
    # Grab lines with MUST / SHALL / REQUIRED / SUBMIT / PROVIDE
    req_lines = []
    for line in text.splitlines():
        if re.search(r"\b(must|shall|required|provide|submit)\b", line, re.IGNORECASE):
            ln = re.sub(r"\s+", " ", line).strip()
            if 30 <= len(ln) <= 240:
                req_lines.append(ln)

    # Deduplicate and cap (memory safety)
    seen = set()
    reqs = []
    for ln in req_lines:
        key = ln.lower()
        if key not in seen:
            seen.add(key)
            reqs.append(ln)
        if len(reqs) >= 80:
            break

    matrix = []
    for i, r in enumerate(reqs, start=1):
        eligibility_tag = ""
        # attach eligibility tags to certain requirements
        rlow = r.lower()
        if "sdvosb" in rlow or "service-disabled veteran" in rlow:
            eligibility_tag = "SDVOSB (Service-Disabled Veteran-Owned Small Business)"
        elif "hubzone" in rlow:
            eligibility_tag = "HUBZone"
        elif "8(a)" in rlow:
            eligibility_tag = "8(a)"
        elif "wosb" in rlow or "women-owned" in rlow:
            eligibility_tag = "WOSB (Women-Owned Small Business)"
        elif "veteran-owned" in rlow or "vosb" in rlow:
            eligibility_tag = "VOSB (Veteran-Owned Small Business)"

        matrix.append({
            "id": f"R{i:03d}",
            "requirement": r,
            "status": "Unknown",
            "evidence": "",
            "notes": "",
            "eligibility_tag": eligibility_tag,
        })

    return pages, meta, matrix