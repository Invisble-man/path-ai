import re
from typing import Dict, Any, List

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
DATE_RE = re.compile(r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\w+\s+\d{1,2},\s+\d{4})\b", re.IGNORECASE)

def extract_metadata(text: str) -> Dict[str, str]:
    """
    Lightweight heuristics to pull key metadata from the RFP text.
    """
    meta = {
        "due_date": "",
        "submit_email": "",
        "submission_method": "",
        "agency": "",
        "solicitation": "",
        "title": "",
    }

    if not text:
        return meta

    emails = EMAIL_RE.findall(text)
    if emails:
        meta["submit_email"] = emails[0]

    dates = DATE_RE.findall(text)
    if dates:
        meta["due_date"] = dates[0]

    # Very rough title guess: first non-empty line under 120 chars
    for line in text.splitlines():
        l = line.strip()
        if 10 <= len(l) <= 120:
            meta["title"] = l
            break

    # solicitation guess
    sol_match = re.search(r"(Solicitation|RFP|RFQ|RFI)\s*(No\.|Number|#)?\s*[:\-]?\s*([A-Za-z0-9\-_.]{4,})", text, re.IGNORECASE)
    if sol_match:
        meta["solicitation"] = sol_match.group(3)

    return meta

def extract_requirements_fast(text: str, max_items: int = 40) -> List[Dict[str, Any]]:
    """
    Non-AI baseline: pulls bullet-like lines and shall/must language.
    """
    reqs = []
    if not text:
        return reqs

    lines = [l.strip() for l in text.splitlines() if l.strip()]
    candidates = []
    for l in lines:
        if len(l) < 8 or len(l) > 220:
            continue
        if any(k in l.lower() for k in ["shall", "must", "required", "requirement", "offeror", "vendor"]):
            candidates.append(l)
        elif l.startswith(("-", "•")):
            candidates.append(l.lstrip("-• ").strip())

    # de-dup while preserving order
    seen = set()
    for c in candidates:
        key = c.lower()
        if key in seen:
            continue
        seen.add(key)
        reqs.append({
            "requirement_id": f"REQ-{len(reqs)+1:03d}",
            "requirement": c,
            "status": "Not started",
            "notes": "",
            "owner": "",
            "evidence": "",
        })
        if len(reqs) >= max_items:
            break

    return reqs